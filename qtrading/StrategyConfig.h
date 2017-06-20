#include <string>
#include <vector>

#include <bb/core/smart_ptr.h>
#include <bb/core/LuaConfig.h>
#include <bb/core/EFeedType.h>
#include <bb/core/EFeedOrig.h>
#include <bb/core/EFeedDest.h>
#include <bb/core/instrument.h>

#include <bb/simulator/markets/AsiaQueueInstrOrderBook.h>

namespace alphaless {

// global options to configure the strategy
struct StrategySettings : public bb::LuaConfig<StrategySettings>
{
    // Optional feature - Your config file can be written in a scripting language
    // this saves time writing parsing code for input/parameter files.
    // Also enables dynamic value setting on a daily basis.
    // Ask ShanCe's Engineering team for guidance with Lua

    std::string market;
    std::string feed_orig; 
    std::string feed_dest; 
    std::string feed_type; 
    std::string trade_server;

    std::vector<std::string> instruments;
    bb::simulator::AsiaQueueInstrOrderBookSpecPtr sim_order_book;

    int start_hour, start_minute, start_second;
    int end_hour, end_minute, end_second;
    int shares;

    static void describe();

};

} // strategy
