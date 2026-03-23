#!/usr/bin/env python3
"""Backtester SmartBot V2 - Reproduction EXACTE du Pine Script avec SO Multiplicator Method"""

import numpy as np
import pandas as pd
import pandas_ta as ta
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List

@dataclass
class ParametresDCA_SmartBotV2:
    """Paramètres COMPLETS SmartBot V2 - correspondant au Pine Script"""
    
    # ═══════════════════════════════════════════════════════════
    # DEAL START CONDITIONS (DSC)
    # ═══════════════════════════════════════════════════════════
    dsc: str = "RSI + MFI"  # Options: "RSI", "Bollinger Band %", "MFI", "RSI + BB", "RSI + MFI", "BB + MFI", "All Three"
    dsc2_enabled: bool = False
    dsc2: str = "Bollinger Band %"  # Secondary condition (if enabled)
    
    # ═══════════════════════════════════════════════════════════
    # ORDER SETTINGS
    # ═══════════════════════════════════════════════════════════
    base_order: float = 1000.0  # Base Order Size ($)
    safe_order: float = 1500.0  # Safety Order Size ($)
    max_safe_order: int = 20  # Max Safety Orders
    safe_order_volume_scale: float = 1.5  # SO Volume Scale (multiplier)
    
    # ═══════════════════════════════════════════════════════════
    # PRICE DEVIATION SETTINGS
    # ═══════════════════════════════════════════════════════════
    pricedevbase: str = "ATR"  # Options: "From Base Order", "From Last Safety Order", "ATR"
    price_deviation: float = 4.0  # Price Deviation (%)
    deviation_scale: float = 1.0  # Price Deviation Scale
    
    # ATR Settings
    atr_length: int = 14
    atr_mult: float = 3.0  # Base ATR multiplier
    atr_mult_step_scale: float = 1.2  # ATR multiplier compounds with each SO
    
    # ═══════════════════════════════════════════════════════════
    # TAKE PROFIT SETTINGS
    # ═══════════════════════════════════════════════════════════
    take_profit: float = 1.5  # Take Profit (%)
    tp_type: str = "From Average Entry"  # Options: "From Average Entry", "From Base Order"
    
    # ═══════════════════════════════════════════════════════════
    # INDICATOR SETTINGS: RSI
    # ═══════════════════════════════════════════════════════════
    rsi_length: int = 2
    rsi_source: str = "close"
    dsc_rsi_threshold_low: int = 3  # Oversold
    dsc_rsi_threshold_high: int = 70  # Overbought (for shorts)
    
    # ═══════════════════════════════════════════════════════════
    # INDICATOR SETTINGS: BOLLINGER BANDS
    # ═══════════════════════════════════════════════════════════
    bb_length: int = 20
    bb_mult: float = 2.0
    bb_source: str = "close"
    bb_threshold_low: float = 0.0  # 0 = lower band
    bb_threshold_high: float = 1.0  # 1 = upper band
    
    # ═══════════════════════════════════════════════════════════
    # INDICATOR SETTINGS: MFI
    # ═══════════════════════════════════════════════════════════
    mfi_length: int = 14
    mfi_threshold_low: int = 30  # Oversold
    mfi_threshold_high: int = 80  # Overbought (for shorts)
    
    # ═══════════════════════════════════════════════════════════
    # SYSTEM SETTINGS
    # ═══════════════════════════════════════════════════════════
    initial_capital: float = 100000.0  # Starting capital ($)
    commission: float = 0.001  # 0.1%
    slippage_pourcent: float = 0.0


