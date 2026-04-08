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
    close_last_trade: bool = False  # Si False, garde le dernier trade ouvert à la fin


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
    current_trade_so_list = []  # Liste des SO pour le trade en cours
    
    # Capital management
    capital_disponible = parametres.initial_capital
    skipped_trades = 0
    
    # Tracking pour calcul du drawdown basé sur capital
    capital_history = [parametres.initial_capital]  # Historique du capital à chaque événement
    
    # Equity curve: capital disponible + valeur des positions ouvertes à chaque barre
    equity_at_bar = np.full(n, parametres.initial_capital, dtype=float)
    
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
                current_trade_so_list = []  # Reset la liste des SO pour ce nouveau trade
                
                # Calculate position
                qty = parametres.base_order / price
                total_position_size = qty
                total_invested = parametres.base_order
                avg_entry_price = price
                
                # Déduire du capital
                capital_disponible -= parametres.base_order
                capital_history.append(capital_disponible)  # Enregistrer la baisse de capital
                
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
                
                # Calculer le P&L de chaque position individuelle (comme TradingView)
                individual_positions = []
                
                # 1. Base Order P&L
                bo_qty = parametres.base_order / base_order_price
                bo_proceeds = exit_price * bo_qty
                bo_fees = (parametres.base_order + bo_proceeds) * parametres.commission
                bo_pnl = bo_proceeds - parametres.base_order - bo_fees
                bo_pnl_pct = ((exit_price / base_order_price) - 1) * 100.0
                
                individual_positions.append({
                    "type": "BO_0",
                    "entry_time": indice[entry_bar],
                    "entry_price": base_order_price,
                    "size_usd": parametres.base_order,
                    "qty": bo_qty,
                    "exit_price": exit_price,
                    "pnl": bo_pnl,
                    "pnl_pct": bo_pnl_pct
                })
                
                # 2. Chaque Safety Order P&L
                for so_info in current_trade_so_list:
                    so_size = so_info['size']
                    so_price = so_info['price']
                    so_qty = so_size / so_price
                    so_proceeds = exit_price * so_qty
                    so_fees = (so_size + so_proceeds) * parametres.commission
                    so_pnl = so_proceeds - so_size - so_fees
                    so_pnl_pct = ((exit_price / so_price) - 1) * 100.0
                    
                    individual_positions.append({
                        "type": f"SO_{so_info['number']}",
                        "entry_time": so_info['time'],
                        "entry_price": so_price,
                        "size_usd": so_size,
                        "qty": so_qty,
                        "exit_price": exit_price,
                        "pnl": so_pnl,
                        "pnl_pct": so_pnl_pct
                    })
                
                transactions.append({
                    "entry_time": indice[entry_bar],
                    "exit_time": indice[t],
                    "entry_price": base_order_price,
                    "avg_entry_price": avg_entry_price,
                    "exit_price": exit_price,
                    "reason": "TP",
                    "so_count": current_so_count,
                    "so_times": [so['time'] for so in current_trade_so_list],
                    "so_prices": [so['price'] for so in current_trade_so_list],
                    "total_invested": total_invested,
                    "total_position_size": total_position_size,
                    "pnl": pnl_net,
                    "pnl_pct": profit_pct,
                    "individual_positions": individual_positions
                })
                
                pnl_realise[t] = pnl_net
                
                # Remettre le capital + PnL
                capital_disponible += total_invested + pnl_net
                capital_history.append(capital_disponible)  # Enregistrer le retour de capital
                
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
                    
                    # Enregistrer le SO dans la liste
                    current_trade_so_list.append({
                        'time': indice[t],
                        'price': price,
                        'size': so_size,
                        'number': current_so_count
                    })
                    
                    # Déduire du capital
                    capital_disponible -= so_size
                    capital_history.append(capital_disponible)  # Enregistrer la baisse de capital (SO = drawdown)
                    
                    print(f"🔻 [{indice[t].strftime('%Y-%m-%d')}] SAFETY ORDER #{current_so_count} @ ${price:.2f} | "
                          f"Size=${so_size:.2f} | Avg=${avg_entry_price:.2f} | Capital=${capital_disponible:.2f}")
        
        # ═══════════════════════════════════════════════════════════
        # MISE À JOUR DE L'EQUITY À CETTE BARRE
        # ═══════════════════════════════════════════════════════════
        if in_trade:
            # Equity = capital disponible + valeur des positions ouvertes
            valeur_position = total_position_size * price
            equity_at_bar[t] = capital_disponible + valeur_position
        else:
            # Pas de position, equity = capital disponible
            equity_at_bar[t] = capital_disponible
    
    # ═══════════════════════════════════════════════════════════
    # SI POSITION OUVERTE À LA FIN
    # ═══════════════════════════════════════════════════════════
    open_trades_at_end = 0
    if in_trade:
        if parametres.close_last_trade:
            # Fermer le trade à la fin du test
            prix_final = close[-1]
            gross_proceeds = prix_final * total_position_size
            total_fees = (total_invested + gross_proceeds) * parametres.commission
            pnl_net = gross_proceeds - total_invested - total_fees
            profit_pct = ((prix_final / avg_entry_price) - 1) * 100.0
            
            # Calculer le P&L de chaque position individuelle
            individual_positions = []
            
            # Base Order
            bo_qty = parametres.base_order / base_order_price
            bo_proceeds = prix_final * bo_qty
            bo_fees = (parametres.base_order + bo_proceeds) * parametres.commission
            bo_pnl = bo_proceeds - parametres.base_order - bo_fees
            bo_pnl_pct = ((prix_final / base_order_price) - 1) * 100.0
            
            individual_positions.append({
                "type": "BO_0",
                "entry_time": indice[entry_bar],
                "entry_price": base_order_price,
                "size_usd": parametres.base_order,
                "qty": bo_qty,
                "exit_price": prix_final,
                "pnl": bo_pnl,
                "pnl_pct": bo_pnl_pct
            })
            
            # Chaque Safety Order
            for so_info in current_trade_so_list:
                so_size = so_info['size']
                so_price = so_info['price']
                so_qty = so_size / so_price
                so_proceeds = prix_final * so_qty
                so_fees = (so_size + so_proceeds) * parametres.commission
                so_pnl = so_proceeds - so_size - so_fees
                so_pnl_pct = ((prix_final / so_price) - 1) * 100.0
                
                individual_positions.append({
                    "type": f"SO_{so_info['number']}",
                    "entry_time": so_info['time'],
                    "entry_price": so_price,
                    "size_usd": so_size,
                    "qty": so_qty,
                    "exit_price": prix_final,
                    "pnl": so_pnl,
                    "pnl_pct": so_pnl_pct
                })
            
            transactions.append({
                "entry_time": indice[entry_bar],
                "exit_time": indice[-1],
                "entry_price": base_order_price,
                "avg_entry_price": avg_entry_price,
                "exit_price": prix_final,
                "reason": "END",
                "so_count": current_so_count,
                "so_times": [so['time'] for so in current_trade_so_list],
                "so_prices": [so['price'] for so in current_trade_so_list],
                "total_invested": total_invested,
                "total_position_size": total_position_size,
                "pnl": pnl_net,
                "pnl_pct": profit_pct,
                "individual_positions": individual_positions
            })
            
            pnl_realise[-1] = pnl_net
            
            # Remettre le capital + PnL
            capital_disponible += total_invested + pnl_net
            equity_at_bar[-1] = capital_disponible  # Mise à jour de l'equity finale
            
            print(f"⚠️ [{indice[-1].strftime('%Y-%m-%d')}] POSITION FORCÉE @ ${prix_final:.2f} | "
                  f"PnL=${pnl_net:.2f} ({profit_pct:.2f}%) | Capital final=${capital_disponible:.2f}")
        else:
            # Garder le trade ouvert
            open_trades_at_end = 1
            print(f"📌 [{indice[-1].strftime('%Y-%m-%d')}] TRADE OUVERT À LA FIN | "
                  f"Entry=${base_order_price:.2f} | Current=${close[-1]:.2f} | "
                  f"Avg=${avg_entry_price:.2f} | SOs={current_so_count} | "
                  f"Invested=${total_invested:.2f}")
    
    # ═══════════════════════════════════════════════════════════
    # CALCUL DES STATISTIQUES
    # ═══════════════════════════════════════════════════════════
    df_trades = pd.DataFrame(transactions)
    # Equity curve basée sur la valeur réelle du portefeuille (capital + positions)
    courbe_equite = pd.Series(equity_at_bar, index=prix.index)
    
    # Calcul du drawdown basé sur l'évolution réelle du capital
    capital_array = np.array(capital_history)
    peak_capital = np.maximum.accumulate(capital_array)
    drawdowns = capital_array - peak_capital
    max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
    max_drawdown_pct = (max_drawdown / parametres.initial_capital * 100) if parametres.initial_capital > 0 else 0.0
    
    statistiques = {}
    if not df_trades.empty:
        winning_trades = df_trades[df_trades["pnl"] > 0]
        losing_trades = df_trades[df_trades["pnl"] <= 0]
        
        # Compter le nombre total d'ordres (BO + tous les SO)
        total_orders = len(df_trades)  # Nombre de deals
        total_so_placed = int(df_trades["so_count"].sum()) if "so_count" in df_trades.columns else 0
        total_orders_including_so = total_orders + total_so_placed
        
        # NOUVEAU: Calcul Win Rate à la TradingView
        # Compter les positions individuelles gagnantes vs perdantes
        total_individual_positions = 0
        winning_individual_positions = 0
        
        for _, trade in df_trades.iterrows():
            if "individual_positions" in trade and trade["individual_positions"]:
                for pos in trade["individual_positions"]:
                    total_individual_positions += 1
                    if pos["pnl"] > 0:
                        winning_individual_positions += 1
        
        # Win Rate TradingView = positions individuelles gagnantes / total positions individuelles
        win_rate_tradingview = float(winning_individual_positions / total_individual_positions * 100) if total_individual_positions > 0 else 0.0
        
        # Ancien win rate (deals complets)
        win_rate_deals = float(len(winning_trades) / len(df_trades) * 100) if len(df_trades) > 0 else 0.0
        
        statistiques = {
            "total_trades": len(df_trades),
            "total_orders_placed": total_orders_including_so,  # BO + tous les SO
            "total_so_placed": total_so_placed,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "total_individual_positions": total_individual_positions,
            "winning_individual_positions": winning_individual_positions,
            "win_rate_tradingview": win_rate_tradingview,  # Win rate comme TradingView
            "win_rate_deals": win_rate_deals,  # Win rate des deals complets
            "total_pnl": float(df_trades["pnl"].sum()),
            "avg_pnl_per_trade": float(df_trades["pnl"].mean()),
            "avg_win": float(winning_trades["pnl"].mean()) if len(winning_trades) > 0 else 0.0,
            "avg_loss": float(losing_trades["pnl"].mean()) if len(losing_trades) > 0 else 0.0,
            "largest_win": float(df_trades["pnl"].max()) if len(df_trades) > 0 else 0.0,
            "largest_loss": float(df_trades["pnl"].min()) if len(df_trades) > 0 else 0.0,
            "avg_so_per_trade": float(df_trades["so_count"].mean()),
            "max_so_used": int(df_trades["so_count"].max()) if len(df_trades) > 0 else 0,
            "total_invested_avg": float(df_trades["total_invested"].mean()),
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "initial_capital": float(parametres.initial_capital),
            "final_capital": float(capital_disponible),
            "capital_return_pct": float((capital_disponible - parametres.initial_capital) / parametres.initial_capital * 100),
            "skipped_trades": int(skipped_trades),
            "open_trades_at_end": open_trades_at_end
        }
    else:
        statistiques = {
            "open_trades_at_end": open_trades_at_end
        }
    
    print("="*80)
    print("📈 RÉSULTATS DU BACKTEST")
    print("="*80)
    if statistiques and "total_trades" in statistiques:
        print(f"Capital initial:    ${statistiques['initial_capital']:.2f}")
        print(f"Capital final:      ${statistiques['final_capital']:.2f}")
        print(f"Return:             {statistiques['capital_return_pct']:.2f}%")
        print(f"-"*80)
        print(f"Deals totaux:       {statistiques['total_trades']}")
        print(f"Ordres totaux:      {statistiques['total_orders_placed']} (BO + SO)")
        print(f"Positions totales:  {statistiques['total_individual_positions']} (comptage TradingView)")
        print(f"Positions WIN:      {statistiques['winning_individual_positions']}")
        print(f"Win Rate (TV):      {statistiques['win_rate_tradingview']:.2f}% (comme TradingView)")
        print(f"Win Rate (Deals):   {statistiques['win_rate_deals']:.2f}% (deals complets)")
        print(f"Deals skipped:      {statistiques['skipped_trades']}")
        if statistiques.get('open_trades_at_end', 0) > 0:
            print(f"⚠️ Trades ouverts:  {statistiques['open_trades_at_end']}")
        print(f"-"*80)
        print(f"PnL total:          ${statistiques['total_pnl']:.2f}")
        print(f"PnL moyen/deal:     ${statistiques['avg_pnl_per_trade']:.2f}")
        print(f"SO moyen/deal:      {statistiques['avg_so_per_trade']:.1f}")
        print(f"SO totaux placés:   {statistiques['total_so_placed']}")
        print(f"Max SO utilisé:     {statistiques['max_so_used']}")
        print(f"Max Drawdown:       ${statistiques['max_drawdown']:.2f} ({statistiques['max_drawdown_pct']:.2f}%)")
    print("="*80)
    
    return df_trades, courbe_equite, statistiques


