#include <csignal>
#include <exception>
#include <fstream>
#include <string>

#include <boost/assign/list_of.hpp>
#include <boost/foreach.hpp>
#include <boost/bind.hpp>

#include <bb/core/date.h>
#include <bb/core/env.h>
#include <bb/core/Error.h>
#include <bb/core/Log.h>
#include <bb/core/LuaState.h>
#include <bb/core/messages.h>
#include <bb/core/program_options.h>
#include <bb/core/instrument.h>
#include <bb/core/timeval.h>
#include <bb/core/smart_ptr.h>
#include <bb/core/mktdestmappings.h>

#include <bb/clientcore/clientcoreutils.h>
#include <bb/clientcore/BookBuilder.h>
#include <bb/clientcore/ClientContext.h>
#include <bb/clientcore/IClientTimer.h>
#include <bb/clientcore/SourceBooks.h>
#include <bb/clientcore/MsgHandler.h>

#include <bb/trading/priceutils.h>
#include <bb/trading/Trader.h>
#include <bb/trading/TradingContext.h>
#include <bb/trading/Trading_Scripting.h>
#include <bb/trading/PositionTrackerFactory.h>
#include <bb/trading/RefData.h>

#include <bb/trading/FillFeesDotLuaFeeProvider.h>

#include <bb/simulator/SimClientContext.h>
#include <bb/simulator/SimTradingContext.h>
#include <bb/simulator/ISimMktDest.h>
#include <bb/simulator/SimMktDelays.h>
#include <bb/simulator/OrderManager.h>
#include <bb/simulator/SimTrader.h>
#include <bb/simulator/SimTradeDemonClient.h>
#include <bb/simulator/SimTrader.h>
#include <bb/simulator/markets/ShfeSimMktDest.h>
#include <bb/simulator/SimBbL1RefDataFactory.h>
#include <bb/simulator/Simulator_Scripting.h>

#include "Strategy.h"

using namespace bb;
using namespace bb::trading;
using namespace alphaless;

namespace {
    const char* const g_usage = "usage: alphaless [options]";
    const char* const g_programName = "alphaless";
}

void initSimulator(trading::HistTradingContextPtr const& htc, timeval_t &starttv, timeval_t &endtv, const InstrVector& instrs, StrategySettings& settings )
{
    mktdest_t market = str2mktdest(settings.market.c_str());

    bb::simulator::DefaultDelaysFactoryCPtr delayFactory(new bb::simulator::DefaultDelaysFactory(HistMStreamManager::getRuntimeFeedDest()));
    bb::simulator::OrderManagerPtr om = bb::simulator::OrderManagerPtr (
            new bb::simulator::OrderManager(
                market,
                htc->getHistMStreamManager(),
                htc->getTimeProvider(),
                htc->getEventDistributor(),
                0,			//verbose
                delayFactory->getMarketTransitDelays( market )
                )
            );
    bb::simulator::SimTraderPtr simTrader = boost::dynamic_pointer_cast<bb::simulator::SimTrader>( htc->getBaseTrader() );
    bb::simulator::SimTradeDemonClientPtr stdc = boost::dynamic_pointer_cast<bb::simulator::SimTradeDemonClient>( simTrader->getTradeDemonClient() );
    stdc->initSimMarketDest( market, bb::dynamic_pointer_cast<bb::simulator::ISimMktDest>( om ) );
    source_t source;
    source.setType( str2EFeedType( settings.feed_type.c_str()) );
    source.setOrig( str2EFeedOrig( settings.feed_orig.c_str()) );
    source.setDest( str2EFeedDest( settings.feed_dest.c_str()) );
    bb::simulator::AsiaOrderHandlerPtr orderHandler = bb::simulator::AsiaOrderHandlerPtr (
            new bb::simulator::AsiaOrderHandler(
                htc,
                market,
                source,
                1,
                om,
                delayFactory->getMarketInternalDelays( market )
                )
            );
    om->registerOrderHandler( orderHandler );
    int numDestsRegistered = 0;
    BOOST_FOREACH( bb::instrument_t instr, instrs )
    {
        std::cout << "instr: " << instr << std::endl;

        om->addInstrument( instr, bb::IBookSpecPtr(), settings.sim_order_book );
        ++numDestsRegistered;

    }
    LOG_INFO << " Registered order handler for " << numDestsRegistered << " tickers." << bb::endl;
}

