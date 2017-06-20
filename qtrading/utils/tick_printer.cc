// Contents Copyright Shanghai ShanCe Technologies Company Ltd. All Rights Reserved.

/*
  print_ticks.cc

  This example shows how to use TickProviders and TickListeners.  It will
  print every tick of the instrument designated on the command line.

  It does this by creating a TickProvider then implementing an ITickListener
  which prints the tick on every update.   An ITickListener gets notified whenever
  a new tick or volume update arrives.
*/

#include <iostream>

#include <boost/foreach.hpp>
#include <boost/algorithm/string/split.hpp>
#include <boost/algorithm/string/classification.hpp>
#include <boost/algorithm/string/predicate.hpp>

#include <bb/core/Log.h>
#include <bb/core/env.h>
#include <bb/core/Error.h>
#include <bb/core/program_options.h>
#include <bb/clientcore/ClientContext.h>
#include <bb/clientcore/TickProvider.h>
#include <bb/clientcore/TickFactory.h>
#include <bb/clientcore/MultipathTickFactory.h>

using namespace bb;
using std::string;


/// This is an implementation of TickPrinter which prints a tick whenever it
/// arrives.  It also accumulates total volume and prints that on exit.
class TickPrinter
    : public ITickListener
{
public:
    TickPrinter( ITickProviderCPtr spTickProv )
        : m_spTickProv( spTickProv )
        , m_total_vol( 0 )
    {
        // subscribe to the TickProvider
        if (!m_spTickProv)
            BB_THROW_ERROR_SS( "TickPrinter constructor: bad TickProvider" );
        m_spTickProv->addTickListener(this);
    }

    virtual ~TickPrinter()
    {
        LOG_INFO << "total_volume of " << m_spTickProv->getInstrument()
                 << " = " << m_total_vol << bb::endl;

        // unsubscribe from the TickProvider
        m_spTickProv->removeTickListener( this );
    }

    virtual void onTickReceived( const ITickProvider* tp, const TradeTick& tick )
    {
        std::cout << "tick update --"
                  << " ex_time:" << tick.getExchangeTime()
                  << " msg_time:" << tick.getMsgTime()
                  << " instr:" << tp->getInstrument()
                  << " sz:" << tick.getSize()
                  << " px:" << tick.getPrice()
                  << std::endl;

        // if a feed does not explciitly have a volume aspect, then
        // then its volume is estimated, so accumulate total volume here.
        if ( tp->isTotalVolumeEstimated() )
            m_total_vol += tick.getSize();
    }

    virtual void onTickVolumeUpdated( const ITickProvider* tp, uint64_t totalVolume )
    {
        std::cout << "vol update --"
                  << " time:" << tp->getLastExchangeTimestamp()
                  << " instr:" << tp->getInstrument()
                  << " vol:" << totalVolume
                  << std::endl;

        // some feeds, like CME, explicitly publish volumes separate from trades
        // they get accumulated here
        m_total_vol = totalVolume;
    }

private:
    ITickProviderCPtr    m_spTickProv;
    uint64_t             m_total_vol;
};



/// Program Main
///
/// Setup BB, read the arguments, create the ClientContext,
/// create the provider and listener, then run.
///
int main(int argc, char* argv[])
{
    // setup BB
    bb::setLogger("tick_printer");
    bb::default_init();

    // specify the program options
    // needs to be outside the try block for the catch handler
    namespace po = boost::program_options;
    bb::options_description po_desc;
    po_desc.add_options()
        ("help",         "print help message and exit")
        ("instr,i",      po::value<string>(), "instrument to run")
        ("live,l",       "run live, ignoring startdate/enddate" )
        ("startdate,d",  po::value<string>(), "process historically from date (YYYYMMDD or timeval)")
        ("enddate,e",    po::value<string>(), "stop processing historically at date (YYYYMMDD or timeval)")
        ("source,s",     po::value<string>()->default_value("SRC_CME.OSPIKE.DSPIKE"), "source to run in" )
        ("multipath-sources",     po::value<string>(), "Multipath tick sources delimited by comma" )
        ("verbose,v",    po::value<int32_t>()->default_value(0),  "verbosity: 0, 1, 2, 3")
    ;

    try
    {
        // read the program options
        po::variables_map po_vars;
        parseOptionsSimple( po_vars, argc, argv, po_desc );

        instrument_t instr;
        if (!po_vars.count("instr"))
            throw UsageError("ERROR: you must specify an instrument");
        instr = instrument_t::fromString( po_vars["instr"].as<string>() );

        source_t src( po_vars["source"].as<string>().c_str() );
        int verbose = po_vars["verbose"].as<int32_t>();

        bool run_live = po_vars.count("live");
        timeval_t starttv, endtv;

        if (run_live)
        {
            starttv = date_t::today().timeval();
            endtv = date_t::tomorrow().timeval();
        }
        else
        {
            if (!po_vars.count("startdate"))
                throw UsageError("ERROR: you must specify a startdate if you are not running live");
            starttv = make_date(po_vars["startdate"].as<string>().c_str()).timeval();
            if (po_vars.count("enddate"))
            {
                endtv = make_date(po_vars["enddate"].as<string>().c_str()).timeval();
                if ( endtv < starttv )
                    throw std::invalid_argument( "ERROR: enddate is before startdate!" );
            }
            else
                endtv = starttv + boost::posix_time::seconds(24*60*60-1);
        }

        ClientContextPtr spContext = ClientContextFactory::create( bb::DefaultCoreContext::getEnvironment(), run_live, starttv, endtv, getLogger()->getname(), verbose );

        // Create a SourceTickFactory, get a TickProvider from it
        // and create a TickPrinter
        SourceTickFactoryPtr spTickFactory = SourceTickFactory::create( spContext );
        ITickProviderPtr spTickProv;

        if( po_vars.count("multipath-sources") )
        {
            MultipathTickFactory m( spTickFactory );

            std::string srcs_str( po_vars["multipath-sources"].as<string>() );
            sourceset_t srcs;
            std::vector<std::string> srcs_strs;
            boost::split( srcs_strs, srcs_str, boost::is_any_of(",") );
            BOOST_FOREACH( const std::string& src_str, srcs_strs )
            {
                srcs.insert( srcs.begin(), source_t( src_str.c_str() ) );
            }

            spTickProv = m.getMultipathTickProvider( instr, srcs, true );
        }
        else
        {
            spTickProv = spTickFactory->getTickProvider( instr, src, true );
        }

        shared_ptr<TickPrinter> spTickPrinter( new TickPrinter(spTickProv) );

        // run...
        // this is pumping the context's EventDistributor with messages from the context's message stream
        spContext->run();

        // all the smart pointers will clean everything up
    }
    catch (UsageError &e)
    {
        if(e.what()[0] != '\0')
            std::cerr << e.what() << std::endl;
        std::cerr << std::endl;
        std::cerr << "options:" << std::endl;
        std::cerr << po_desc << std::endl;
        return EXIT_FAILURE;
    }
    catch ( const std::exception& e )
    {
        std::cerr << e.what() << std::endl;
        return EXIT_FAILURE;
    }
}