def print_tradingview_style_report(df_trades: pd.DataFrame):
    """
    Affiche un rapport détaillé comme TradingView avec chaque position individuelle
    """
    if df_trades.empty:
        print("Aucun trade à afficher.")
        return
    
    print("\n" + "="*120)
    print("📊 DÉTAIL DES TRADES (Style TradingView)")
    print("="*120)
    
    trade_number = 0
    for idx, trade in df_trades.iterrows():
        if "individual_positions" not in trade or not trade["individual_positions"]:
            continue
        
        positions = trade["individual_positions"]
        
        # Afficher chaque position individuelle
        for pos in positions:
            trade_number += 1
            
            print(f"\n{'─'*120}")
            print(f"Trade #{trade_number} - {pos['type']}")
            print(f"{'─'*120}")
            print(f"  Entry:        {pos['entry_time'].strftime('%Y-%m-%d %H:%M')} @ ${pos['entry_price']:.2f}")
            print(f"  Exit:         {trade['exit_time'].strftime('%Y-%m-%d %H:%M')} @ ${pos['exit_price']:.2f}")
            print(f"  Size (USD):   ${pos['size_usd']:.2f}")
            print(f"  Size (Qty):   {pos['qty']:.8f}")
            
            # Afficher le P&L avec couleur
            pnl_symbol = "✅" if pos['pnl'] > 0 else "❌"
            print(f"  Net P&L:      {pnl_symbol} ${pos['pnl']:.2f} ({pos['pnl_pct']:+.2f}%)")
        
        # Résumé du deal complet
        print(f"\n{'─'*120}")
        print(f"📌 DEAL SUMMARY:")
        print(f"  Total Invested:  ${trade['total_invested']:.2f}")
        print(f"  Avg Entry:       ${trade['avg_entry_price']:.2f}")
        print(f"  Exit Price:      ${trade['exit_price']:.2f}")
        print(f"  SO Count:        {trade['so_count']}")
        deal_symbol = "✅" if trade['pnl'] > 0 else "❌"
        print(f"  Deal P&L:        {deal_symbol} ${trade['pnl']:.2f} ({trade['pnl_pct']:+.2f}%)")
        print(f"{'─'*120}")
    
    print("\n" + "="*120)
    print(f"Total Trades Displayed: {trade_number}")
    print("="*120 + "\n")


