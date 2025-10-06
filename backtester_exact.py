#!/usr/bin/env python3
"""Backtester modifié avec ordre d'évaluation IDENTIQUE à dca_library_backtestingpy.py"""

import numpy as np
import pandas as pd
import pandas_ta as ta
from dataclasses import dataclass
from typing import Optional, Tuple, Dict

@dataclass
class ParametresDCA_Exact:
    """Paramètres EXACTS de dca_library_backtestingpy.py"""
    cote: str = "LONG"
    quantite_base: float = 1.0
    quantite_so_base: float = 1.0
    nb_max_so: int = 4  # EXACTEMENT comme dca_library (so_max = 4)
    volume_scale: float = 1.0  # so_volume_scale = 1
    deviation_premier_so: float = 0.0021  # so_step = 0.0021
    step_scale: float = 1.0  # so_step_scale = 1
    take_profit_pourcent: float = 0.01
    stop_loss_pourcent: Optional[float] = None
    commission: float = 0.002
    slippage_pourcent: float = 0.0
    autoriser_chevauchement: bool = False
    
    # Paramètres IDENTIQUES à dca_library_backtestingpy.py
    rsi_length: int = 14
    rsi_entry: int = 30
    rsi_exit: int = 75
    bb_length: int = 20
    bb_std: float = 3.0  # bb_std = 3 dans dca_library
    bbp_trigger: float = 0.2
    tp_minimum: float = 0.01  # min_tp = 0.01


def calculer_indicateurs_exact(prix_df: pd.DataFrame, parametres: ParametresDCA_Exact) -> Tuple[np.ndarray, np.ndarray]:
    """Calcule RSI et BBP EXACTEMENT comme dca_library_backtestingpy.py"""
    close = prix_df['Close']
    
    # Calcul RSI identique à dca_library
    try:
        rsi = ta.rsi(close, length=parametres.rsi_length)
        if rsi is None:
            rsi_values = np.full(len(close), 50.0)
        else:
            rsi_values = rsi.fillna(0).to_numpy()  # fillna(0) comme dca_library
    except Exception as e:
        print(f"Erreur RSI: {e}")
        rsi_values = np.full(len(close), 50.0)
    
    # Calcul BBP identique à dca_library
    try:
        bb = ta.bbands(close, length=parametres.bb_length, std=parametres.bb_std)
        
        if bb is None or bb.empty:
            bbp_values = np.full(len(close), 0.5)
        else:
            # Mêmes noms de colonnes que dca_library
            lower_col = [col for col in bb.columns if 'BBL' in col][0]
            upper_col = [col for col in bb.columns if 'BBU' in col][0]
            
            bbp = (close - bb[lower_col]) / (bb[upper_col] - bb[lower_col])
            bbp_values = bbp.fillna(0).to_numpy()  # fillna(0) comme dca_library
    except Exception as e:
        print(f"Erreur BBP: {e}")
        bbp_values = np.full(len(close), 0.5)
    
    return rsi_values, bbp_values


