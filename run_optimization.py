#!/usr/bin/env python3
"""Optimisation de paramètres SmartBot V2 sur un portefeuille complet.

Exemple :
    python run_optimization.py --assets BTC ETH SOL ADA --timeframe 1h \
        --start 2023-01-01 --end 2025-01-01 --trials 3000 --max-dd 35

Les données sont mises en cache (datafeed_tester/.cache) : seule la 1re exécution télécharge.
Pour limiter le sur-apprentissage : optimiser sur --start/--end puis valider les meilleurs jeux
avec --start/--end différents (période "hors échantillon") via backtest_portfolio_fast.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):  # console Windows (cp1252) : le fetcher affiche des emojis
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "datafeed_tester"))

from backtester_exact import ParametresDCA_SmartBotV2  # noqa: E402
from backtester_fast import PreparedPortfolio, optimize_portfolio  # noqa: E402
from fetch_cache import fetch_final_cached  # noqa: E402
from fetcher import compare_exchanges_on_bases  # noqa: E402

# Espace de recherche par défaut : liste = choix discrets, (min, max) = intervalle continu / entier
DEFAULT_SPACE = {
    "take_profit": (0.5, 4.0),
    "pricedevbase": ["ATR", "From Last Safety Order", "From Base Order"],
    "price_deviation": (1.0, 8.0),
    "atr_mult": (1.0, 5.0),
    "atr_mult_step_scale": (1.0, 1.5),
    "max_safe_order": (3, 12),
    "safe_order_volume_scale": (1.0, 2.0),
    "dsc": ["RSI", "RSI + MFI", "RSI + BB", "BB + MFI", "All Three"],
    "rsi_length": [2, 3, 5, 7, 14],
    "dsc_rsi_threshold_low": (3, 40),
    "mfi_threshold_low": (15, 45),
    "max_active_trades": [2, 3, 5],
}


def load_assets(assets, timeframe, start, end, exchange):
    to_ms = lambda s: int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    exchanges = [exchange] + [e for e in ["binance", "coinbase", "kraken", "kucoin", "okx"] if e != exchange]
    data = fetch_final_cached(compare_exchanges_on_bases, exchanges, assets, timeframe, to_ms(start), to_ms(end))
    out = {}
    for asset, df in data["__FINAL__"].items():
        df = df.copy()
        df.index = pd.to_datetime(df["date"], utc=True) if "date" in df.columns else \
            pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.rename(columns=str.capitalize)[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df = df[(df.index >= pd.Timestamp(start, tz="UTC")) & (df.index <= pd.Timestamp(end, tz="UTC"))]
        if not df.empty:
            out[asset] = df
    missing = set(assets) - set(out)
    if missing:
        print(f"⚠️ Assets sans données: {sorted(missing)}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", nargs="+", required=True)
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2025-01-01")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--trials", type=int, default=2000)
    ap.add_argument("--objective", default="calmar", help="calmar | return_pct | final_equity | realized_pnl")
    ap.add_argument("--max-dd", type=float, default=None, help="drawdown equity max accepté (%%)")
    ap.add_argument("--min-trades", type=int, default=20)
    ap.add_argument("--capital", type=float, default=100000.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="optimization_results.csv")
    args = ap.parse_args()

    assets = load_assets(args.assets, args.timeframe, args.start, args.end, args.exchange)
    if not assets:
        sys.exit("Aucune donnée disponible")
    prep = PreparedPortfolio(assets)
    print(f"📊 {len(assets)} assets, {len(prep.timeline)} barres alignées")

    res = optimize_portfolio(
        prep, DEFAULT_SPACE, n_trials=args.trials,
        base_params=ParametresDCA_SmartBotV2(initial_capital=args.capital),
        objective=args.objective, max_dd_limit=args.max_dd, min_trades=args.min_trades, seed=args.seed,
    )
    res.to_csv(args.out, index=False)
    cols = [c for c in res.columns if c not in ("final_cash", "cash_dd_pct", "win_rate_deals")]
    print(f"\n🏆 Top 10 (sur {len(res)} essais, résultats complets dans {args.out})")
    print(res.head(10)[cols].to_string())


if __name__ == "__main__":
    main()