def generate_tradingview_html_table(df_trades: pd.DataFrame) -> str:
    """
    Génère un tableau HTML style TradingView avec chaque position individuelle
    """
    if df_trades.empty:
        return "<p>Aucun trade à afficher.</p>"
    
    html_rows = []
    trade_number = 0
    cumulative_pnl = 0.0
    
    for idx, trade in df_trades.iterrows():
        if "individual_positions" not in trade or not trade["individual_positions"]:
            continue
        
        positions = trade["individual_positions"]
        
        for pos in positions:
            trade_number += 1
            cumulative_pnl += pos['pnl']
            
            # Couleur selon le P&L
            pnl_class = "positive" if pos['pnl'] > 0 else "negative"
            
            # Ligne Entry
            entry_row = f"""
                <tr>
                    <td rowspan="2" class="trade-number">{trade_number}</td>
                    <td class="entry">Entry long</td>
                    <td>{pos['entry_time'].strftime('%Y-%m-%d %H:%M')}</td>
                    <td>{pos['type']}</td>
                    <td>${pos['entry_price']:.2f}</td>
                    <td>{pos['qty']:.8f}</td>
                    <td>${pos['size_usd']:.2f}</td>
                    <td rowspan="2" class="{pnl_class}">${pos['pnl']:.2f}</td>
                    <td rowspan="2" class="{pnl_class}">{pos['pnl_pct']:+.2f}%</td>
                    <td rowspan="2">${cumulative_pnl:.2f}</td>
                </tr>
            """
            
            # Ligne Exit
            exit_row = f"""
                <tr>
                    <td class="exit">Exit long</td>
                    <td>{trade['exit_time'].strftime('%Y-%m-%d %H:%M')}</td>
                    <td>TP @ {trade.get('tp_pct', 1.5):.1f}%</td>
                    <td>${pos['exit_price']:.2f}</td>
                    <td>{pos['qty']:.8f}</td>
                    <td>${pos['qty'] * pos['exit_price']:.2f}</td>
                </tr>
            """
            
            html_rows.append(entry_row + exit_row)
    
    table_html = f"""
    <style>
        .trades-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            font-size: 13px;
            background: #1a1d23;
            border-radius: 8px;
            overflow: hidden;
        }}
        .trades-table th {{
            background: #2d333b;
            color: #adbac7;
            padding: 12px 8px;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #444c56;
            position: sticky;
            top: 0;
        }}
        .trades-table td {{
            padding: 8px;
            border-bottom: 1px solid #2d333b;
            color: #cdd9e5;
        }}
        .trades-table tr:hover {{
            background: #22272e;
        }}
        .trade-number {{
            font-weight: bold;
            color: #58a6ff;
            text-align: center;
        }}
        .entry {{
            color: #7ee787;
        }}
        .exit {{
            color: #f85149;
        }}
        .positive {{
            color: #3fb950 !important;
            font-weight: bold;
        }}
        .negative {{
            color: #f85149 !important;
            font-weight: bold;
        }}
        .table-container {{
            max-height: 600px;
            overflow-y: auto;
            border-radius: 8px;
            border: 1px solid #2d333b;
        }}
    </style>
    
    <div class="table-container">
        <table class="trades-table">
            <thead>
                <tr>
                    <th>Trade #</th>
                    <th>Type</th>
                    <th>Date/Time</th>
                    <th>Signal</th>
                    <th>Price USD</th>
                    <th>Size (qty)</th>
                    <th>Size (value)</th>
                    <th>Net P&L USD</th>
                    <th>Net P&L %</th>
                    <th>Cumulative P&L</th>
                </tr>
            </thead>
            <tbody>
                {''.join(html_rows)}
            </tbody>
        </table>
    </div>
    
    <p style="margin-top: 15px; color: #7d8590; font-size: 12px;">
        📊 Total trades: {trade_number} | Cumulative P&L: <span style="color: {'#3fb950' if cumulative_pnl > 0 else '#f85149'}; font-weight: bold;">${cumulative_pnl:.2f}</span>
    </p>
    """
    
    return table_html