def backtest_dca_exact(prix: pd.DataFrame, signal_entree: pd.Series, parametres: ParametresDCA_Exact) -> Tuple[pd.DataFrame, pd.Series, Dict]:
    """
    Backtester reproduisant EXACTEMENT l'ordre d'évaluation de dca_library_backtestingpy.py
    """
    for c in ("Open", "High", "Low", "Close"):
        assert c in prix.columns, f"la colonne {c} n'existe pas dans les prix"
    assert prix.index.equals(signal_entree.index), "les séries 'prix' et 'signal_entree' doivent être alignées"

    # Calcul des indicateurs identique à dca_library
    rsi_values, bbp_values = calculer_indicateurs_exact(prix, parametres)
    
    close = prix["Close"].to_numpy(dtype=float)
    n = len(close)
    indice = prix.index
    
    # Timestamps pour période de trading (comme dca_library)
    timestamps = indice.tz_localize(None) if indice.tz is not None else indice
    start_time = pd.Timestamp("2024-01-01 00:00:00")
    end_time = pd.Timestamp("2030-01-01 00:00:00")

    # Variables d'état EXACTEMENT comme dca_library
    position = False  # position active
    entry_price = None
    total_cost = 0.0
    total_qty = 0.0
    safety_orders = []
    
    transactions = []
    pnl_realise = np.zeros(n)
    
    for t in range(n):
        # Valeurs courantes (comme dca_library.next())
        price = close[t]
        rsi = rsi_values[t]
        bbp = bbp_values[t]
        timestamp = timestamps[t]
        
        # Période définie pour trader (comme dca_library)
        if timestamp < start_time or timestamp > end_time:
            continue
        
        # LOGIQUE D'ENTRÉE (EXACTEMENT comme dca_library.next())
        if not position:
            if rsi < parametres.rsi_entry:  # direction == 'long' et rsi < rsi_entry
                # Entrée en position
                position = True
                entry_price = price
                total_cost = price
                total_qty = 1.0
                safety_orders = [price]
                print(f"[LONG] Entrée à {price:.2f}")
                
        # GESTION POSITION EN COURS (EXACTEMENT comme dca_library.next())
        elif position:
            avg_price = total_cost / total_qty
            pnl = (price - avg_price) / avg_price  # position.is_long = True
            
            # CONDITIONS DE SORTIE (EXACTEMENT comme dca_library)
            # Condition: (rsi > rsi_exit and pnl >= min_tp)
            if rsi > parametres.rsi_exit and pnl >= parametres.tp_minimum:
                # Sortie de position
                position = False
                
                # Calcul PnL final
                revenus_bruts = price * total_qty
                frais_totaux = (total_cost + revenus_bruts) * parametres.commission
                pnl_net = revenus_bruts - total_cost - frais_totaux
                
                # Enregistrer le trade (ajustement pour correspondre à backtesting.py)
                entry_idx = max(0, t - len(safety_orders))  # Index d'entrée ajusté
                transactions.append({
                    "entry_time": indice[entry_idx],
                    "exit_time": indice[t],
                    "entry_price": entry_price,
                    "exit_price": price,
                    "reason": "TP",
                    "fills_count": len(safety_orders),
                    "filled_qty_total": total_qty,
                    "wap": avg_price,
                    "pnl": pnl_net
                })
                
                pnl_realise[t] += pnl_net
                
                print(f"Sortie à {price:.2f} | PnL: {pnl * 100:.2f}%")
                
                # Reset variables
                entry_price = None
                total_cost = 0.0
                total_qty = 0.0
                safety_orders = []
                
            # SAFETY ORDERS (EXACTEMENT comme dca_library)
            elif len(safety_orders) < parametres.nb_max_so + 1:  # +1 car on inclut l'entrée initiale
                last_so_price = safety_orders[-1]
                step_scaled = parametres.deviation_premier_so * (parametres.step_scale ** len(safety_orders))
                price_deviation = abs((last_so_price - price) / last_so_price)
                
                # Conditions EXACTES de dca_library
                bbp_ok = bbp < parametres.bbp_trigger  # position longue
                deviation_ok = price_deviation >= step_scaled
                
                if deviation_ok and bbp_ok:
                    qty = parametres.quantite_base * (parametres.volume_scale ** len(safety_orders))
                    total_cost += price * qty
                    total_qty += qty
                    safety_orders.append(price)
                    
                    print(f"Safety Order #{len(safety_orders)} à {price:.2f}")
    
    # Si position ouverte à la fin, la fermer
    if position:
        prix_final = close[-1]
        avg_price = total_cost / total_qty
        revenus_bruts = prix_final * total_qty
        frais_totaux = (total_cost + revenus_bruts) * parametres.commission
        pnl_net = revenus_bruts - total_cost - frais_totaux
        
        transactions.append({
            "entry_time": indice[-len(safety_orders)] if len(safety_orders) > 1 else indice[-2],
            "exit_time": indice[-1],
            "entry_price": entry_price,
            "exit_price": prix_final,
            "reason": "END",
            "fills_count": len(safety_orders),
            "filled_qty_total": total_qty,
            "wap": avg_price,
            "pnl": pnl_net
        })
        
        pnl_realise[-1] += pnl_net

    df_trades = pd.DataFrame(transactions)
    courbe_equite = pd.Series(pnl_realise, index=prix.index).cumsum()
    statistiques = {}
    if not df_trades.empty:
        statistiques = {
            "trades": len(df_trades),
            "win_rate": float((df_trades["pnl"] > 0).mean()),
            "avg_pnl": float(df_trades["pnl"].mean()),
            "total_pnl": float(df_trades["pnl"].sum()),
            "max_drawdown": float((courbe_equite - courbe_equite.cummax()).min())
        }
    return df_trades, courbe_equite, statistiques


if __name__ == "__main__":
    # Test de validation
    import yfinance as yf
    
    print("=== TEST BACKTESTER EXACT ===")
    
    # Données identiques
    data = yf.download("BTC-USD", start="2023-09-27", end="2025-09-25", interval="1d")
    data.to_csv("btc_data_temp.csv")
    df = pd.read_csv("btc_data_temp.csv", index_col=0, skiprows=2, parse_dates=True)
    
    if len(df.columns) == 6:
        df.columns = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
        df = df.drop('Adj Close', axis=1)
    elif len(df.columns) == 5:
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    
    df = df.dropna()
    
    # Paramètres EXACTS
    params_exact = ParametresDCA_Exact()
    signal_entree = pd.Series(True, index=df.index)
    
    # Test
    trades, equity, stats = backtest_dca_exact(df, signal_entree, params_exact)
    
    print(f"Nombre de trades: {len(trades)}")
    if not trades.empty:
        for i, trade in trades.iterrows():
            print(f"Trade {i+1}: {trade['entry_time'].strftime('%Y-%m-%d')} à {trade['entry_price']:.2f} → {trade['exit_time'].strftime('%Y-%m-%d')} à {trade['exit_price']:.2f}")
    
    # Nettoyage
    import os
    if os.path.exists("btc_data_temp.csv"):
        os.remove("btc_data_temp.csv")
