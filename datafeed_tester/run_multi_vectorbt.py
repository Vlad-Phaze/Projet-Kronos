"""Run a strategy across multiple bases and aggregate results.

Usage examples:
  PYTHONPATH=. ./venv/bin/python datafeed_tester/run_multi_vectorbt.py --bases BTC,ETH --exchange binance --start 2025-01-01 --end 2025-12-31 --init-cash 1000000

The script will:
 - fetch OHLCV per base via `backtester_vectorbt.fetch_price_df`
 - generate signals using `DCAStrategy.generate_signals`
 - run a per-base vectorbt Portfolio with equal capital split
 - sum per-base equity curves to produce a combined portfolio equity curve
 - save per-base stats and combined stats + equity to CSV files
"""
from __future__ import annotations
import argparse
from typing import List, Optional
import pandas as pd
import numpy as np

try:
    import vectorbt as vbt
except Exception:
    vbt = None

from datafeed_tester.backtester_vectorbt import fetch_price_df
from datafeed_tester import fetcher as fetcher_module
import importlib
import importlib.util
import os
from typing import Type


def load_strategy_class(ref: str) -> Type:
    """
    Load a strategy class from a reference string.
    Supported formats:
      - module_path:ClassName  (e.g. datafeed_tester.strategies.buy_dip:DCAStrategy)
      - /abs/or/rel/path.py:ClassName
    Returns the class object.
    """
    if ':' in ref:
        module_part, class_name = ref.split(':', 1)
    else:
        module_part, class_name = ref, None

    # file path
    if os.path.isfile(module_part):
        spec = importlib.util.spec_from_file_location('user_strategy', module_part)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
    else:
        module = importlib.import_module(module_part)

    if class_name:
        if not hasattr(module, class_name):
            raise ImportError(f"Strategy class {class_name} not found in {module_part}")
        return getattr(module, class_name)
    # fallback: try common names
    for cand in ('DCAStrategy', 'MyTestStrategy', 'Strategy'):
        if hasattr(module, cand):
            return getattr(module, cand)
    raise ImportError(f"No strategy class found in {module_part}; provide Module:Class")


