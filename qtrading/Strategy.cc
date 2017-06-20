#include "Strategy.h"

// remove io stream when cout (printfs) go away
#include <iostream>
#include <fstream>
#include <iomanip>

#include <bb/core/Log.h>
#include <bb/core/env.h>
#include <bb/core/Error.h>
#include <bb/core/EFeedType.h>
#include <bb/core/EquitySecurityInfo.h>
#include <bb/core/messages_autogen.h>
#include <bb/core/usermsg.h>
#include <bb/core/ptime.h>
#include <bb/core/CommoditiesSpecifications.h>

#include <bb/db/TradingCalendar.h>
#include <bb/db/DayInfo.h>

#include <bb/clientcore/IBook.h>
#include <bb/clientcore/BookBuilder.h>
#include <bb/clientcore/IClientTimer.h>
#include <bb/clientcore/PriceProvider.h>
#include <bb/clientcore/BbL1TickProvider.h>
#include <bb/clientcore/EventDist.h>

#include <bb/trading/Trader.h>
#include <bb/trading/IssuedOrderTracker.h>
#include <bb/trading/trading.h>
#include <bb/trading/OrderPositionTracker.h>
#include <bb/trading/InstrumentContext.h>
#include <bb/trading/Order.h>
#include <bb/trading/IPositionProvider.h>
#include <bb/trading/PnLProvider.h>

namespace alphaless {

/// This is an implementation of IBookListener which prints a MarketLevel on every update.
Strategy::Strategy( const InstrVector& instruments,
                    const bb::trading::TradingContextPtr& tradingContext,
                    const StrategySettings &strategySettings )

