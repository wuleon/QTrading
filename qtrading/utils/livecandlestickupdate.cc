// Contents Copyright Shanghai ShanCe Technologies Company Ltd. All Rights Reserved.

#include <iostream>
#include <iomanip>
#include <fstream>
#include <boost/io/ios_state.hpp>

#include <boost/program_options.hpp>

#include <bb/core/env.h>
#include <bb/core/LuaState.h>
#include <bb/clientcore/ClientCoreSetup.h>
#include <bb/clientcore/TickFactory.h>
#include <bb/clientcore/ICandlestickSeries.h>
#include <bb/clientcore/ICandlestickListener.h>
#include <bb/clientcore/HistCandlestickFileStore.h>
#include <bb/clientcore/ShfeTickProvider.h>
#include <bb/clientcore/LiveUpdateCandlestickStore.h>

using namespace bb;
using namespace std;

class LiveCandlestickUpdateSetup
    : public ClientCoreSetup
    , public ICandlestickListener
{
public:
    LiveCandlestickUpdateSetup( int argc, char** argv )
        : ClientCoreSetup( argc, argv )
        , m_output( &cout )
    {
        // this could probably take the instr, but it's not important
        setIdentity( getProgramName() );
        m_bLoadProductFile = false;
    }

    class Options : public SetupOptions
    {
    public:
        Options( LiveCandlestickUpdateSetup* ts )
            : SetupOptions( ts->getProgramName() + " options"
                , boost::bind( &LiveCandlestickUpdateSetup::checkOptions, ts, _1, _2 ) )
        {
            namespace po = boost::program_options;
            add_options()
                ("mstreamfile,m", po::value<std::string>(), "Message stream file.")
                ("instrument,i", po::value<std::string>(), "instrument")
                ("period,p", po::value<double>()->default_value(60.0), "candlestick period")
                ("source,S", po::value<std::string>()->default_value("SRC_SHFE.OSFIT.DSFIT")
                    , "data source")
                ("separator", po::value<std::string>()->default_value(","), "field separator" )
                ("dateformat,F", po::value<std::string>(), "date format")
                ("append,a", po::bool_switch(), "append to output file")
                ("zeros,z", po::bool_switch(&(ts->m_bKeepZeros)), "keep zero volume bars")
                ;
        }
    };
    friend class Options;

    virtual void addOptions( boost::program_options::options_description& allOptions )
    {
        registerOptions( allOptions, getClientCoreSetupOptions( false ) );
        registerOptions( allOptions, SetupOptionsPtr( new Options( this ) ) );
    }

    void checkOptions( const boost::program_options::variables_map& vm, ProblemList* problems )
    {
        try {
            std::string instr_str;
            std::string source_str;
            assignOption( &instr_str, vm, "instrument", true );
            m_instr = instrument_t::fromString( instr_str );

            assignOption( &m_dateFormat, vm, "dateformat", false );
            assignOption( &m_period, vm, "period", true );
            assignOption( &m_sep, vm, "separator", true );
            assignOption( &source_str, vm, "source", true );
            m_source = source_t( source_str.c_str() );
        }
        catch( std::string& str )
        {
            problems->add( ProblemList::ERROR, str.c_str() );
        }
        // optional
        assignOption( &m_messageStreamFilename, vm, "mstreamfile", false );
    }

    bool setupSymbols()
    {
        // ClientCoreSetup::setupSymbols();

        if( !isRunLive() && m_messageStreamFilename )
        {
            DefaultCoreContext::getEnvironment()->config().histMStreamConfig.ignoreMissingFiles = true;
            HistClientContextPtr hcc = boost::dynamic_pointer_cast<HistClientContext>( getClientContext() );
            hcc->getHistMStreamManager()->addFile( m_messageStreamFilename.get().c_str() );
        }

        SourceTickFactoryPtr stf( new SourceTickFactory( getClientContext() ) );
        m_spTickProvider = stf->getTickProvider( m_instr
            , m_source, true );

        m_spStore.reset( new LiveUpdateCandlestickStore( m_period
                , m_source
                , "."
                , getClientContext()->getClockMonitor()
                , stf
                , getStartDate().getMidnight()
                , m_bKeepZeros ) );
        m_spSeries = m_spStore->getInstrument( m_instr );

        m_spStore->subscribeSeriesUpdate( m_instr, m_sub, this );

        bb::timeval_t::set_print_precision( 4 );
        return true;
    }

    void onUpdate( const ICandlestickSeries*, const Candlestick& entry )
    {
        std::cout << m_spSeries->size() << " " << m_spSeries->rbegin().isValid() << std::endl;
        if( !m_dateFormat.size() )
            (*m_output) << entry.getTime();
        else
        {
            char buf[1024];
            entry.getTime().strftime( buf, 1024, m_dateFormat );
            (*m_output) << buf;
        }

        (*m_output) << m_sep << entry.getOpen()
                    << m_sep << entry.getHigh()
                    << m_sep << entry.getLow()
                    << m_sep << entry.getClose()
                    << m_sep << entry.getVolume();

        (*m_output) << endl;
    }

protected:
    boost::optional<std::string> m_messageStreamFilename;
    double m_period;
    instrument_t m_instr;
    LiveUpdateCandlestickStorePtr m_spStore;
    ICandlestickSeriesPtr m_spSeries;
    Subscription m_sub;
    ITickProviderPtr m_spTickProvider;
    source_t m_source;
    std::string m_sep;
    ostream* m_output;
    std::string m_dateFormat;
    bool m_bKeepZeros;
};

int main( int argc, char* argv[] )
{
    bb::setLogger( "candlesticks" );
    bb::default_init();
    bb::DefaultCoreContext::getEnvironment()->luaState().setErrorHandler( bb::LuaState::TracebackErrorHandler );

    LiveCandlestickUpdateSetup setup( argc, argv );
    try
    {
        setup.setup();
        setup.setupSymbols();
        setup.run();
    }
    catch( const UsageError& ex )
    {
        std::cerr << "usage: " << setup.getProgramName() << " [options]" "\n"
            << ex.what();
        return EXIT_FAILURE;
    }
    catch( std::exception& ex )
    {
        std::cerr << "ERROR: problem in setup: " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }
}