def calculer_indicateurs_smartbot(prix_df: pd.DataFrame, parametres: ParametresDCA_SmartBotV2) -> Dict[str, np.ndarray]:
    """Calcule TOUS les indicateurs nécessaires pour SmartBot V2"""
    close = prix_df['Close'].to_numpy()
    high = prix_df['High'].to_numpy()
    low = prix_df['Low'].to_numpy()
    volume = prix_df['Volume'].to_numpy() if 'Volume' in prix_df.columns else np.ones(len(close))
    n = len(close)
    
    indicators = {}
    
    # ═══════════════════════════════════════════════════════════
    # RSI Calculation
    # ═══════════════════════════════════════════════════════════
    try:
        rsi = ta.rsi(prix_df['Close'], length=parametres.rsi_length)
        indicators['rsi'] = rsi.fillna(50.0).to_numpy() if rsi is not None else np.full(n, 50.0)
    except Exception as e:
        print(f"⚠️ Erreur RSI: {e}")
        indicators['rsi'] = np.full(n, 50.0)
    
    # ═══════════════════════════════════════════════════════════
    # Bollinger Bands Percentage
    # ═══════════════════════════════════════════════════════════
    try:
        bb = ta.bbands(prix_df['Close'], length=parametres.bb_length, std=parametres.bb_mult)
        if bb is not None and not bb.empty:
            lower_col = [col for col in bb.columns if 'BBL' in col][0]
            upper_col = [col for col in bb.columns if 'BBU' in col][0]
            bb_lower = bb[lower_col].to_numpy()
            bb_upper = bb[upper_col].to_numpy()
            
            # BB% = (price - lower) / (upper - lower)
            # 0 = at lower band, 1 = at upper band
            bb_range = bb_upper - bb_lower
            bb_range[bb_range == 0] = 1.0  # Éviter division par zéro
            bb_percent = (close - bb_lower) / bb_range
            indicators['bb_percent'] = np.nan_to_num(bb_percent, nan=0.5)
        else:
            indicators['bb_percent'] = np.full(n, 0.5)
    except Exception as e:
        print(f"⚠️ Erreur BB%: {e}")
        indicators['bb_percent'] = np.full(n, 0.5)
    
    # ═══════════════════════════════════════════════════════════
    # MFI (Money Flow Index)
    # ═══════════════════════════════════════════════════════════
    try:
        mfi = ta.mfi(high=prix_df['High'], low=prix_df['Low'], close=prix_df['Close'], 
                     volume=prix_df['Volume'], length=parametres.mfi_length)
        indicators['mfi'] = mfi.fillna(50.0).to_numpy() if mfi is not None else np.full(n, 50.0)
    except Exception as e:
        print(f"⚠️ Erreur MFI: {e}")
        indicators['mfi'] = np.full(n, 50.0)
    
    # ═════════════════════════════════════════════════════════
    # ATR (Average True Range)
    # ═══════════════════════════════════════════════════════════
    try:
        atr = ta.atr(high=prix_df['High'], low=prix_df['Low'], close=prix_df['Close'], 
                     length=parametres.atr_length)
        indicators['atr'] = atr.fillna(0.0).to_numpy() if atr is not None else np.zeros(n)
    except Exception as e:
        print(f"⚠️ Erreur ATR: {e}")
        indicators['atr'] = np.zeros(n)
    
    return indicators


def evaluer_entry_signal(indicators: Dict[str, np.ndarray], t: int, parametres: ParametresDCA_SmartBotV2) -> bool:
    """Évalue le signal d'entrée selon la configuration DSC (Deal Start Condition)"""
    rsi = indicators['rsi'][t]
    bb_pct = indicators['bb_percent'][t]
    mfi = indicators['mfi'][t]
    
    # Individual signals
    rsi_signal = rsi < parametres.dsc_rsi_threshold_low
    bb_signal = bb_pct < parametres.bb_threshold_low
    mfi_signal = mfi < parametres.mfi_threshold_low
    
    # Primary signal based on DSC selection
    if parametres.dsc == "RSI":
        primary_signal = rsi_signal
    elif parametres.dsc == "Bollinger Band %":
        primary_signal = bb_signal
    elif parametres.dsc == "MFI":
        primary_signal = mfi_signal
    elif parametres.dsc == "RSI + BB":
        primary_signal = rsi_signal and bb_signal
    elif parametres.dsc == "RSI + MFI":
        primary_signal = rsi_signal and mfi_signal
    elif parametres.dsc == "BB + MFI":
        primary_signal = bb_signal and mfi_signal
    elif parametres.dsc == "All Three":
        primary_signal = rsi_signal and bb_signal and mfi_signal
    else:
        primary_signal = False
    
    # Secondary signal (if enabled)
    if parametres.dsc2_enabled:
        if parametres.dsc2 == "RSI":
            secondary_signal = rsi_signal
        elif parametres.dsc2 == "Bollinger Band %":
            secondary_signal = bb_signal
        elif parametres.dsc2 == "MFI":
            secondary_signal = mfi_signal
        else:
            secondary_signal = True
        
        return primary_signal and secondary_signal
    
    return primary_signal


