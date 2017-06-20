#ifndef ALPHALESS_STRATEGY_H
#define ALPHALESS_STRATEGY_H

#include <set>
#include <map>
#include <vector>
#include <string>

#include <bb/core/smart_ptr.h>
#include <bb/core/Subscription.h>
#include <bb/core/instrument.h>
#include <bb/trading/IOrderStatusListener.h>
#include <bb/trading/IPositionProvider.h>
#include <bb/clientcore/IBook.h>
#include <bb/clientcore/TickProvider.h>
#include <bb/clientcore/MsgHandler.h>
#include <boost/foreach.hpp>

#include "StrategyConfig.h"


namespace bb {

BB_FWD_DECLARE_SHARED_PTR( IPriceProvider );
BB_FWD_DECLARE_SHARED_PTR( ClockMonitor );
BB_FWD_DECLARE_SHARED_PTR( IClientTimer );
BB_FWD_DECLARE_SHARED_PTR( ClientContext );
BB_FWD_DECLARE_SHARED_PTR( MsgHandler );

class BbL1TradeMsg;
class UserMessageMsg;
class NyseImbalanceMsg;

namespace trading {
BB_FWD_DECLARE_SHARED_PTR( TradingContext );
BB_FWD_DECLARE_INTRUSIVE_PTR( Order );

class ChangeFlags;

}

}

namespace alphaless {

BB_FWD_DECLARE_SHARED_PTR( Pair );
BB_FWD_DECLARE_SHARED_PTR( OPS );
BB_FWD_DECLARE_SHARED_PTR( ClosedPosition );

typedef std::vector<bb::instrument_t> InstrVector;

class Strategy
    : public bb::IBookListener, public bb::trading::IOrderStatusListener, public bb::ITickListener, public bb::trading::IPositionListener
{
public:
    Strategy( const InstrVector&,
              const bb::trading::TradingContextPtr&,
              const StrategySettings& );

    virtual ~Strategy();

    void onTickReceived( const bb::ITickProvider*, const bb::TradeTick& );

    void onPriceChanged( const bb::IPriceProvider& );

    /// Prints the top of book whenever the best market changes.
    /// From clientcore/IBook.h:
    /// Invoked when the subscribed Book changes.
    /// The levelChanged entries are negative if there is no change, or a 0-based depth.
    /// This depth is a minimum -- there could be multiple deeper levels that changed
    /// since the last onBookChanged.
    void onBookChanged( const bb::IBook*, const bb::Msg*,
                                int32_t bidLevelChange, int32_t askLevelChanged );

    /// Invoked when the subscribed Book is flushed.
    void onBookFlushed( const bb::IBook*, const bb::Msg* );

    void onPositionUpdated( bb::trading::IPositionProvider * );

    /// Called whenever an order's OrderStatus or CancelStatus changes.
    /// The details of what has changed can be found in the ChangeFlags.
    /// Listeners typically will only care about a small number of possible changes,
    /// so they can check the order to see whether it is something they care about.
    void onOrderStatusChange( const bb::trading::OrderPtr&, const bb::trading::IOrderStatusListener::ChangeFlags& );

    /// Called whenever there is a fill on the order.
    void onFill( const bb::trading::FillInfo &info );

    /// Called when the openTick is received
    void onOpenTick( const bb::ITickProvider* tp, const bb::TradeTick& tick );

    void shutdown();

    void handleUserMessage( const bb::UserMessageMsg& );
    void subscribeUserMessage();

private:

    void oneShotTimerCB();
    void hourlyTimerPeriodicCB();
    void hourlyTimerDoneCB();


    typedef std::map< bb::instrument_t, bb::IBookPtr, bb::instrument_t::less_no_mkt_no_currency > BookMap;
    InstrVector m_instrs;
    StrategySettings m_strategySettings;
    const bb::mktdest_t m_market;
    const bb::trading::TradingContextPtr m_tradingContext;
    const bb::ClientContextPtr m_clientContext;

    BookMap m_Books;

    // clock
    bb::ClockMonitorPtr m_clockMonitor;

    // timer stuff
    typedef std::map< bb::instrument_t, bb::Subscription, bb::instrument_t::less_no_mkt_no_currency> SubscriptionMap;
    SubscriptionMap m_posSub;
    SubscriptionMap m_priceSub;

    const bb::IClientTimerPtr m_timer;
    bb::timeval_t m_startTime, m_endTime, m_entryTime, m_exitTime;
    bool m_trade, m_entryOrdersSent, m_exitOrdersSent;

    // keep track of my positions
    typedef std::map< bb::instrument_t, uint32_t, bb::instrument_t::less_no_mkt_no_currency> PositionsMap;
    PositionsMap   m_posMap;

    // price handler for opening prints
    bb::Subscription m_open;

    // for Shutting down (via userMsghandler)
    bb::Subscription shutdownTimerSub;

    // subscriptionVector
    typedef std::vector<bb::Subscription>  SubscriptionVector;
    SubscriptionVector      m_subVec;
    std::vector<bb::MsgHandlerPtr> m_msgHandlers;

};
BB_DECLARE_SHARED_PTR( Strategy );

} // namespace alphaless

#endif // ALPHALESS_STRATEGY_H
