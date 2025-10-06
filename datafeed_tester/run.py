# run.py
from __future__ import annotations

import argparse
import importlib
import os
from typing import Any, Dict

import yaml
import numpy as np
import pandas as pd

from datafeed_tester.core.fetcher_adapter import fetch_market_data
from datafeed_tester.core.backtester_adapter import run_backtest_with_strategy
from datafeed_tester.core.io import save_equity_and_trades, make_run_id


# -----------------------------
# Chargement de config tolérant
# -----------------------------
def load_config(path: str) -> dict:
    """
    Charge un YAML. Si le fichier est absent ou vide -> {}.
    """
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


# -----------------------------
# Chargement dynamique stratégie
# -----------------------------
def load_strategy(dotted_path: str):
    """
    Accepte:
      - 'module:build_strategy' -> appelle la fabrique
      - 'module:ClassName'      -> instancie la classe
    """
    if ":" not in dotted_path:
        raise ValueError("La stratégie doit être du type 'module.sousmodule:factory_ou_Classe'")
    mod_name, name = dotted_path.split(":")
    mod = importlib.import_module(mod_name)
    obj = getattr(mod, name)
    if isinstance(obj, type):   # classe
        return obj()
    if callable(obj):           # fabrique
        # On retourne la fabrique elle-même, elle sera appelée plus tard avec les bons arguments
        return obj
    raise TypeError(f"{dotted_path}: ni fabrique callable ni classe.")


# -----------------------------
# Helpers métriques avancées
# -----------------------------
def _minutes_per_bar_from_timeframe(tf: str) -> float:
    lut = {
        "1m":1, "3m":3, "5m":5, "15m":15, "30m":30,
        "1h":60, "2h":120, "4h":240, "6h":360, "8h":480, "12h":720,
        "1d":1440, "3d":4320, "1w":10080
    }
    return float(lut.get(tf, 60.0))  # défaut: 1h

def _bars_per_year(tf: str) -> float:
    minutes_year = 365.0 * 24.0 * 60.0  # 525600
    return minutes_year / _minutes_per_bar_from_timeframe(tf)

def compute_dd(equity: pd.Series) -> float:
    """Max drawdown (valeur la plus négative) sur la courbe 'equity' (P&L cumulé)."""
    if equity is None or equity.empty:
        return 0.0
    roll_max = equity.cummax()
    dd = equity - roll_max
    return float(dd.min())  # négatif ou 0

def compute_ratios(equity_df: pd.DataFrame, timeframe: str) -> dict:
    """
    Sharpe/Sortino/Calmar à partir de la série 'equity' (P&L cumulé).
    -> On considère les 'retours' comme les variations de P&L par barre (diff d'equity).
    -> Annualisation par nb de barres/an (comparatif entre runs/timeframes).
    """
    if equity_df is None or equity_df.empty or "equity" not in equity_df.columns:
        return {"sharpe": np.nan, "sortino": np.nan, "calmar": np.nan}

    eq = equity_df["equity"].astype(float)
    rets = eq.diff().dropna()
    if rets.empty:
        return {"sharpe": np.nan, "sortino": np.nan, "calmar": np.nan}

    ann_bar_sqrt = np.sqrt(_bars_per_year(timeframe))

    mu = float(np.mean(rets))
    sig = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = (mu / sig * ann_bar_sqrt) if sig > 0 else np.nan

    downside = rets[rets < 0.0]
    dsig = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = (mu / dsig * ann_bar_sqrt) if dsig > 0 else np.nan

    ann_return = mu * _bars_per_year(timeframe)  # approx rendement/an
    mdd = compute_dd(eq)                         # négatif
    calmar = (ann_return / abs(mdd)) if mdd < 0 else np.nan

    return {"sharpe": sharpe, "sortino": sortino, "calmar": calmar}


