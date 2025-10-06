# core/backtester_adapter.py
from __future__ import annotations
from typing import Dict, Any, Tuple
import pandas as pd
from datafeed_tester.core.types import BaseStrategy

# On tente d'importer ton backtester; adapte le nom si besoin.
try:
    from backtester import ParametresDCA, backtest_dca_vectorise
except ImportError:
    try:
        from backtester import ParametresDCA, backtest_dca_vectorise
    except ImportError as e:
        raise ImportError(
            "Impossible d’importer ParametresDCA/backtest_dca_vectorise. "
            "Place ton code DCA dans 'my_backtester.py' ou 'backtester.py' à la racine."
        ) from e

def _make_params_dca(params: Dict[str, Any]) -> ParametresDCA:
    quantite_base = float(params.get("quantite_base", 1.0))
    # Si initial_capital est fourni, l'utiliser comme quantite_base
    if "initial_capital" in params:
        try:
            quantite_base = float(params["initial_capital"])
        except Exception:
            pass
    return ParametresDCA(
        cote=str(params.get("cote", "LONG")).upper(),
        quantite_base=quantite_base,
        quantite_so_base=float(params.get("quantite_so_base", 1.0)),
        nb_max_so=int(params.get("nb_max_so", 5)),
        volume_scale=float(params.get("volume_scale", 1.2)),
        deviation_premier_so=float(params.get("deviation_premier_so", 0.02)),
        step_scale=float(params.get("step_scale", 1.2)),
        take_profit_pourcent=float(params.get("take_profit_pourcent", 0.01)),
        stop_loss_pourcent=(
            None if params.get("stop_loss_pourcent", None) is None
            else float(params["stop_loss_pourcent"])
        ),
        commission=float(params.get("commission", 0.0005)),
        slippage_pourcent=float(params.get("slippage_pourcent", 0.0)),
        autoriser_chevauchement=bool(params.get("autoriser_chevauchement", False)),
    )

def _signals_to_entry_bool(signals: pd.DataFrame) -> pd.Series:
    if "size" in signals.columns:
        return (signals["size"].fillna(0) > 0).astype(bool)
    side = signals.get("side", pd.Series(index=signals.index, dtype=object)).astype(str).str.lower()
    return (side == "long")

def run_backtest_with_strategy(   # ←←← Assure-toi que le nom est EXACT
    df: pd.DataFrame,
    strategy: BaseStrategy,
    strategy_params: Dict[str, Any]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    # 1) Signaux de la stratégie
    signals = strategy.generate_signals(df, strategy_params)
    if not isinstance(signals, pd.DataFrame) or signals.empty:
        equity_df = pd.DataFrame({"date": df["date"].values, "equity": [0.0] * len(df)})
        return equity_df, {"bars": len(df), "final_equity": 0.0, "trades_df": pd.DataFrame()}

    # 2) Paramètres DCA
    p = _make_params_dca(strategy_params)

    # 3) Serie de prix & signal d’entrée booléen
    prix = df["close"].astype(float)
    signal_entree = _signals_to_entry_bool(signals).reindex(prix.index).fillna(False).astype(bool)

    # 4) Lancer TON moteur
    trades_df, equity_series, stats = backtest_dca_vectorise(prix, signal_entree, p)

    # 5) Normaliser la sortie
    equity_df = pd.DataFrame({"date": df["date"].values, "equity": equity_series.values})
    stats = dict(stats) if isinstance(stats, dict) else {}
    stats["bars"] = int(len(df))
    stats["final_equity"] = float(equity_df["equity"].iloc[-1]) if len(equity_df) else 0.0
    stats["trades_df"] = trades_df if isinstance(trades_df, pd.DataFrame) else pd.DataFrame()
    return equity_df, stats
