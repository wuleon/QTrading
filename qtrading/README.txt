Usage:

# Historical mode
alphaless --start-date "2017-03-22 09:00:00" --end-date "2017-03-22 16:30:00" \
--id shance_test -a <YOUR_ACCOUNT> -c strategy_config.lua

# Live mode without order routing
alphaless --id shance_test -a <YOUR_ACCOUNT> -c strategy_config.lua -l

# Live mode *with* order routing
alphaless --id shance_test -a <YOUR_ACCOUNT> -c strategy_config.lua -l -r

Please replace <YOUR_ACCOUNT> with the actual account you were given.