# -----------------------------
# Main
# -----------------------------
def main():
    p = argparse.ArgumentParser(description="Orchestrateur fetcher + backtester")
    p.add_argument("--config", default="config.yaml", help="Fichier YAML de config")
    p.add_argument("--strategy", required=True, help="ex: strategies.buy_dip:build_strategy ou :BuyDip")
    p.add_argument("--symbols", nargs="+", help="override des bases (sinon config)")
    p.add_argument("--timeframe", help="override (sinon config)")
    p.add_argument("--lookback", type=int, help="override (sinon config)")
    p.add_argument("--selection", choices=["best", "fixed"], help="mode de sélection de la source")
    p.add_argument("--fixed-exchange", help="exchange fixe si --selection fixed")
    p.add_argument("--allowed", nargs="+", help="limiter aux exchanges autorisés (filtre)")
    p.add_argument("--groups", action="store_true", help="activer l’expansion des groupes (Large Cap, etc.)")

    # Export
    p.add_argument("--save", action="store_true", help="sauvegarder equity/trades")
    p.add_argument("--outdir", default=None, help="dossier de sortie (override config)")
    p.add_argument("--fmt", nargs="+", default=None, help="formats d’export: csv parquet")

    args = p.parse_args()

    # 1) Config + fallbacks
    cfg: Dict[str, Any] = load_config(args.config)

    bases = args.symbols or cfg.get("bases", ["BTC", "ETH"])
    timeframe = args.timeframe or cfg.get("timeframe", "1h")
    lookback = int(args.lookback or cfg.get("lookback_days", 30))
    selection = args.selection or cfg.get("selection", "best")
    fixed = args.fixed_exchange or cfg.get("fixed_exchange")
    allowed = args.allowed or cfg.get("allowed_exchanges")
    exchanges = cfg.get("exchanges")  # None -> le fetcher utilisera ses defaults
    use_groups = bool(args.groups or cfg.get("use_group_expansion", False))

    # Export
    want_save = bool(args.save or cfg.get("save_exports", False))
    out_dir = args.outdir or cfg.get("export_dir", "data/exports")
    fmts = args.fmt or cfg.get("export_formats", ["csv", "parquet"])
    run_id = make_run_id() if want_save else None

    # 2) FETCH: données finales + provenance + erreurs
    data_final, meta_final, errors, agg, detail = fetch_market_data(
        bases=bases,
        timeframe=timeframe,
        lookback_days=lookback,
        exchanges=exchanges,
        selection=selection,
        fixed_exchange=fixed,
        allowed_exchanges=allowed,
        use_group_expansion=use_groups,
    )

    # 3) STRAT
    strategy_obj = load_strategy(args.strategy)
    strat_params = cfg.get("strategy_params", {})
    # Si c'est une fabrique, on l'appelle avec les bons arguments
    if callable(strategy_obj):
        # Il faut définir broker et data ici, adapte selon ton projet
        broker = None  # Remplace par l'objet broker si tu en as un
        data = None    # Remplace par l'objet data si tu en as un
        strategy = strategy_obj(broker, data, strat_params)
    else:
        strategy = strategy_obj
    strat_name = strategy.name() if hasattr(strategy, "name") else strategy.__class__.__name__

    # 4) BACKTEST (par base) + export optionnel
    for base, df in data_final.items():
        # Remplacer toutes les valeurs NaN, None ou null par 0.0 dans stats
        for k, v in stats.items():
            try:
                if v is None or (isinstance(v, (float, int)) and np.isnan(v)):
                    stats[k] = 0.0
            except Exception:
                stats[k] = 0.0
        if df is None or df.empty:
            print(f"[WARN] {base}: pas de données finales.")
            continue


        equity_df, stats = run_backtest_with_strategy(df, strategy, strat_params)
        provenance = meta_final.get(base, {}).get("provenance", "Provenance inconnue")

        # Supprimer trades_df pour la réponse front
        if "trades_df" in stats:
            del stats["trades_df"]

        # ...le reste du code d'affichage et d'export inchangé...

    # 5) Récap erreurs (prêt pour le front)
    if errors:
        print("\n=== ERRORS ===")
        for e in errors:
            sm = e.get("short_message") or e.get("message")
            print(f"[{e.get('where')}] {sm} (code={e.get('code')}) ctx={e.get('context')}")


if __name__ == "__main__":
    main()