def calcular_so_trigger_price(parametres: ParametresDCA_SmartBotV2, base_order_price: float, 
                               last_so_price: float, current_so_count: int, 
                               close_prev: float, atr: float) -> float:
    """
    Calcule le prix de déclenchement pour le prochain Safety Order
    Reproduit EXACTEMENT la logique Pine Script
    """
    if parametres.pricedevbase == "From Base Order":
        # Cumulative deviation from base order
        cum_dev = 0.0
        for i in range(current_so_count + 1):
            dev = parametres.price_deviation * (parametres.deviation_scale ** i)
            cum_dev += dev
        trigger_price = base_order_price * (1 - cum_dev / 100.0)
        
    elif parametres.pricedevbase == "From Last Safety Order":
        # Deviation from last SO (or base order if no SO yet)
        ref_price = base_order_price if current_so_count == 0 else last_so_price
        dev = parametres.price_deviation * (parametres.deviation_scale ** current_so_count)
        trigger_price = ref_price * (1 - dev / 100.0)
        
    elif parametres.pricedevbase == "ATR":
        # ATR-based with dynamic multiplier
        ref_price = base_order_price if current_so_count == 0 else last_so_price
        
        # Calculate ATR percentage
        atr_pct = (atr / close_prev) * 100.0 if close_prev > 0 else 0.0
        
        # Dynamic multiplier compounds with each SO
        dyn_mult = parametres.atr_mult * (parametres.atr_mult_step_scale ** current_so_count)
        
        # Final deviation
        deviation_pct = atr_pct * dyn_mult
        trigger_price = ref_price * (1 - deviation_pct / 100.0)
    else:
        trigger_price = 0.0
    
    return trigger_price


def calcular_so_size(parametres: ParametresDCA_SmartBotV2, so_number: int) -> float:
    """Calcule la taille du Safety Order avec scaling"""
    return parametres.safe_order * (parametres.safe_order_volume_scale ** so_number)