int main(int argc, char** argv)
{
    //Options
    std::string startDateStr;
    std::string endDateStr;
    acct_t acct;
    std::string strategyConfig;
    bool verbose = false;
    bool live = false;
    bool route = false;
    std::string id;
    bb::options_description optionsDesc( "options" );


    std::string ident( g_programName );
    setLogger( ident.c_str() );

    default_init();
    bb::registerScripting();
    bb::simulator::registerScripting();

    {
        namespace po = boost::program_options;
        optionsDesc.add_options()
            ( "help", "show the help text")
            ( "start-date,s",      po::value( &startDateStr ),"" )
            ( "end-date,e",        po::value( &endDateStr ), "" )
            ( "account,a",         po::value( &acct ), "" )
            ( "verbose,v",         po::bool_switch( &verbose ), "" )
            ( "live,l",            po::bool_switch( &live ), "Run in live mode" )
            ( "route,r",           po::bool_switch( &route ), "Allow routing of orders" )
            ( "id,i",              po::value( &id ), "unique name for strategy" )
            ( "strategy-config,c", po::value( &strategyConfig ), "lua config file for strategy" )
            ;
    }

    try
    {

        // parse the program options into the variables
        boost::program_options::variables_map programOptions;

        parseOptionsSimple(programOptions, argc, argv,
                boost::program_options::options_description()
                .add(optionsDesc)
                );

        // sanity checks for some of the options
        if( !acct.isValid() )
            throw UsageError("account required");
        if( strategyConfig.empty() )
            throw UsageError("strategy config must be specified");
        if( id.empty() )
            throw UsageError("id must be specified");
        if( !live && startDateStr.empty() )
            throw UsageError("start-date is required in histmode");

        // convert the start/end range to timeval_t start and end
        timeval_t starttv,endtv;
        
        if( live && startDateStr.empty() )
        {
            starttv = timeval_t::now;
        }
        else
        {
            starttv = timeval_t::make_time( startDateStr );
        }


        if(endDateStr.empty())
        {
            endtv = starttv + boost::posix_time::hours( 24 ) - boost::posix_time::seconds( 1 );
        }
        else
        {
            endtv = timeval_t::make_time( endDateStr );
            if( endtv < starttv )
                throw UsageError( "end-date is before start-date!" );
        }

        // Load Strategy Settings.

        // register the core libraries and any strategy entities
        LuaStatePtr state(new LuaState);

        // allow our strategy to connect any lua bindings to the lua state
        state->loadLibrary( "core" );
        state->loadLibrary( "simulator" );
        bb::trading::register_libtrading( *( state->getState() ) );

        LOG_INFO << "Loading lua: " << strategyConfig << bb::endl;
        // load the strategy configuration
        state->load( strategyConfig );
        LOG_INFO << "Done Loading lua: " << strategyConfig << bb::endl;

        StrategySettings settings = StrategySettings::fromLua( (*state)["strategy_config"] );

        // setup default origin and destination
        bb::source_t::setAutoOrig(str2EFeedOrig(settings.feed_orig.c_str()));
        bb::source_t::setAutoDest(str2EFeedDest(settings.feed_dest.c_str()));

        //Construct TradingContext and ClientContext
        std::string idString = ident + "_" + id + "_" + acct.toString();

        // client context manages...everything
        ClientContextFactory::Config ccConfig( idString,
                starttv,
                endtv,
                live ? ClientContextFactory::kLive : ClientContextFactory::kHistoricalSplit,
                verbose ? ClientContextFactory::kVerbose : ClientContextFactory::kQuiet,
                "production"
                );

        TradingContextFactory::Config tcConfig;
        tcConfig.setClientContextFactoryConfig( ccConfig )
            .setAccount( acct )
            .createBookBuilderFromClientContext()
            .setOrderRoutingMode( route ? TradingContextFactory::kRoute : TradingContextFactory::kDoNotRoute );

        TradingContextPtr tradingContext = TradingContextFactory::create( tcConfig );
        ClientContextPtr clientContext = tradingContext->getClientContext();

        InstrVector instruments;
        BOOST_FOREACH(const std::string& instr, settings.instruments) {
            instruments.push_back( bb::instrument_t::fromString(instr) );
        }

        boost::optional<source_t> positionSource;
        sourceset_t data_source;
        source_t source;

        source.setType( str2EFeedType(settings.feed_type.c_str()) );
        source.setOrig( str2EFeedOrig( settings.feed_orig.c_str()) );
        source.setDest( str2EFeedDest( settings.feed_dest.c_str()) );

        data_source.insert(source);
        tradingContext->setDefaultReferenceData( RefDataPtr( new RefData(data_source) ) );
        if( live ) {
            // needs to be set in live mode to get position updates
            positionSource = source_t::make_auto( SRC_INFO );
        } else { // simulation
            HistMStreamManager::setRuntimeFeedDest(str2EFeedDest(settings.feed_dest.c_str()));

            trading::HistTradingContextPtr         htc = boost::dynamic_pointer_cast<trading::HistTradingContext>(tradingContext);
            bb::simulator::SimTradeDemonClientPtr  tdc = boost::make_shared<bb::simulator::SimTradeDemonClient>(htc) ;


            bb::simulator::initSimTrader( htc, tdc );

            initSimulator( htc, starttv, endtv, instruments, settings );

            BOOST_FOREACH( const bb::instrument_t instr, instruments){
                // set the starting position for this instrument in the simulator
                tdc->initSyntheticPosition(instr, 0);
            }
        }
        IPositionProviderFactoryPtr positionProviderFactory ( new PositionTrackerFactory( positionSource ) );
        tradingContext->setPositionProviderFactory( positionProviderFactory );

        const bb::trading::IFeeProviderFactoryPtr feeProviderFactory = boost::make_shared<bb::trading::FillFeesDotLuaFeeProviderFactory>();
        tradingContext->setFeeProviderFactory( feeProviderFactory );

        tradingContext->createTrader();

        // MUST go after "createTrader()"  or "getIssuedOrderTracker" on tradingContext won't work

        LOG_INFO << "Instantiating Strategy." << bb::endl;
        StrategyPtr strategy( new Strategy( instruments, tradingContext, settings ) );
        LOG_INFO << "Done Instantiating Strategy." << bb::endl;

        //if it's true, then cancel all the orders if the connection between clients and TD is down
        tradingContext->getBaseTrader()->setCancelOnDisconnect( true );
        if( !tradingContext->getBaseTrader()->connectToTradeServer( settings.trade_server ) ) {
            BB_THROW_ERROR_SS("Failed to connect to trade server " << settings.trade_server);
        }


        // connect to listen to user messages
        // this allows message passing to the strategy
        if ( clientContext->isLive() )
        {
            strategy->subscribeUserMessage();
        }

        // End Strategy Launcher Items

        // start main loop
        clientContext->run();

        LOG_INFO << "end of market day - process end of day stuff" << bb::endl;
    }
    catch (UsageError &e)
    {
        if(e.what()[0] != '\0')
        {
            std::cerr << e.what() << "\n";
            std::cerr << optionsDesc;
            std::cerr << bb::endl;
            return EXIT_FAILURE;
        }

        LOG_INFO << "\n\n" << g_usage << "\n";
        LOG_INFO << optionsDesc << bb::endl;
    }
    catch (std::exception& e)
    {
        std::cout << "caught exception" << std::endl;
        LOG_PANIC << "error: " << e.what() << bb::endl;
        return EXIT_FAILURE;
    }
}