def run_multi_backtest(bases: List[str], exchange: Optional[str] = None, timeframe: str = '1h', init_cash: float = 100000.0,
                       start: Optional[str] = None, end: Optional[str] = None, weights: Optional[List[float]] = None,
                       fee: float = 0.0, slippage: float = 0.0, max_active_trades: Optional[int] = None, 
                       strategy_ref: Optional[str] = None, strategy_params: Optional[dict] = None):
    if vbt is None:
        raise RuntimeError('vectorbt is not installed')

    n = len(bases)
    if n == 0:
        raise ValueError('No bases provided')

    # determine weights: either provided or equal split
    if weights is None:
        weights = [1.0 / n] * n
    else:
        if len(weights) != n:
            raise ValueError('Number of weights must match number of bases')
        total_w = sum(weights)
        if total_w <= 0:
            raise ValueError('Sum of weights must be positive')
        # normalize
        weights = [w / total_w for w in weights]

    per_asset_equities = {}
    per_asset_stats = []
    # collect per-asset raw signals first
    per_asset_raw = {}
    # We will use fetch_price_df with exchange=None which will ask the fetcher to collect
    # multiple sources and perform a median fusion by default.

    # compute lookback_days to forward to fetch_price_df when possible
    if start is not None and end is not None:
        try:
            start_dt = pd.to_datetime(start)
            end_dt = pd.to_datetime(end)
            lookback_days = max(1, int((end_dt - start_dt).days) + 1)
        except Exception:
            lookback_days = fetcher_module.LOOKBACK_DAYS
    else:
        lookback_days = fetcher_module.LOOKBACK_DAYS

    # Load strategy class
    strategy_cls = None
    if strategy_ref:
        strategy_cls = load_strategy_class(strategy_ref)

    # Phase 1: OPTIMISATION - Fetch all data in ONE call to avoid repeated fetcher overhead
    import time
    fetch_start = time.time()
    print(f'\n📥 Fetching data for {len(bases)} assets in ONE batch...')
    print(f'   Assets: {", ".join(bases)}')
    all_data = {}
    
    if exchange is None:
        # Multi-exchange fusion: fetch ALL bases at once
        exchanges = fetcher_module.EXCHANGES
        print(f'   🔄 Calling fetcher ONCE for all {len(bases)} assets across {len(exchanges)} exchanges...')
        if start is not None and end is not None:
            start_dt = pd.to_datetime(start)
            end_dt = pd.to_datetime(end)
            if start_dt.tzinfo is None:
                start_dt = start_dt.tz_localize('UTC')
            if end_dt.tzinfo is None:
                end_dt = end_dt.tz_localize('UTC')
            since_ms = int(start_dt.timestamp() * 1000)
            until_ms = int(end_dt.timestamp() * 1000)
        else:
            since_ms = None
            until_ms = None
        
        api_call_start = time.time()
        _, _, data = fetcher_module.compare_exchanges_on_bases(
            exchanges, bases, timeframe, lookback_days, 
            selection='best', since_ms=since_ms, until_ms=until_ms
        )
        api_call_duration = time.time() - api_call_start
        print(f'   ✅ Single API call completed in {api_call_duration:.2f}s')
        
        # Extract and fuse data for each base
        for base in bases:
            dfs = []
            for ex in exchanges:
                ex_map = data.get(ex, {})
                if ex_map and base in ex_map:
                    candidate = ex_map[base]
                    if candidate is not None and not candidate.empty:
                        dfs.append(candidate[["timestamp","date","open","high","low","close","volume"]].copy())
            
            if dfs:
                fused = fetcher_module.fuse_ohlcv(dfs)
                fused = fused.set_index('date').sort_index()
                fused.columns = [col.lower() if isinstance(col, str) else col for col in fused.columns]
                all_data[base] = fused
                print(f'     ✅ {base}: {len(fused)} bars')
            else:
                print(f'     ⚠️  {base}: No data available')
    else:
        # Single exchange: fetch each base individually (less optimizable)
        print(f'   ⚠️  Single exchange mode: will fetch each asset separately')
        for base in bases:
            try:
                df = fetch_price_df(exchange, base, timeframe=timeframe, lookback_days=lookback_days, start=start, end=end)
                if df is not None and not df.empty:
                    all_data[base] = df
                    print(f'     ✅ {base}: {len(df)} bars')
            except Exception as e:
                print(f'     ⚠️  {base}: Error - {e}')
    
    fetch_duration = time.time() - fetch_start
    print(f'\n✅ Total fetching time: {fetch_duration:.2f}s')
    print(f'   Data loaded: {len(all_data)}/{len(bases)} assets')
    print(f'   Average: {fetch_duration/len(bases):.2f}s per asset\n')

    # Phase 2: Generate signals for each asset
    for i, base in enumerate(bases):
        if base not in all_data:
            print(f'  {base}: Skipped (no data)')
            continue
            
        df = all_data[base]
        if 'close' not in df.columns and 'Close' in df.columns:
            df['close'] = df['Close']

        # generate signals (strategy returns 'side' column: 'long' or 'flat')
        params_to_pass = strategy_params if strategy_params else {}
        if strategy_cls is not None:
            strat = strategy_cls()
            # support both object API and simple generate_signals function
            if hasattr(strat, 'generate_signals'):
                signals = strat.generate_signals(df, params_to_pass)
            else:
                raise RuntimeError('Loaded strategy does not expose generate_signals')
        else:
            # fallback to built-in buy_dip DCAStrategy
            from datafeed_tester.strategies.buy_dip import DCAStrategy
            strat = DCAStrategy()
            signals = strat.generate_signals(df, params_to_pass)
        if 'side' not in signals.columns:
            print(f'  Strategy did not return side column for {base} (skipping)')
            continue

        # side boolean series: True when long
        side = (signals['side'] == 'long').reindex(df.index, method='ffill').fillna(False)
        # compute edge events (entry = transition False->True, exit = True->False)
        prev = side.shift(1).fillna(False)
        entry_events = (side & ~prev).astype(bool)
        exit_events = (~side & prev).astype(bool)

        per_asset_raw[base] = {
            'df': df,
            'close': df['close'],
            'entry_events': entry_events,
            'exit_events': exit_events,
            'index': df.index,
            'has_entries': entry_events.any()  # Track if this asset has at least 1 entry signal
        }

    if not per_asset_raw:
        raise RuntimeError('No assets had valid data/signals')

    # Filter assets that actually have entry signals (will trade)
    bases_with_trades = [b for b, info in per_asset_raw.items() if info['has_entries']]
    bases_with_data_no_trades = [b for b, info in per_asset_raw.items() if not info['has_entries']]
    skipped_bases = [b for b in bases if b not in per_asset_raw]
    
    # REDISTRIBUTION DU CAPITAL: utiliser seulement les paires qui traderont
    n_active = len(bases_with_trades)
    
    if n_active == 0:
        raise RuntimeError('No assets generated any entry signals')
    
    print(f'\n💰 Capital allocation:')
    print(f'   Total capital: ${init_cash:,.2f}')
    print(f'   Assets requested: {len(bases)}')
    print(f'   Assets with data: {len(per_asset_raw)}')
    print(f'   Assets with entry signals: {n_active}')
    print(f'   Capital per trading asset: ${init_cash / n_active:,.2f} ({100/n_active:.2f}% each)')
    
    if skipped_bases:
        print(f'   ⚠️  No data ({len(skipped_bases)}): {", ".join(skipped_bases)}')
    if bases_with_data_no_trades:
        print(f'   ⚠️  No entry signals ({len(bases_with_data_no_trades)}): {", ".join(bases_with_data_no_trades)}')
    
    # Recalculate weights to redistribute capital on TRADING assets only
    if weights is None or len(weights) != n_active:
        # Equal split among TRADING assets
        active_weights = [1.0 / n_active] * n_active
    else:
        # Filter and renormalize provided weights for trading assets
        active_weights = []
        for i, base in enumerate(bases):
            if base in bases_with_trades:
                active_weights.append(weights[i])
        total_w = sum(active_weights)
        active_weights = [w / total_w for w in active_weights]

    # Phase 2: build global timeline and simulate max active trades
    # global index is the union of all asset indexes
    print(f'\n🔄 Building synchronized global timeline...')
    all_indexes = None
    for info in per_asset_raw.values():
        if all_indexes is None:
            all_indexes = info['index']
        else:
            all_indexes = all_indexes.union(info['index'])
    global_index = pd.DatetimeIndex(sorted(set(all_indexes)))
    
    print(f'   Global timeline: {len(global_index)} bars from {global_index[0]} to {global_index[-1]}')
    for base, info in per_asset_raw.items():
        overlap = len(info['index'].intersection(global_index))
        print(f'   {base}: {len(info["index"])} bars, {overlap} overlap with global timeline ({overlap/len(global_index)*100:.1f}%)')
    
    if max_active_trades is not None:
        print(f'\n⚙️  Max Active Trades: {max_active_trades}')
    else:
        print(f'\n⚙️  Max Active Trades: Unlimited')
    print(f'   Processing {len(global_index)} bars synchronously across {len(per_asset_raw)} assets...\n')

    # reindex events to global index
    entry_global = {b: info['entry_events'].reindex(global_index, fill_value=False) for b, info in per_asset_raw.items()}
    exit_global = {b: info['exit_events'].reindex(global_index, fill_value=False) for b, info in per_asset_raw.items()}

    # initialize allowed events - ONLY for assets that will trade
    allowed_entry = {b: pd.Series(False, index=global_index) for b in bases_with_trades}
    allowed_exit = {b: pd.Series(False, index=global_index) for b in bases_with_trades}

    active_set = set()
    bases_in_order = bases_with_trades  # Only process assets that have entry signals
    
    # Statistics for gating
    total_entries_requested = 0
    total_entries_allowed = 0
    total_entries_blocked = 0
    max_simultaneous_reached = 0

    for t in global_index:
        # first process exits (close trades)
        for b in bases_in_order:
            if exit_global[b].get(t, False):
                if b in active_set:
                    allowed_exit[b].at[t] = True
                    active_set.remove(b)
        # then process entries in provided order
        for b in bases_in_order:
            if entry_global[b].get(t, False):
                total_entries_requested += 1
                if b in active_set:
                    # already active; ignore
                    continue
                # check if we can open new trade
                if max_active_trades is None or len(active_set) < int(max_active_trades):
                    allowed_entry[b].at[t] = True
                    active_set.add(b)
                    total_entries_allowed += 1
                else:
                    # suppressed due to max active trades
                    total_entries_blocked += 1
        
        # Track maximum simultaneous positions
        if len(active_set) > max_simultaneous_reached:
            max_simultaneous_reached = len(active_set)
    
    if max_active_trades is not None:
        print(f'📊 Gating Statistics:')
        print(f'   Max simultaneous positions reached: {max_simultaneous_reached} / {max_active_trades}')
        print(f'   Total entry signals: {total_entries_requested}')
        print(f'   Entries allowed: {total_entries_allowed} ({total_entries_allowed/total_entries_requested*100:.1f}%)')
        print(f'   Entries blocked: {total_entries_blocked} ({total_entries_blocked/total_entries_requested*100:.1f}%)')
        print()

    # Phase 3: run per-asset portfolios using allowed events mapped back to each asset's index
    for i, base in enumerate(bases_in_order):
        info = per_asset_raw[base]
        df = info['df']
        close = info['close']
        # map allowed events back to asset index
        entries = allowed_entry[base].reindex(df.index, method=None).fillna(False).astype(bool)
        exits = allowed_exit[base].reindex(df.index, method=None).fillna(False).astype(bool)

        cash_for_asset = init_cash * active_weights[i]
        print(f'Running vectorbt portfolio for {base} with cash {cash_for_asset} (weight {active_weights[i]:.4f})...')
        pf = vbt.Portfolio.from_signals(close, entries, exits, init_cash=cash_for_asset, fees=fee, slippage=slippage)

        per_asset_equities[base] = pf.value()
        stats = pf.stats()
        stats_df = stats.to_frame().T
        stats_df.columns = [f"{base}_{c}" for c in stats_df.columns]
        per_asset_stats.append(stats_df)

    # Align and sum equities
    eq_df = pd.concat(per_asset_equities, axis=1)
    # forward-fill small gaps then drop rows that are all NaN
    eq_df = eq_df.sort_index().ffill().dropna(how='all')
    combined_equity = eq_df.sum(axis=1)

    # Combined metrics
    start_value = combined_equity.iloc[0]
    end_value = combined_equity.iloc[-1]
    total_return_pct = (end_value / start_value - 1) * 100
    # Drawdown
    peak = combined_equity.cummax()
    drawdown = (combined_equity - peak) / peak
    max_drawdown_pct = drawdown.min() * 100

    combined_stats = pd.Series({
        'Start Value': start_value,
        'End Value': end_value,
        'Total Return [%]': total_return_pct,
        'Max Drawdown [%]': max_drawdown_pct,
        'Num Assets Requested': len(bases),
        'Num Assets With Data': len(per_asset_raw),
        'Num Assets Active': n_active,
        'Num Assets No Data': len(skipped_bases),
        'Num Assets No Signals': len(bases_with_data_no_trades),
        'Skipped Assets (No Data)': ', '.join(skipped_bases) if skipped_bases else 'None',
        'Skipped Assets (No Signals)': ', '.join(bases_with_data_no_trades) if bases_with_data_no_trades else 'None'
    })

    # Save outputs
    per_stats_df = pd.concat(per_asset_stats, axis=0)
    per_stats_df.to_csv('multi_vectorbt_per_asset_stats.csv')
    eq_df.to_csv('multi_vectorbt_per_asset_equity.csv')
    combined_equity.to_frame('equity').to_csv('multi_vectorbt_combined_equity.csv')
    combined_stats.to_csv('multi_vectorbt_combined_stats.csv')

    print('Saved multi_vectorbt_per_asset_stats.csv')
    print('Saved multi_vectorbt_per_asset_equity.csv')
    print('Saved multi_vectorbt_combined_equity.csv')
    print('Saved multi_vectorbt_combined_stats.csv')

    return per_stats_df, combined_stats, eq_df, combined_equity


