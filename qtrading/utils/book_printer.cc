// Contents Copyright Shanghai ShanCe Technologies Company Ltd. All Rights Reserved.

/*
   book_printer.cc

   This example shows how to use IBooks and IBookListeners.  It will
   print every book change of the instrument designated on the command line.

   It does this by creating an IBook then implementing an IBookListener
   which prints the MarketLevel on every update.
 */
#include <iostream>

#include <luabind/adopt_policy.hpp>

#include <bb/core/LuaState.h>
#include <bb/core/Log.h>
#include <bb/core/env.h>
#include <bb/core/Error.h>
#include <bb/core/mktdestmappings.h>
#include <bb/core/program_options.h>
#include <bb/clientcore/ClientCore_Scripting.h>
#include <bb/clientcore/ClientContext.h>
#include <bb/clientcore/IBook.h>
#include <bb/clientcore/BookBuilder.h>

using namespace bb;
using std::string;


namespace {
const char* const g_usage = "usage: book_printer [options]\nbook_printer -i FUT_CME_ES:2013 -s SRC_CME --live";
}


/// This is an implementation of IBookListener which prints a MarketLevel on every update.
class BookPrinter
    : public IBookListener
{
public:
    BookPrinter( IBookCPtr spBook )
        : m_spBook( spBook )
    {
        // subscribe to the Book
        if( !m_spBook )
            BB_THROW_ERROR_SS( "BookPrinter constructor: bad IBook" );
        m_spBook->addBookListener( this );
    }

    virtual ~BookPrinter()
    {
        // unsubscribe from the Book
        m_spBook->removeBookListener( this );
    }

    /// Prints the top of book whenever the best market changes.
    /// From clientcore/IBook.h:
    /// Invoked when the subscribed Book changes.
    /// The levelChanged entries are negative if there is no change, or a 0-based depth.
    /// This depth is a minimum -- there could be multiple deeper levels that changed
    /// since the last onBookChanged.
    virtual void onBookChanged( const IBook* pBook, const Msg* pMsg,
                                int32_t bidLevelChanged, int32_t askLevelChanged )
    {
        if( bidLevelChanged == 0 || askLevelChanged == 0 )
        {
            MarketLevel ml = getBestMarket( *pBook );

            std::cout << "L1 update --"
                      << " time:" << pBook->getLastChangeTime()
                      << " instr:" << pBook->getInstrument()
                      << " bid_sz:" << ml.getSize( BID )
                      << " bid_px:" << ml.getPrice( BID )
                      << " ask_px:" << ml.getPrice( ASK )
                      << " ask_sz:" << ml.getSize( ASK )
                      << " mid_px:" << pBook->getMidPrice()
                      << std::endl;
        }
    }

    /// Invoked when the subscribed Book is flushed.
    virtual void onBookFlushed( const IBook* pBook, const Msg* pMsg )
    {
        std::cout << "book flush --"
                  << " time:" << pBook->getLastChangeTime()
                  << " instr:" << pBook->getInstrument()
                  << std::endl;
    }

private:
    IBookCPtr m_spBook;
};


