require('utils')

strategy_config = { --this object is parsed into a StrategyConfig object

    market = "MKT_DCE",
    feed_orig = "ORIG_HTD",
    feed_dest = "DEST_JINGYI",
    feed_type = "SRC_ACR_DCE_L2",
    trade_server = "auto",

    instruments = {
	"FUT_DCE_PP:201609"
    },

    sim_order_book = cons{
        AsiaQueueInstrOrderBookSpec,
        look_ahead_exchange = {
            enabled = true,
            verbose = true,
            use_fixed_look_ahead_time = true,
            fixed_look_ahead_time = Duration(.5), -- in seconds
            -- max_advance_duration = Duration(.5),
        }
    },

    -- other options can be added as needed
    start_hour = 10,
    start_minute = 15,
    start_second = 0,
    end_hour = 14,
    end_minute = 15,
    end_second = 0,

    shares = 100
}