def export_tradingview_csv(df_trades: pd.DataFrame, filename: str = "backtest_tradingview.csv"):
    """
    Export les trades au format CSV comme TradingView
    """
    if df_trades.empty:
        print("Aucun trade à exporter.")
        return
    
    rows = []
    trade_number = 0
    
    for idx, trade in df_trades.iterrows():
        if "individual_positions" not in trade or not trade["individual_positions"]:
            continue
        
        positions = trade["individual_positions"]
        
        for pos in positions:
            trade_number += 1
            
            # Ligne Exit
            rows.append({
                "Trade #": trade_number,
                "Type": "Exit long",
                "Date and time": trade['exit_time'].strftime('%Y-%m-%d %H:%M'),
                "Signal": f"TP @ {trade['pnl_pct']:.1f}%",
                "Price USD": pos['exit_price'],
                "Size (qty)": pos['qty'],
                "Size (value)": pos['size_usd'],
                "Net P&L USD": pos['pnl'],
                "Net P&L %": pos['pnl_pct'],
            })
            
            # Ligne Entry
            rows.append({
                "Trade #": trade_number,
                "Type": "Entry long",
                "Date and time": pos['entry_time'].strftime('%Y-%m-%d %H:%M'),
                "Signal": pos['type'],
                "Price USD": pos['entry_price'],
                "Size (qty)": pos['qty'],
                "Size (value)": pos['size_usd'],
                "Net P&L USD": pos['pnl'],
                "Net P&L %": pos['pnl_pct'],
            })
    
    df_export = pd.DataFrame(rows)
    df_export.to_csv(filename, index=False)
    print(f"✅ Export CSV TradingView: {filename}")
    return df_export


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
    
    # Affichage du rapport TradingView style
    print_tradingview_style_report(trades)
    
    # Export CSV
    export_tradingview_csv(trades, "backtest_smartbot_v2_tradingview.csv")
    
    print("\n✨ Backtest terminé!")


