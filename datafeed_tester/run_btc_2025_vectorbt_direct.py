import time
import requests
import pandas as pd
from datetime import datetime, timezone

from datafeed_tester.strategies.buy_dip import DCAStrategy
import vectorbt as vbt


def fetch_binance_klines(symbol: str, interval: str, start_ts: int, end_ts: int):
    url = 'https://api.binance.com/api/v3/klines'
    limit = 1000
    interval_ms = {
        '1h': 3600_000,
        '1m': 60_000,
        '1d': 86_400_000
    }[interval]

    rows = []
    cur = start_ts
    while cur < end_ts:
        to_ts = min(end_ts, cur + limit * interval_ms - 1)
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': cur,
            'endTime': to_ts,
            'limit': limit
        }
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        rows.extend(data)
        last_ts = data[-1][0]
        cur = last_ts + interval_ms
        time.sleep(0.25)
    return rows


def klines_to_df(klines):
    cols = ['open_time','open','high','low','close','volume','close_time','qav','num_trades','tb_base_av','tb_quote_av','ignore']
    df = pd.DataFrame(klines, columns=cols)
    df['open'] = pd.to_numeric(df['open'])
    df['high'] = pd.to_numeric(df['high'])
    df['low'] = pd.to_numeric(df['low'])
    df['close'] = pd.to_numeric(df['close'])
    df['volume'] = pd.to_numeric(df['volume'])
    df['date'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df = df.set_index('date')
    return df


def run():
    symbol = 'BTCUSDT'
    interval = '1h'
    # define 2025 range
    start = int(datetime(2025,1,1,tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2025,12,31,23,59,59,tzinfo=timezone.utc).timestamp() * 1000)
    print('Fetching klines...')
    klines = fetch_binance_klines(symbol, interval, start, end)
    df = klines_to_df(klines)
    print('Rows fetched:', len(df))

    # Prepare df expected by strategy: ensure 'close' column exists
    # Strategy expects df['close'] (lowercase)
    if 'close' not in df.columns and 'Close' in df.columns:
        df['close'] = df['Close']

    strat = DCAStrategy(None, None, {})
    signals = strat.generate_signals(df, {})
    entries = signals['side'] == 'long'
    exits = signals['side'] != 'long'

    # align with close series
    close = df['close']
    entries = entries.reindex(close.index, method='ffill').fillna(False)
    exits = exits.reindex(close.index, method='ffill').fillna(False)

    pf = vbt.Portfolio.from_signals(close, entries, exits, init_cash=1_000_000)
    stats = pf.stats()
    print(stats)
    stats.to_csv('datafeed_tester/btc_2025_vectorbt_stats_direct.csv')
    print('Saved datafeed_tester/btc_2025_vectorbt_stats_direct.csv')


if __name__ == '__main__':
    run()