/// Setup BB, read the arguments, create the ClientContext, create the book and listener, and run.
int main( int argc, char* argv[] )
{
    bb::setLogger( "book_printer" );
    bb::default_init();

    instrument_t instr;
    bool run_live;
    date_t startdate;
    date_t enddate;
    source_t source;
    int verbose;
    std::string book_spec;

    namespace po = boost::program_options;
    bb::options_description po_desc("\n" \
                                    "example usage:\n" \
                                    "book_printer --instr FUT_CME_ES:201306 --date 2013-03-27\n" \
                                    "book_printer --instr SRC_SHFE:FUT_CFFEX_IF:201304 --date 2013-03-27\n" \
                                    "book_printer --instr FUT_CME_ES:201306 --live  ( from a datacenter where the data is broadcast )\n" \
                                    "\n" \
                                    "Options" \
        );
    po_desc.add_options()
        ( "instr,i", po::value( &instr ), "" )
        ( "live,l", po::bool_switch( &run_live ), "run live, ignoring startdate/enddate" )
        ( "date,d", po::value( &startdate ), "process historically for this date (YYYYMMDD or timeval)" )
        ( "start-date,s", po::value( &startdate ), "process historically from date (YYYYMMDD or timeval)" )
        ( "end-date,e", po::value( &enddate ), "stop processing historically at date (YYYYMMDD or timeval)" )
        ( "source,S", po::value( &source ), "source of book. auto-detects orig and dest if omitted" )
        ( "verbose,v", po::value( &verbose )->default_value( 0 ), "verbosity: 0, 1, 2, 3" )
        ( "bookspec,b", po::value( &book_spec ), "Lua code to define book spec" )
        ( "help", "print help message and exit" )
    ;

    try
    {
        bb::default_init();

        po::variables_map po_vars;
        parseOptionsSimple( po_vars, argc, argv, po_desc );

        BB_THROW_EXASSERT_SSX( instr.is_valid() || po_vars.count( "bookspec" ),
                               "invalid instrument" );

        timeval_t starttv, endtv;
        if( run_live )
        {
            starttv = timeval_t::earliest;
            endtv = timeval_t::latest;
        }
        else
        {
            if( !po_vars.count( "start-date" ) && !po_vars.count( "date" ) )
                BB_THROW_EXCEPTION( UsageError, "ERROR: you must specify a date if you are not running live" );

            starttv = startdate.timeval();

            if( po_vars.count( "end-date" ) )
            {
                endtv = enddate.timeval();
                if( endtv < starttv )
                    throw std::invalid_argument( "ERROR: enddate is before startdate!" );
            }
            else
                endtv = starttv + boost::posix_time::hours( 24 ) - boost::posix_time::seconds( 1 );
        }

        ClientContextPtr spContext = ClientContextFactory::create( bb::DefaultCoreContext::getEnvironment()
                                                                   , run_live, starttv, endtv,
                                                                   getLogger()->getname(), verbose );

        // Create a BookBuilder, get a Book from it
        // and create a BookPrinter
        IBookBuilderPtr spBookBuilder( new BookBuilder( spContext, false ) ); // useSrcMonitors => false
        IBookPtr spBook;

        if( !po_vars.count( "bookspec" ) )
        {
            if( !po_vars.count( "source" ) )
            {
                EFeedType feed = mktdest_to_primary_feed( instr.mkt );
                source.setType( feed );
            }

            if( ( source.orig() == bb::ORIG_UNKNOWN ) && ( source.dest() == bb::DEST_UNKNOWN ) )
            {
                if( run_live )
                {
                    source.autoSetOrigDest();
                }
                else
                {
                    source.setPrimaryOrigDest();
            }
            }
            BB_THROW_EXASSERT_SSX( source.isValid(), "Source must be valid" );

            spBook = spBookBuilder->buildSourceBook( instr, source );
        }
        else
        {
            bb::clientcore_registerScripting();

            bb::LuaState bookspec_config;
            bookspec_config.loadLibrary( "core" );
            bookspec_config.loadLibrary( "clientcore" );

            bookspec_config.execute( "bookspec = " + book_spec );

            luabind::object bookSpecLuaObj = bookspec_config.root()["bookspec"];

            IBookSpecPtr spBookSpec( luabind::object_cast<IBookSpecPtr>(
                                         bookSpecLuaObj ) );

            spBook = spBookBuilder->buildBook( IBookSpecPtr( spBookSpec->clone() ) );
        }

        shared_ptr<BookPrinter> spBookPrinter( new BookPrinter( spBook ) );

        // run the Context's EventDistributor with messages from the context's message stream
        spContext->run();
    }
    catch( const UsageError& ex )
    {
        if( ex.what()[0] == '\0' )
        {
            std::cout << g_usage << '\n' << po_desc << std::endl;
            return EXIT_SUCCESS;
        }
        else
        {
            std::cerr << "error: " << ex.what() << '\n' << g_usage << '\n' << po_desc << std::endl;
            return EXIT_FAILURE;
        }
    }
    catch( const std::exception& ex )
    {
        std::cerr << "error: " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }
}
