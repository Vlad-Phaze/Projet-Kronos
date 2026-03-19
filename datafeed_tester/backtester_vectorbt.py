"""Lightweight vectorbt backtester that re-uses existing fetcher and strategy.

Usage: run as script or import and call `run_backtest(pair, exchange, timeframe, lookback_days, params)`.
It fetches OHLCV via the existing fetcher, calls the strategy's `generate_signals(df, params)` to get a signals DataFrame
with a 'side' column containing 'long' or 'flat', then runs a vectorbt portfolio using those signals.
"""
from __future__ import annotations
import sys
from typing import Optional, Dict, Any
import pandas as pd

try:
    import vectorbt as vbt
except Exception:
    vbt = None

from datafeed_tester import fetcher
from datafeed_tester.strategies.buy_dip import DCAStrategy


def fetch_price_df(exchange: Optional[str], base: str, quote: str = 'USD', timeframe: str = '1h', lookback_days: int = 90,
                   start: Optional[pd.Timestamp] = None, end: Optional[pd.Timestamp] = None, force_fuse: bool = True):
    """
    Fetch price DataFrame for `base`.
    - If `exchange` is provided: use that exchange via ccxt.
    - If `exchange` is None: query known exchanges and perform a median fusion across available sources by default
      (force_fuse=True).
    Returns a DataFrame with a timezone-aware DatetimeIndex and columns including 'close'.
    """
    # Determine since/until
    if end is None:
        end = pd.Timestamp.utcnow().tz_localize('UTC')
    if start is None:
        start = end - pd.Timedelta(days=lookback_days)
    # Normalize to UTC tz-aware
    start = pd.to_datetime(start)
    end = pd.to_datetime(end)
    if start.tzinfo is None:
        start = start.tz_localize('UTC')
    if end.tzinfo is None:
        end = end.tz_localize('UTC')
    since_ms = int(start.timestamp() * 1000)
    until_ms = int(end.timestamp() * 1000)

    # If a specific exchange is requested, keep the original behaviour
    if exchange is not None:
        pair_info = fetcher.pick_tradable_pair_on_exchange(exchange, base)
        pair = pair_info.get('pair')
        if not pair:
            raise RuntimeError(f'No tradable pair found for {base} on {exchange}')

        df = fetcher.fetch_ohlcv_ccxt(exchange, pair, timeframe, since_ms, until_ms)
        if df.empty:
            raise RuntimeError('No OHLCV data returned')

        df = df.set_index('date')
        df = df.sort_index()
        
        # Normalize column names to lowercase for consistency with strategies and vectorbt
        df.columns = [col.lower() if isinstance(col, str) else col for col in df.columns]
        
        return df

    # No exchange specified: collect data from available exchanges and fuse (median)
    exchanges = fetcher.EXCHANGES
    # Use the fetcher orchestration which already fetches per-exchange dfs and scores them
    # Pass explicit since/until (ms) so fused multi-source fetch honors requested start/end
    _, _, data = fetcher.compare_exchanges_on_bases(exchanges, [base], timeframe, lookback_days, selection='best', since_ms=since_ms, until_ms=until_ms)

    # Collect per-exchange dataframes for this base
    dfs = []
    for ex in exchanges:
        ex_map = data.get(ex, {})
        if ex_map and base in ex_map:
            candidate = ex_map[base]
            if candidate is not None and not candidate.empty:
                dfs.append(candidate[["timestamp","date","open","high","low","close","volume"]].copy())

    if not dfs:
        raise RuntimeError(f'No OHLCV sources found across exchanges for base {base}')

    if force_fuse:
        fused = fetcher.fuse_ohlcv(dfs)
        df = fused
    else:
        # fallback: pick first available
        df = dfs[0]

    df = df.set_index('date')
    df = df.sort_index()
    
    # Normalize column names to lowercase for consistency with strategies and vectorbt
    df.columns = [col.lower() if isinstance(col, str) else col for col in df.columns]
    
    return df


def signals_from_strategy(df: pd.DataFrame, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    # The strategy exposes generate_signals(df, params) returning 'side' column
    # DCAStrategy does not require broker/data in constructor for the generate_signals method
    strat = DCAStrategy()
    # DCAStrategy.generate_signals is defined to take (df, params)
    signals = strat.generate_signals(df.rename(columns={'close':'Close'}).assign(close=df['close'] if 'close' in df.columns else df['Close']), params or {})
    if 'side' not in signals.columns:
        raise RuntimeError('Strategy did not return a signals DataFrame with a "side" column')
    return signals


def run_backtest(base: str, exchange: str = 'binance', timeframe: str = '1h', lookback_days: int = 90, params: Optional[Dict[str, Any]] = None, init_cash: float = 10000.0, start: Optional[str] = None, end: Optional[str] = None):
    if vbt is None:
        raise RuntimeError('vectorbt is not installed. Install it and retry (see datafeed_tester/requirements.txt)')

    # allow start/end as strings like '2025-01-01'
    start_dt = pd.to_datetime(start) if start is not None else None
    end_dt = pd.to_datetime(end) if end is not None else None

    df = fetch_price_df(exchange, base, timeframe=timeframe, lookback_days=lookback_days, start=start_dt, end=end_dt)

    # ensure 'close' column exists
    if 'close' not in df.columns and 'Close' in df.columns:
        df['close'] = df['Close']
    close = df['close']

    signals = signals_from_strategy(df, params)
    # Generate boolean entry/exit arrays
    entries = signals['side'] == 'long'
    exits = signals['side'] != 'long'

    # Align index
    entries = entries.reindex(close.index, method='ffill').fillna(False)
    exits = exits.reindex(close.index, method='ffill').fillna(False)

    pf = vbt.Portfolio.from_signals(close, entries, exits, init_cash=init_cash)
    stats = pf.stats()
    return pf, stats


def main():
    if len(sys.argv) < 2:
        print('Usage: backtester_vectorbt.py BASE [EXCHANGE]')
        sys.exit(1)
    base = sys.argv[1].upper()
    exchange = sys.argv[2] if len(sys.argv) > 2 else 'binance'
    try:
        pf, stats = run_backtest(base, exchange)
        print(stats)
    except Exception as e:
        print('Backtest failed:', e)


if __name__ == '__main__':
    main()