def backtest_smartbot_v2_multi_portfolio(
    assets_data: Dict[str, pd.DataFrame],
    parametres: ParametresDCA_SmartBotV2,
    max_active_trades: int = 3
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.Series], Dict[str, Dict], pd.Series, Dict]:
    """
    Backtest SmartBot V2 avec gestion de portfolio multi-assets
    
    Args:
        assets_data: Dict {asset_name: DataFrame avec OHLCV}
        parametres: Paramètres SmartBot V2
        max_active_trades: Nombre maximum de positions simultanées
        
    Returns:
        (per_asset_trades, per_asset_equity, per_asset_stats, combined_equity, combined_stats)
    """
    
    # Préparer tous les DataFrames avec indicateurs
    assets_prepared = {}
    for asset, df in assets_data.items():
        indicators = calculer_indicateurs_smartbot(df, parametres)
        assets_prepared[asset] = {
            'df': df,
            'indicators': indicators,
            'indice': df.index.to_numpy(),
            'prix': df['Close'].to_numpy()
        }
    
    # Créer un index temporel unifié (union de tous les timestamps)
    all_timestamps = pd.DatetimeIndex([])
    for asset_data in assets_prepared.values():
        all_timestamps = all_timestamps.union(asset_data['indice'])
    all_timestamps = all_timestamps.sort_values()
    
    # Variables de gestion du portfolio
    capital_disponible = float(parametres.initial_capital)
    capital_history = [float(parametres.initial_capital)]  # Historique du capital pour calcul drawdown
    positions_ouvertes = {}  # {asset: {entry_time, entry_price, quantity, so_count, so_list, invested}}
    trades_history = {asset: [] for asset in assets_data.keys()}
    equity_history = []
    
    print(f"\n{'='*80}")
    print(f"🎯 BACKTEST PORTFOLIO MULTI-ASSET")
    print(f"📊 Assets: {list(assets_data.keys())}")
    print(f"🔢 Max Positions Simultanées: {max_active_trades}")
    print(f"💰 Capital Initial: ${capital_disponible:,.2f}")
    print(f"{'='*80}\n")
    
    # Parcourir chronologiquement toutes les barres
    for t_idx, timestamp in enumerate(all_timestamps):
        unrealized_pnl = 0.0
        
        # Vérifier les conditions de sortie et SO pour les positions ouvertes
        for asset in list(positions_ouvertes.keys()):
            if asset not in assets_prepared:
                continue
                
            asset_data = assets_prepared[asset]
            df = asset_data['df']
            
            # Trouver l'index le plus proche de ce timestamp
            if timestamp not in df.index:
                continue
            
            idx = df.index.get_loc(timestamp)
            if idx >= len(df):
                continue
                
            position = positions_ouvertes[asset]
            current_price = df['Close'].iloc[idx]
            indicators = asset_data['indicators']
            
            # Calculer le prix moyen d'entrée
            avg_entry = position['entry_price'] if position['so_count'] == 0 else (
                position['invested'] / position['quantity']
            )
            
            # Vérifier la condition de Take Profit
            tp_target = avg_entry * (1 + parametres.take_profit / 100)
            
            if current_price >= tp_target:
                # SORTIE : Take Profit
                exit_value = position['quantity'] * current_price * (1 - parametres.commission)
                pnl = exit_value - position['invested']
                pnl_pct = (pnl / position['invested']) * 100
                
                capital_disponible += exit_value
                capital_history.append(capital_disponible)  # Enregistrer le retour de capital
                
                # Enregistrer le trade
                trades_history[asset].append({
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': timestamp,
                    'exit_price': current_price,
                    'quantity': position['quantity'],
                    'so_count': position['so_count'],
                    'so_times': position['so_list'].get('times', []),
                    'so_prices': position['so_list'].get('prices', []),
                    'invested': position['invested'],
                    'pnl': pnl,
                    'pnl_pct': pnl_pct
                })
                
                print(f"✅ [{ timestamp.strftime('%Y-%m-%d')}] TAKE PROFIT {asset} @ ${current_price:.2f} | "
                      f"SOs={position['so_count']} | PnL=${pnl:.2f} ({pnl_pct:.2f}%)")
                
                del positions_ouvertes[asset]
                continue
            
            # Vérifier les conditions de Safety Order
            if position['so_count'] < parametres.max_safe_order:
                atr = indicators['atr'][idx] if idx < len(indicators['atr']) else 0
                
                # Calculer le seuil de déclenchement du SO
                if parametres.pricedevbase == "ATR":
                    atr_mult_current = parametres.atr_mult * (parametres.atr_mult_step_scale ** position['so_count'])
                    so_trigger = avg_entry - (atr * atr_mult_current)
                elif parametres.pricedevbase == "From Last Safety Order":
                    last_price = position['so_list']['prices'][-1] if position['so_list']['prices'] else position['entry_price']
                    deviation = last_price * (parametres.price_deviation / 100)
                    so_trigger = last_price - deviation
                else:  # From Base Order
                    deviation = position['entry_price'] * (parametres.price_deviation / 100)
                    scale_factor = parametres.deviation_scale ** position['so_count']
                    so_trigger = position['entry_price'] - (deviation * scale_factor)
                
                if current_price <= so_trigger:
                    # Déclencher le Safety Order
                    so_size = parametres.safe_order * (parametres.safe_order_volume_scale ** position['so_count'])
                    
                    if capital_disponible >= so_size:
                        so_quantity = (so_size / current_price) * (1 - parametres.commission)
                        capital_disponible -= so_size
                        capital_history.append(capital_disponible)  # SO = baisse de capital (drawdown)
                        
                        position['quantity'] += so_quantity
                        position['invested'] += so_size
                        position['so_count'] += 1
                        position['so_list']['times'].append(timestamp)
                        position['so_list']['prices'].append(current_price)
                        
                        new_avg = position['invested'] / position['quantity']
                        
                        print(f"🔻 [{timestamp.strftime('%Y-%m-%d')}] SAFETY ORDER #{position['so_count']} {asset} @ ${current_price:.2f} | "
                              f"Size=${so_size:.2f} | Avg=${new_avg:.2f}")
            
            # Calculer le PnL non réalisé
            current_value = position['quantity'] * current_price
            unrealized_pnl += (current_value - position['invested'])
        
        # Vérifier les conditions d'entrée pour les assets sans position
        if len(positions_ouvertes) < max_active_trades:
            entry_signals = []
            
            for asset, asset_data in assets_prepared.items():
                if asset in positions_ouvertes:
                    continue
                    
                df = asset_data['df']
                if timestamp not in df.index:
                    continue
                    
                idx = df.index.get_loc(timestamp)
                if idx >= len(df):
                    continue
                
                indicators = asset_data['indicators']
                
                # Évaluer les Deal Start Conditions
                dsc_signal = evaluer_dsc(
                    parametres.dsc,
                    indicators['rsi'][idx] if idx < len(indicators['rsi']) else 50,
                    indicators['mfi'][idx] if idx < len(indicators['mfi']) else 50,
                    indicators['bb_percent'][idx] if idx < len(indicators['bb_percent']) else 0.5,
                    parametres
                )
                
                if dsc_signal:
                    current_price = df['Close'].iloc[idx]
                    entry_signals.append((asset, current_price))
            
            # Prendre les meilleures opportunités d'entrée
            slots_disponibles = max_active_trades - len(positions_ouvertes)
            for asset, entry_price in entry_signals[:slots_disponibles]:
                if capital_disponible >= parametres.base_order:
                    # ENTRÉE : Base Order
                    quantity = (parametres.base_order / entry_price) * (1 - parametres.commission)
                    capital_disponible -= parametres.base_order
                    capital_history.append(capital_disponible)  # Enregistrer la baisse de capital
                    
                    positions_ouvertes[asset] = {
                        'entry_time': timestamp,
                        'entry_price': entry_price,
                        'quantity': quantity,
                        'so_count': 0,
                        'so_list': {'times': [], 'prices': []},
                        'invested': parametres.base_order
                    }
                    
                    print(f"📍 [{timestamp.strftime('%Y-%m-%d')}] BASE ORDER {asset} @ ${entry_price:.2f} | "
                          f"Qty={quantity:.6f} | Capital restant=${capital_disponible:.2f}")
        
        # Enregistrer l'equity à ce timestamp
        total_equity = capital_disponible
        for position in positions_ouvertes.values():
            # Trouver le prix actuel pour cet asset
            for asset, pos_data in positions_ouvertes.items():
                if pos_data == position and asset in assets_prepared:
                    df = assets_prepared[asset]['df']
                    if timestamp in df.index:
                        current_price = df.loc[timestamp, 'Close']
                        total_equity += position['quantity'] * current_price
        
        equity_history.append({'timestamp': timestamp, 'equity': total_equity})
    
    # Fermer les positions ouvertes à la fin (optionnel)
    if parametres.close_last_trade:
        for asset, position in list(positions_ouvertes.items()):
            df = assets_prepared[asset]['df']
            final_price = df['Close'].iloc[-1]
            exit_value = position['quantity'] * final_price * (1 - parametres.commission)
            pnl = exit_value - position['invested']
            pnl_pct = (pnl / position['invested']) * 100
            
            capital_disponible += exit_value
            
            trades_history[asset].append({
                'entry_time': position['entry_time'],
                'entry_price': position['entry_price'],
                'exit_time': df.index[-1],
                'exit_price': final_price,
                'quantity': position['quantity'],
                'so_count': position['so_count'],
                'so_times': position['so_list']['times'],
                'so_prices': position['so_list']['prices'],
                'invested': position['invested'],
                'pnl': pnl,
                'pnl_pct': pnl_pct
            })
            
            print(f"🔚 [{df.index[-1].strftime('%Y-%m-%d')}] CLÔTURE FORCÉE {asset} @ ${final_price:.2f} | "
                  f"PnL=${pnl:.2f} ({pnl_pct:.2f}%)")
    
    # Créer les DataFrames de résultats
    per_asset_trades = {}
    per_asset_stats = {}
    per_asset_equity = {}
    
    for asset in assets_data.keys():
        if trades_history[asset]:
            df_trades = pd.DataFrame(trades_history[asset])
            per_asset_trades[asset] = df_trades
            
            # Calculer les statistiques par asset
            winning = df_trades[df_trades['pnl'] > 0]
            total_so = int(df_trades['so_count'].sum())
            total_events = len(df_trades) + total_so  # Chaque SO = événement perdant
            
            # Calculer le Win Rate TradingView (chaque position individuelle compte)
            individual_positions = []
            for _, trade in df_trades.iterrows():
                # Base Order (BO_0)
                bo_pnl = trade['pnl'] if trade['so_count'] == 0 else 0
                individual_positions.append({
                    'type': 'BO_0',
                    'pnl': bo_pnl,
                    'is_win': bo_pnl > 0
                })
                
                # Safety Orders (SO_1, SO_2, etc.)
                for so_idx in range(trade['so_count']):
                    # Les SO sont considérés comme des pertes car ils baissent le prix moyen
                    individual_positions.append({
                        'type': f'SO_{so_idx + 1}',
                        'pnl': 0,  # PnL distribué sur le BO
                        'is_win': False  # SO = toujours perte selon TradingView
                    })
            
            # Compter les positions gagnantes
            positions_win = sum(1 for p in individual_positions if p['is_win'])
            total_positions = len(individual_positions)
            win_rate_tradingview = (positions_win / total_positions * 100) if total_positions > 0 else 0
            
            stats = {
                'total_trades': len(df_trades),
                'total_orders_placed': int(len(df_trades) + total_so),
                'total_so_placed': total_so,
                'winning_trades': len(winning),
                'losing_trades': len(df_trades) - len(winning),
                'total_events': total_events,
                'win_rate': (len(winning) / total_events * 100) if total_events > 0 else 0,
                'win_rate_tradingview': float(win_rate_tradingview),
                'total_positions': total_positions,
                'total_pnl': float(df_trades['pnl'].sum()),
                'avg_pnl_per_trade': float(df_trades['pnl'].mean()),
                'avg_so_per_trade': float(df_trades['so_count'].mean()),
                'max_so_used': int(df_trades['so_count'].max()),
                'individual_positions': individual_positions  # Garder pour le tableau
            }
            per_asset_stats[asset] = stats
        else:
            per_asset_trades[asset] = pd.DataFrame()
            per_asset_stats[asset] = {'total_trades': 0}
    
    # Calcul du drawdown basé sur l'évolution réelle du capital
    capital_array = np.array(capital_history)
    peak_capital = np.maximum.accumulate(capital_array)
    drawdowns = capital_array - peak_capital
    max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
    max_drawdown_pct = (max_drawdown / parametres.initial_capital * 100) if parametres.initial_capital > 0 else 0.0
    
    # Créer l'équité combinée
    equity_df = pd.DataFrame(equity_history)
    if not equity_df.empty:
        equity_df = equity_df.set_index('timestamp')
        combined_equity = equity_df['equity']
    else:
        combined_equity = pd.Series()
    
    print(f"\n{'='*80}")
    print(f"📈 RÉSULTATS PORTFOLIO")
    print(f"{'='*80}")
    print(f"Capital Initial:    ${parametres.initial_capital:,.2f}")
    print(f"Capital Final:      ${capital_disponible:,.2f}")
    print(f"Return:             {((capital_disponible - parametres.initial_capital) / parametres.initial_capital * 100):.2f}%")
    print(f"Max Drawdown:       ${max_drawdown:,.2f} ({max_drawdown_pct:.2f}%)")
    print(f"Positions ouvertes: {len(positions_ouvertes)}")
    print(f"{'='*80}\n")
    
    # Créer les statistiques combinées
    combined_stats = {
        'initial_capital': float(parametres.initial_capital),
        'final_capital': float(capital_disponible),
        'total_return_pct': float((capital_disponible - parametres.initial_capital) / parametres.initial_capital * 100),
        'max_drawdown': max_drawdown,
        'max_drawdown_pct': max_drawdown_pct,
        'open_positions': len(positions_ouvertes),
        'max_active_trades': max_active_trades
    }
    
    return per_asset_trades, per_asset_equity, per_asset_stats, combined_equity, combined_stats


def evaluer_dsc(dsc_type: str, rsi: float, mfi: float, bb_pct: float, parametres: ParametresDCA_SmartBotV2) -> bool:
    """Évalue les Deal Start Conditions"""
    conditions = {
        'RSI': rsi < parametres.dsc_rsi_threshold_low,
        'MFI': mfi < parametres.mfi_threshold_low,
        'BB': bb_pct < parametres.bb_threshold_low
    }
    
    if dsc_type == "RSI":
        return conditions['RSI']
    elif dsc_type == "MFI":
        return conditions['MFI']
    elif dsc_type == "Bollinger Band %":
        return conditions['BB']
    elif dsc_type == "RSI + MFI":
        return conditions['RSI'] and conditions['MFI']
    elif dsc_type == "RSI + BB":
        return conditions['RSI'] and conditions['BB']
    elif dsc_type == "BB + MFI":
        return conditions['BB'] and conditions['MFI']
    elif dsc_type == "All Three":
        return conditions['RSI'] and conditions['MFI'] and conditions['BB']
    
    return False