def backtest_smartbot_v2(prix: pd.DataFrame, parametres: ParametresDCA_SmartBotV2) -> Tuple[pd.DataFrame, pd.Series, Dict]:
    """
    Backtester SmartBot V2 - Reproduction EXACTE de la logique Pine Script
    avec SO Multiplicator Method
    """
    for c in ("Open", "High", "Low", "Close"):
        assert c in prix.columns, f"❌ Colonne manquante: {c}"
    
    # ═══════════════════════════════════════════════════════════
    # CALCUL DES INDICATEURS
    # ═══════════════════════════════════════════════════════════
    print("📊 Calcul des indicateurs...")
    indicators = calculer_indicateurs_smartbot(prix, parametres)
    
    close = prix["Close"].to_numpy(dtype=float)
    high = prix["High"].to_numpy(dtype=float)
    n = len(close)
    indice = prix.index
    
    # ═══════════════════════════════════════════════════════════
    # VARIABLES D'ÉTAT (comme Pine Script)
    # ═══════════════════════════════════════════════════════════
    in_trade = False
    base_order_price = None
    last_so_price = None
    avg_entry_price = None
    total_position_size = 0.0
    total_invested = 0.0
    current_so_count = 0
    entry_bar = -1
    last_close_bar = -1
    
    # Capital management
    capital_disponible = parametres.initial_capital
    skipped_trades = 0
    
    transactions = []
    pnl_realise = np.zeros(n)
    
    print(f"🚀 Début du backtest - {len(close)} barres")
    print(f"📋 Configuration: DSC='{parametres.dsc}', Price Deviation='{parametres.pricedevbase}'")
    print(f"💰 Capital Initial=${parametres.initial_capital:.2f}")
    print(f"💰 Base Order=${parametres.base_order}, SO=${parametres.safe_order}, Max SO={parametres.max_safe_order}")
    print("="*80)
    
    for t in range(1, n):  # Commence à 1 pour avoir close[t-1]
        price = close[t]
        
        # Évaluer le signal d'entrée
        entry_signal = evaluer_entry_signal(indicators, t, parametres)
        
        # ═══════════════════════════════════════════════════════════
        # LOGIQUE D'ENTRÉE (BASE ORDER)
        # ═══════════════════════════════════════════════════════════
        if not in_trade and t != last_close_bar and entry_signal:
            # Vérifier capital disponible
            if capital_disponible < parametres.base_order:
                skipped_trades += 1
                print(f"⚠️ [{indice[t].strftime('%Y-%m-%d')}] TRADE SKIPPED - Capital insuffisant (${capital_disponible:.2f} < ${parametres.base_order})")
            else:
                # OPEN NEW DEAL
                in_trade = True
                base_order_price = price
                last_so_price = price
                current_so_count = 0
                entry_bar = t
                
                # Calculate position
                qty = parametres.base_order / price
                total_position_size = qty
                total_invested = parametres.base_order
                avg_entry_price = price
                
                # Déduire du capital
                capital_disponible -= parametres.base_order
                
                print(f"📍 [{indice[t].strftime('%Y-%m-%d')}] BASE ORDER @ ${price:.2f} | Qty={qty:.6f} | Capital restant=${capital_disponible:.2f}")
        
        # ═══════════════════════════════════════════════════════════
        # LOGIQUE DE SORTIE (TAKE PROFIT)
        # ═══════════════════════════════════════════════════════════
        elif in_trade and t != entry_bar:
            # Calculate TP price
            if parametres.tp_type == "From Average Entry":
                tp_price = avg_entry_price * (1 + parametres.take_profit / 100.0)
            else:  # From Base Order
                tp_price = base_order_price * (1 + parametres.take_profit / 100.0)
            
            # Check TP on wick (high)
            if high[t] >= tp_price:
                # CLOSE DEAL
                exit_price = tp_price  # Assume filled at TP price
                
                # Calculate PnL
                gross_proceeds = exit_price * total_position_size
                total_fees = (total_invested + gross_proceeds) * parametres.commission
                pnl_net = gross_proceeds - total_invested - total_fees
                profit_pct = ((exit_price / avg_entry_price) - 1) * 100.0
                
                transactions.append({
                    "entry_time": indice[entry_bar],
                    "exit_time": indice[t],
                    "entry_price": base_order_price,
                    "avg_entry_price": avg_entry_price,
                    "exit_price": exit_price,
                    "reason": "TP",
                    "so_count": current_so_count,
                    "total_invested": total_invested,
                    "total_position_size": total_position_size,
                    "pnl": pnl_net,
                    "pnl_pct": profit_pct
                })
                
                pnl_realise[t] = pnl_net
                
                # Remettre le capital + PnL
                capital_disponible += total_invested + pnl_net
                
                print(f"✅ [{indice[t].strftime('%Y-%m-%d')}] TAKE PROFIT @ ${exit_price:.2f} | "
                      f"SOs={current_so_count} | PnL=${pnl_net:.2f} ({profit_pct:.2f}%) | Capital=${capital_disponible:.2f}")
                
                # Reset state
                in_trade = False
                last_close_bar = t
                base_order_price = None
                last_so_price = None
                avg_entry_price = None
                total_position_size = 0.0
                total_invested = 0.0
                current_so_count = 0
        
        # ═══════════════════════════════════════════════════════════
        # LOGIQUE SAFETY ORDERS
        # ═══════════════════════════════════════════════════════════
        if in_trade and current_so_count < parametres.max_safe_order:
            # Calculate SO trigger price
            so_trigger_price = calcular_so_trigger_price(
                parametres, base_order_price, last_so_price, current_so_count,
                close[t-1], indicators['atr'][t]
            )
            
            # Check conditions
            price_below_so = price <= so_trigger_price
            
            # SO trigger logic (from Pine Script):
            # - "From Base Order" mode: trigger on price alone
            # - Other modes: require both price AND entry signal
            if parametres.pricedevbase == "From Base Order":
                so_trigger = price_below_so
            else:
                so_trigger = price_below_so and entry_signal
            
            if so_trigger:
                # PLACE SAFETY ORDER
                so_size = calcular_so_size(parametres, current_so_count)
                
                # Vérifier capital disponible
                if capital_disponible < so_size:
                    print(f"⚠️ [{indice[t].strftime('%Y-%m-%d')}] SO SKIPPED - Capital insuffisant (${capital_disponible:.2f} < ${so_size:.2f})")
                    # Continue le trade sans ajouter le SO
                else:
                    so_qty = so_size / price
                    
                    # Update position
                    total_invested += so_size
                    total_position_size += so_qty
                    avg_entry_price = total_invested / total_position_size
                    last_so_price = price
                    current_so_count += 1
                    
                    # Déduire du capital
                    capital_disponible -= so_size
                    
                    print(f"🔻 [{indice[t].strftime('%Y-%m-%d')}] SAFETY ORDER #{current_so_count} @ ${price:.2f} | "
                          f"Size=${so_size:.2f} | Avg=${avg_entry_price:.2f} | Capital=${capital_disponible:.2f}")
    
    # ═══════════════════════════════════════════════════════════
    # SI POSITION OUVERTE À LA FIN, LA FERMER
    # ═══════════════════════════════════════════════════════════
    if in_trade:
        prix_final = close[-1]
        gross_proceeds = prix_final * total_position_size
        total_fees = (total_invested + gross_proceeds) * parametres.commission
        pnl_net = gross_proceeds - total_invested - total_fees
        profit_pct = ((prix_final / avg_entry_price) - 1) * 100.0
        
        transactions.append({
            "entry_time": indice[entry_bar],
            "exit_time": indice[-1],
            "entry_price": base_order_price,
            "avg_entry_price": avg_entry_price,
            "exit_price": prix_final,
            "reason": "END",
            "so_count": current_so_count,
            "total_invested": total_invested,
            "total_position_size": total_position_size,
            "pnl": pnl_net,
            "pnl_pct": profit_pct
        })
        
        pnl_realise[-1] = pnl_net
        
        # Remettre le capital + PnL
        capital_disponible += total_invested + pnl_net
        
        print(f"⚠️ [{indice[-1].strftime('%Y-%m-%d')}] POSITION FORCÉE @ ${prix_final:.2f} | "
              f"PnL=${pnl_net:.2f} ({profit_pct:.2f}%) | Capital final=${capital_disponible:.2f}")
    
    # ═══════════════════════════════════════════════════════════
    # CALCUL DES STATISTIQUES
    # ═══════════════════════════════════════════════════════════
    df_trades = pd.DataFrame(transactions)
    courbe_equite = pd.Series(pnl_realise, index=prix.index).cumsum()
    
    statistiques = {}
    if not df_trades.empty:
        winning_trades = df_trades[df_trades["pnl"] > 0]
        losing_trades = df_trades[df_trades["pnl"] <= 0]
        
        statistiques = {
            "total_trades": len(df_trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": float(len(winning_trades) / len(df_trades) * 100),
            "total_pnl": float(df_trades["pnl"].sum()),
            "avg_pnl_per_trade": float(df_trades["pnl"].mean()),
            "avg_win": float(winning_trades["pnl"].mean()) if len(winning_trades) > 0 else 0.0,
            "avg_loss": float(losing_trades["pnl"].mean()) if len(losing_trades) > 0 else 0.0,
            "largest_win": float(df_trades["pnl"].max()) if len(df_trades) > 0 else 0.0,
            "largest_loss": float(df_trades["pnl"].min()) if len(df_trades) > 0 else 0.0,
            "avg_so_per_trade": float(df_trades["so_count"].mean()),
            "max_so_used": int(df_trades["so_count"].max()) if len(df_trades) > 0 else 0,
            "total_invested_avg": float(df_trades["total_invested"].mean()),
            "max_drawdown": float((courbe_equite - courbe_equite.cummax()).min()) if len(courbe_equite) > 0 else 0.0,
            "initial_capital": float(parametres.initial_capital),
            "final_capital": float(capital_disponible),
            "capital_return_pct": float((capital_disponible - parametres.initial_capital) / parametres.initial_capital * 100),
            "skipped_trades": int(skipped_trades)
        }
    
    print("="*80)
    print("📈 RÉSULTATS DU BACKTEST")
    print("="*80)
    if statistiques:
        print(f"Capital initial:    ${statistiques['initial_capital']:.2f}")
        print(f"Capital final:      ${statistiques['final_capital']:.2f}")
        print(f"Return:             {statistiques['capital_return_pct']:.2f}%")
        print(f"-"*80)
        print(f"Trades totaux:      {statistiques['total_trades']}")
        print(f"Trades gagnants:    {statistiques['winning_trades']} ({statistiques['win_rate']:.1f}%)")
        print(f"Trades perdants:    {statistiques['losing_trades']}")
        print(f"Trades skipped:     {statistiques['skipped_trades']}")
        print(f"-"*80)
        print(f"PnL total:          ${statistiques['total_pnl']:.2f}")
        print(f"PnL moyen/trade:    ${statistiques['avg_pnl_per_trade']:.2f}")
        print(f"SO moyen/trade:     {statistiques['avg_so_per_trade']:.1f}")
        print(f"Max SO utilisé:     {statistiques['max_so_used']}")
        print(f"Max Drawdown:       ${statistiques['max_drawdown']:.2f}")
    print("="*80)
    
    return df_trades, courbe_equite, statistiques


if __name__ == "__main__":
    # Test du backtester SmartBot V2
    import yfinance as yf
    
    print("\n" + "="*80)
    print("🤖 SMARTBOT V2 BACKTESTER - SO MULTIPLICATOR METHOD")
    print("="*80 + "\n")
    
    # Téléchargement des données
    print("📥 Téléchargement des données BTC-USD...")
    data = yf.download("BTC-USD", start="2024-01-01", end="2025-01-01", interval="1d", progress=False)
    
    if len(data.columns) == 6:
        data.columns = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
        data = data.drop('Adj Close', axis=1)
    elif len(data.columns) == 5:
        data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    
    data = data.dropna()
    print(f"✅ {len(data)} barres téléchargées\n")
    
    # Configuration SmartBot V2 (paramètres du Pine Script)
    params = ParametresDCA_SmartBotV2(
        # DSC Configuration
        dsc="RSI + MFI",
        dsc2_enabled=False,
        
        # Order Settings
        base_order=1000.0,
        safe_order=1500.0,
        max_safe_order=20,
        safe_order_volume_scale=1.5,
        
        # Price Deviation
        pricedevbase="ATR",
        price_deviation=4.0,
        deviation_scale=1.0,
        
        # ATR Settings
        atr_length=14,
        atr_mult=3.0,
        atr_mult_step_scale=1.2,
        
        # Take Profit
        take_profit=1.5,
        tp_type="From Average Entry",
        
        # RSI Settings
        rsi_length=2,
        dsc_rsi_threshold_low=3,
        
        # MFI Settings
        mfi_length=14,
        mfi_threshold_low=30,
        
        # Bollinger Bands
        bb_length=20,
        bb_mult=2.0,
        bb_threshold_low=0.0
    )
    
    # Exécution du backtest
    trades, equity, stats = backtest_smartbot_v2(data, params)
    
    # Affichage des trades
    if not trades.empty:
        print("\n📋 DÉTAIL DES TRADES:")
        print("-"*80)
        for i, trade in trades.iterrows():
            entry_date = trade['entry_time'].strftime('%Y-%m-%d')
            exit_date = trade['exit_time'].strftime('%Y-%m-%d')
            pnl_color = "✅" if trade['pnl'] > 0 else "❌"
            print(f"Trade #{i+1:2d} | {entry_date} → {exit_date} | "
                  f"Entry: ${trade['entry_price']:8.2f} | Exit: ${trade['exit_price']:8.2f} | "
                  f"SOs: {trade['so_count']:2d} | {pnl_color} ${trade['pnl']:8.2f} ({trade['pnl_pct']:5.2f}%)")
    
    print("\n✨ Backtest terminé!")