def parse_bases(s: str) -> List[str]:
    return [x.strip().upper() for x in s.split(',') if x.strip()]


def parse_weights(s: Optional[str]) -> Optional[List[float]]:
    if s is None:
        return None
    parts = [p.strip() for p in s.split(',') if p.strip()]
    return [float(p) for p in parts]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--bases', required=True, help='Comma-separated base symbols, e.g. BTC,ETH')
    p.add_argument('--exchange', default=None, help='Optional: ccxt exchange id to force (default: let fetcher choose across known exchanges)')
    p.add_argument('--timeframe', default='1h')
    p.add_argument('--init-cash', type=float, default=100000.0)
    p.add_argument('--start', default=None)
    p.add_argument('--end', default=None)
    p.add_argument('--weights', default=None, help='Comma-separated weights e.g. 0.6,0.4')
    p.add_argument('--fee', type=float, default=0.0, help='Trading fee as fraction, e.g. 0.0005')
    p.add_argument('--slippage', type=float, default=0.0, help='Slippage as fraction, e.g. 0.001')
    p.add_argument('--max-active-trades', type=int, default=None, help='Maximum number of concurrently active long trades across all assets')
    p.add_argument('--strategy', default=None, help='Strategy reference Module:Class or path/to/file.py:Class')
    args = p.parse_args()

    bases = parse_bases(args.bases)
    weights = parse_weights(args.weights)
    run_multi_backtest(bases, exchange=args.exchange, timeframe=args.timeframe, init_cash=args.init_cash, start=args.start, end=args.end, weights=weights, fee=args.fee, slippage=args.slippage, max_active_trades=args.max_active_trades, strategy_ref=args.strategy)


if __name__ == '__main__':
    main()
