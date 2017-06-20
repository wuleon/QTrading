#include "StrategyConfig.h"

namespace alphaless {

void StrategySettings::describe()
{
    Self::create()
        .param( "market"                     , &Self::market )
        .param( "feed_orig"                  , &Self::feed_orig )
        .param( "feed_dest"                  , &Self::feed_dest )
        .param( "feed_type"                  , &Self::feed_type )
        .param( "trade_server"               , &Self::trade_server )
        .param( "instruments"                , &Self::instruments )
        .param( "sim_order_book"             , &Self::sim_order_book )
        .param( "start_hour"                 , &Self::start_hour )
        .param( "start_minute"               , &Self::start_minute )
        .param( "start_second"               , &Self::start_second )
        .param( "end_hour"                   , &Self::end_hour )
        .param( "end_minute"                 , &Self::end_minute )
        .param( "end_second"                 , &Self::end_second )
        .param( "shares"                     , &Self::shares )
        ;
}


} // strategy


