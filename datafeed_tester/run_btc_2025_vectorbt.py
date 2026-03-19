from datafeed_tester.backtester_vectorbt import run_backtest

if __name__ == '__main__':
    base = 'BTC'
    exchange = 'binance'
    start = '2025-01-01'
    end = '2025-12-31'
    init_cash = 1_000_000
    print('Running BTC 2025 backtest...')
    pf, stats = run_backtest(base, exchange, timeframe='1h', lookback_days=365, init_cash=init_cash, start=start, end=end)
    print(stats)
    # Save a small report
    stats.to_csv('datafeed_tester/btc_2025_vectorbt_stats.csv')
    print('Saved datafeed_tester/btc_2025_vectorbt_stats.csv')