    : m_instrs ( instruments )
    , m_strategySettings ( strategySettings )
    , m_market( bb::str2mktdest( strategySettings.market.c_str() ) )
    , m_tradingContext( tradingContext )
    , m_clientContext( tradingContext->getClientContext() )
    , m_clockMonitor( m_clientContext->getClockMonitor() )
    , m_timer( m_clientContext->getClientTimer() )

{
    bb::date_t sd = bb::date_t( m_clientContext->getStartTimeval() );
    m_startTime = bb::timeval_t::make_time( sd.year(), sd.month(), sd.day(), m_strategySettings.start_hour, m_strategySettings.start_minute, m_strategySettings.start_second );
    m_endTime = bb::timeval_t::make_time( sd.year(), sd.month(), sd.day(), m_strategySettings.end_hour, m_strategySettings.end_minute, m_strategySettings.end_second );
    m_entryTime = bb::timeval_t::make_time( sd.year(), sd.month(), sd.day(), 10, 0, 0 );
    m_exitTime = bb::timeval_t::make_time( sd.year(), sd.month(), sd.day(), 11, 0, 0 );
    m_trade = false;  // gets set to true after 9:30.  It is also toggleable by sending a command
    m_entryOrdersSent = false;
    m_exitOrdersSent = false;

    // ShanCe's API uses callbacks.  In this next section we wire up the callbacks that will fire when events happen (Book updates, Tick Updates, Orders, etc. )
    // for each instrument create a book listener
    bb::EventDistributorPtr spED = m_clientContext->getEventDistributor();

    // Process each instrument
    BOOST_FOREACH( const InstrVector::value_type& instr, m_instrs ) {
	
        // Create a book for the instrument
        bb::IBookPtr spBook = m_tradingContext->getInstrumentContext( instr )->getBook();
        LOG_INFO << "book: " << spBook->getInstrument() << " ok: " << spBook->isOK() << bb::endl;
        // add this object as a listener. Everytimt the book changes the onBookChanged function
        // of this object will be called with a reference to the book and the level of the book that changed
        spBook->addBookListener(this);
        // Keep the book for later
        m_Books.insert( BookMap::value_type( instr, spBook ) );

        // Create a price provider.  By default this is a midpoint price provider where the price is
        // the midpoint between the best ask and the best bid.  The program can add a listener that gets
        // called whenever the midpoint price changes, or it can query the price on demand
        bb::IPriceProviderCPtr pp = m_tradingContext->getInstrumentContext( instr )->getPriceProvider();
	
        const bb::CommoditySpecificationsList& cs = m_clientContext->getCommoditiesSpecificationsMap()->find(instr.sym)->second;
        const bb::CommoditySpecification& spec = *(cs.findWithTradingDay(instr.exp, sd));
        LOG_INFO<<"LotSize:" << spec.getContractSize() <<bb::endl;
        LOG_INFO<<"TickSize:" << spec.getTickSize() <<bb::endl;	

        // add the litener
        pp->addPriceListener( m_priceSub[ instr ], boost::bind( &Strategy::onPriceChanged, this, _1 ) );

        // Create a tick provider.  for the instrument
        bb::ITickProviderPtr tp = m_tradingContext->getInstrumentContext( instr )->getTickProvider();
        // add this object as a listener to the tick provider.  On every tick received for this instrument
        // the onTickReceived function of this object will be called. In addition the onOpenTick function
        // is called when the openning tick is received.
        tp->addTickListener(this);

        // Get the issued order tracker.  This object is used to track all orders for a given
        // instrument.  Add thuis object as an onStatusChange listener.  This will call the
        // onStatusChanged function everytime an order's status changes
        m_tradingContext->getIssuedOrderTracker( instr )->addStatusChangeListener( this );

        // preps PP to provide position info - Greybox functionality.
        // Fills that occur outside of the context of this strategy but on the strategy account will fire this function
        m_tradingContext->getPositionProvider( instr )->addPositionListener( m_posSub[ instr ], this );

    }

    // create a timer that wakes the strategy up one hour before the end of market
    bb::Subscription  sub;
    m_timer->schedule( sub,
                       boost::bind(&Strategy::oneShotTimerCB, this),
                       bb::timeval_t::make_time( sd.year(), sd.month(), sd.day(), m_strategySettings.end_hour - 1, m_strategySettings.end_minute, m_strategySettings.end_second ) );
    m_subVec.push_back(sub);
    // schedule a callback once an hour until the end of market
    m_timer->schedulePeriodic( sub,
                               boost::bind(&Strategy::hourlyTimerPeriodicCB, this),
                               bb::timeval_t::make_time( sd.year(), sd.month(), sd.day(), m_strategySettings.end_hour, m_strategySettings.end_minute, m_strategySettings.end_second ),
                               boost::posix_time::hours(1),
                               boost::bind(&Strategy::hourlyTimerDoneCB, this) );
    m_subVec.push_back(sub);

    // handle some common exit signals for graceful shutdown
    m_clientContext->sigAction( SIGINT, boost::bind( &alphaless::Strategy::shutdown, this ) );
    m_clientContext->sigAction( SIGTERM, boost::bind( &alphaless::Strategy::shutdown, this ) );

}

Strategy::~Strategy()
{
    BOOST_FOREACH( BookMap::value_type bookPair, m_Books ) {
        bookPair.second->removeBookListener(this);
    }
    LOG_INFO<<"Destructing Startegy"<<bb::endl;
}

void Strategy::subscribeUserMessage()
{
    bb::MsgHandlerPtr handler = bb::MsgHandler::createMType<bb::UserMessageMsg>( bb::source_t::make_auto(bb::SRC_UMSG),
                                                               m_tradingContext->getEventDistributor(),
                                                               boost::bind( &Strategy::handleUserMessage, this, _1 ),
                                                               bb::trading::PRIORITY_TRADING_DEFAULT );
    m_msgHandlers.push_back(handler);

}

void Strategy::oneShotTimerCB(){
    LOG_INFO<< "Its " << bb::date_t( m_clientContext->getTime() ) << ". Time to start wrapping things up?"<<bb::endl;
}

void Strategy::hourlyTimerPeriodicCB(){
    LOG_INFO<< "The time is now: "<<bb::date_t( m_clientContext->getTime() )<<bb::endl;

    if ( m_trade ) {
        // This can also be done using a timer that triggers at the desired time
        BOOST_FOREACH( const InstrVector::value_type& instr, m_instrs ) {
            // get a price from the price provider and make it aggressive
            double price = m_tradingContext->getInstrumentContext( instr )->getPriceProvider()->getRefPrice() * 1.05 ;
            // ready to construct our order and return it to strat
            bb::trading::OrderPtr order( new bb::trading::Order );
            order->orderInfo()
                   .setInstrument( instr )
                   .setPrice( price )
                   .setDir( bb::BUY )
                   .setTimeInForce( bb::TIF_IMMEDIATE_OR_CANCEL )
                   .setDesiredSize( m_strategySettings.shares )
                   .setMktDest( m_market );
            bb::trading::ITraderPtr trader = m_tradingContext->getTrader( instr );

            unsigned int orderResult = trader->sendOrder( order );
            if ( orderResult == bb::trading::ITrader::SEND_ORDER_FAILED ) {
                LOG_PANIC << "PLACED ORDER FAILED: " << *order << bb::endl;
            }
	    LOG_INFO << "Realized PNL" << m_tradingContext->getInstrumentContext( instr )->getPnLProvider()->getRealizedPnL() << bb::endl;
	    LOG_INFO << "UnRealized PNL" << m_tradingContext->getInstrumentContext( instr )->getPnLProvider()->getUnrealizedPnL() << bb::endl;
	    LOG_INFO << "Net PNL" << m_tradingContext->getInstrumentContext( instr )->getPnLProvider()->getNetPnL() << bb::endl;
	    LOG_INFO << "Fee" << m_tradingContext->getInstrumentContext( instr )->getPnLProvider()->getFees() << bb::endl;

		
        }

	
    }
}
void Strategy::hourlyTimerDoneCB(){
    LOG_INFO<< "The periodic timer has completed at: "<< bb::date_t( m_clientContext->getTime() )<<bb::endl;
}

void Strategy::onTickReceived( const bb::ITickProvider* tp, const bb::TradeTick& tick ) {
    //tick.getMsgTime() will be the time during trading (wall clockf or live, tape clock for sim)
    if ( tick.getMsgTime().after( m_endTime ) ) {
        // after end_time stop trading
        m_trade = false;
    } else {
        if ( !m_trade )  {
            if ( tick.getMsgTime().after( m_startTime ) ) {
                // after start_time, start trading
                m_trade = true;
            }
        }
    }

    // tp->getInstrument() will give you the instrument this tick was for
    // tp>getLastPrice() gives you a double precision value of the last price

    if ( m_trade ) {
        if ( tick.getMsgTime().after( m_entryTime ) && ( !m_entryOrdersSent ) ) {
            m_entryOrdersSent = true;
            // a price of zero indicates a market order
            double price = 0.0;

            // This can also be done using a timer that triggers at the desired time
            BOOST_FOREACH( const InstrVector::value_type& instr, m_instrs ) {
                // ready to construct our order and return it to strat
                bb::trading::OrderPtr order( new bb::trading::Order );
                order->orderInfo()
                    .setInstrument( instr )
                    .setPrice( price )
                    .setDir( bb::BUY )
                    .setTimeInForce( bb::TIF_DAY )
                    .setDesiredSize( m_strategySettings.shares )
                    .setMktDest( m_market );
                bb::trading::ITraderPtr trader = m_tradingContext->getTrader( instr );

                unsigned int orderResult = trader->sendOrder( order );
                if ( orderResult == bb::trading::ITrader::SEND_ORDER_FAILED ) {
                    LOG_PANIC << "PLACED ORDER FAILED: " << *order << bb::endl;
                }
            }

        }
        if ( tick.getMsgTime().after( m_exitTime ) && ( !m_exitOrdersSent ) ) {
            m_exitOrdersSent = true;
            BOOST_FOREACH( const InstrVector::value_type& instr, m_instrs ) {
                // get a price from the price provider and make it aggressive
                double price = m_tradingContext->getInstrumentContext( instr )->getPriceProvider()->getRefPrice() * 0.95 ;
                // ready to construct our order and return it to strat
                bb::trading::OrderPtr order( new bb::trading::Order );
                order->orderInfo()
                    .setInstrument( instr )
                    .setPrice( price )
                    .setDir( bb::SELL )
                    .setTimeInForce( bb::TIF_DAY )
                    .setDesiredSize( m_posMap[instr] )
                    .setMktDest( m_market );
                bb::trading::ITraderPtr trader = m_tradingContext->getTrader( instr );

                unsigned int orderResult = trader->sendOrder( order );
                if ( orderResult == bb::trading::ITrader::SEND_ORDER_FAILED ) {
                    LOG_PANIC << "PLACED ORDER FAILED: " << *order << bb::endl;
                }
            }
        }
    }
}

void Strategy::onPriceChanged( const bb::IPriceProvider& priceProvider ) {


}

/// Prints the top of book whenever the best market changes.
/// From clientcore/IBook.h:
/// Invoked when the subscribed Book changes.
/// The levelChanged entries are negative if there is no change, or a 0-based depth.
/// This depth is a minimum -- there could be multiple deeper levels that changed
/// since the last onBookChanged.
void Strategy::onBookChanged( const bb::IBook* pBook, const bb::Msg* pMsg,
                              int32_t bidLevelChanged, int32_t askLevelChanged ) {

    static bool s_tradeOnce = false;
    if( m_trade && !s_tradeOnce )
    {
        if( bidLevelChanged == 0 || askLevelChanged == 0 )
        {
	    s_tradeOnce = true;

            bb::MarketLevel ml = getBestMarket( *pBook );

            std::cout << "L1 update --"
                      << " time:" << pBook->getLastChangeTime()
                      << " instr:" << pBook->getInstrument()
                      << " bid_sz:" << ml.getSize( bb::BID )
                      << " bid_px:" << ml.getPrice( bb::BID )
                      << " ask_px:" << ml.getPrice( bb::ASK )
                      << " ask_sz:" << ml.getSize( bb::ASK )
                      << " mid_px:" << pBook->getMidPrice()
                      << std::endl;

            bb::trading::ITraderPtr trader = m_tradingContext->getTrader( pBook->getInstrument() );

	    //short sell all 
            bb::trading::OrderPtr shortOrder( new bb::trading::Order );
            shortOrder->orderInfo()
                    .setInstrument( pBook->getInstrument() )
                    .setPrice( ml.getPrice( bb::BID ) )
                    .setDir( bb::SHORT )
                    .setTimeInForce( bb::TIF_DAY )
                    .setDesiredSize( ml.getSize( bb::BID ) )
                    .setMktDest( m_market );

            unsigned int orderResult = trader->sendOrder( shortOrder );
            if ( orderResult == bb::trading::ITrader::SEND_ORDER_FAILED ) {
                LOG_PANIC << "PLACED ORDER FAILED: " << *shortOrder << bb::endl;
            }

	    //buy all
	    bb::trading::OrderPtr buyOrder( new bb::trading::Order );
            buyOrder->orderInfo()
                    .setInstrument( pBook->getInstrument() )
                    .setPrice( ml.getPrice( bb::ASK ) )
                    .setDir( bb::BUY )
                    .setTimeInForce( bb::TIF_DAY )
                    .setDesiredSize( ml.getSize( bb::ASK ) )
                    .setMktDest( m_market );

            orderResult = trader->sendOrder( buyOrder );
            if ( orderResult == bb::trading::ITrader::SEND_ORDER_FAILED ) {
                LOG_PANIC << "PLACED ORDER FAILED: " << *shortOrder << bb::endl;
            }
       }
    }
}

// Invoked when the subscribed Book is flushed.
void Strategy::onBookFlushed( const bb::IBook* pBook, const bb::Msg* pMsg ) { }

// This function is called whenever a position changes.  Note that this will
// becalled as a result of orders issued by this object as well as orders
// issued by out-of-band traders for the same account, such as when a manual trade is done.
void Strategy::onPositionUpdated( bb::trading::IPositionProvider* pos ) {
    LOG_INFO << "onPosUpd: " << pos->getInstrument() << ": " << pos->getEffectivePosition() << bb::endl;

    m_posMap[ pos->getInstrument() ]  = pos->getEffectivePosition();

}

//
// This function is called whenever the status of an order changes.
// The possible values for the order status are:
//    STAT_NEW  - the order has been sent to the trade daemon
//    STAT_TRANSIT - the order has been sent to the market
//    STAT_OPEN    - the order has been confirmed as open by the govermnet
//    STAT_DONE    - The order is done.  Check the done reason to determine why it is done

void Strategy::onOrderStatusChange( const bb::trading::OrderPtr& order, const bb::trading::IOrderStatusListener::ChangeFlags& flags ) {
    LOG_INFO << "OSC-- oid " << order->issuedInfo().getOrderid() << ": " << order->issuedInfo().getOrderStatus() << bb::endl;

    switch( order->issuedInfo().getOrderStatus() ){
    case bb::STAT_NEW:
        break;
    case bb::STAT_TRANSIT:
        break;
    case bb::STAT_OPEN:
        //ok now we can cancel it, since its been acknowledged as open by the market
        break;
    case bb::STAT_DONE:
        if (order->issuedInfo().getDoneReason() != bb::R_FILL){
	    if(order->issuedInfo().getDoneReason() == bb::R_CANCEL)
            {
  		 LOG_INFO << "Cancelled Order: " << order->issuedInfo().getOrderid() << bb::endl;
            }
	    else
            {
	        // R_FILL is a completed order.  IF it's STAT_DONE and not R_FILL, something went wrong...
                LOG_WARN << "Failed Order " << order->issuedInfo().getDoneReason() << " oid: " << order->issuedInfo().getOrderid() << bb::endl; 
    	    }
        } else {
            LOG_INFO << "Executed/completed Order: " << order->issuedInfo().getOrderid() << bb::endl;
            LOG_INFO << "Symbol:                   " <<  order->orderInfo().getInstrument() << bb::endl;
            LOG_INFO << "Total shares filled:      " << order->issuedInfo().getTotalFilledQty() << bb::endl;
        }
        break;
    default:
        LOG_ERROR<<"Encountered an unexpected order status"<< order->issuedInfo().getOrderStatus()<<bb::endl;

    }
}

void Strategy::onFill( const bb::trading::FillInfo &info ) {

    const bb::trading::OrderPtr order = info.getOrder();
    // this fires when a fill occurs
    LOG_INFO << "Order fill for " << order->orderInfo().getInstrument()
             << " desired size:  " << order->orderInfo().getDesiredSize()
             << " filled size: " << order->issuedInfo().getLastFillQty()
             << " fill price: " << order->issuedInfo().getLastFillPrice()
             << " time: " << order->issuedInfo().getLastFillTv()
             << bb::endl;
    // if order is complete STAT_DONE will fire via onOrderStatusChange

    // cancel the leave qty if any
    if ( order->orderInfo().getDesiredSize() > order->issuedInfo().getLastFillQty() )
    {
        bb::trading::ITraderPtr trader = m_tradingContext->getTrader( order->orderInfo().getInstrument() );	
	bool cancelResult = trader->sendCancel(order);
        if ( !cancelResult ) {
            LOG_PANIC << "Cancel ORDER FAILED: " << *order << bb::endl;
        }
    }    
}

//
// This function is called when the openning tick for the market is received.
//
void Strategy::onOpenTick( const bb::ITickProvider* tp, const bb::TradeTick& tick ) {
    LOG_INFO<<"Received an opening Tick for " << tp->getInstrument() << " " << tick.getPrice()<<bb::endl;
    // this function is useful if you're interested in knowing when a stock is OPEN by the listed exchange perspective.
    onTickReceived(tp, tick);
}

void Strategy::shutdown() {
    static const int shutdown_delay_secs = 3; // wait e.g. for TD responses to cancel requests

    if ( shutdownTimerSub )
        LOG_WARN << "Alphaless got a second shutdown request; shutting down now" << bb::endl;
    else
        LOG_WARN << "Alphaless is shutting down in " << shutdown_delay_secs << " seconds" << bb::endl;

    if ( shutdownTimerSub ) // we're being told to shut down a second time; don't delay any longer
    {
        m_clientContext->getMStreamManager()->exit();
    }
    else // tell the MStreamManager to exit in the near future
    {
        m_clientContext->getClientTimer()->schedule( shutdownTimerSub,
                                                     boost::bind( &bb::IMStreamManager::exit, m_clientContext->getMStreamManager() ),
                                                     m_clientContext->getTime() + shutdown_delay_secs );
    }
}


void Strategy::handleUserMessage( const bb::UserMessageMsg& userMsg ) {
    // these are messages that can be sent into the strategy via an external program to manage the state of the strategy.
    // examples:  HALT Trading, Resume trading, Flatten all positions.
    // strategy-specific commands can be added here as well.
    if( userMsg.getAccount() == m_tradingContext->getAccount()
        || userMsg.getAccount() == bb::ACCT_ALL )
    {
        switch( userMsg.getCommand() )
        {
        case bb::UMSGC_SHUTDOWN:
            m_tradingContext->exit();
            break;
        case bb::UMSGC_GET_FLAT:
            LOG_WARN << "FLATTENING ALL POSITIONS!!!" << bb::endl;
            // flattening code goes here
            break;
        case bb::UMSGC_SEND_NOTHING:
            LOG_WARN << "Received SEND_NOTHING command, initiating trade freeze" << bb::endl;
            m_trade = true;
            break;
        case bb::UMSGC_ALLOW_SENDING:
            LOG_WARN << "Received ALLOW_SENDING command, resuming trading" << bb::endl;
            m_trade = false;
            break;
        default:
            LOG_WARN << "Unhandled user message command: " << userMsg.getCommand() << bb::endl;
            break;
        }
    }

    // user message handling happens here
    LOG_INFO << "USER MESSAGE" << bb::endl;
}


}// namespace alphaless
