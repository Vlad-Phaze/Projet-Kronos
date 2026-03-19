"""
SmartBot V2 DCA Strategy - FULL VERSION
Version complète avec Safety Orders, identique au PineScript
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple

try:
    import vectorbt as vbt
except ImportError:
    vbt = None


class SmartBotV2DCAStrategyFull:
    """
    Stratégie DCA complète avec Safety Orders (identique au PineScript)
    
    Cette version implémente la VRAIE logique DCA :
    - Base Order + Safety Orders multiples
    - Calcul du prix moyen pondéré
    - Volume scaling (chaque SO est plus gros)
    - Price deviation logic (déclenchement des SO)
    - Tracking complet de l'état du trade
    """
    
    # Paramètres par défaut (alignés avec PineScript)
    rsi_length: int = 14
    rsi_threshold: float = 30.0
    bb_length: int = 20
    bb_mult: float = 2.0
    bb_threshold: float = 0.0
    mfi_length: int = 14
    mfi_threshold: float = 20.0
    atr_length: int = 14
    atr_mult: float = 1.5
    atr_smoothing: int = 14
    dsc_mode: str = "RSI"
    
    # Paramètres DCA
    base_order: float = 100.0
    safe_order: float = 200.0
    max_safe_order: int = 10
    safe_order_volume_scale: float = 1.5
    price_deviation: float = 1.5
    deviation_scale: float = 1.0
    pricedevbase: str = "From Base Order"
    
    # Paramètres Take Profit
    take_profit: float = 1.5
    tp_type: str = "From Average Entry"
    
    # Conditions secondaires
    dsc2_enabled: bool = False
    dsc2: str = "Bollinger Band %"
    
    def __init__(self, *args, **kwargs):
        """Initialisation de la stratégie"""
        pass
    
    def _calculate_rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        """Calcule le RSI"""
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_bb_percent(self, close: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
        """Calcule le Bollinger Band %"""
        sma = close.rolling(window=period, min_periods=period).mean()
        std = close.rolling(window=period, min_periods=period).std()
        
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        
        bb_pct = (close - lower) / (upper - lower)
        return bb_pct
    
    def _calculate_mfi(self, high: pd.Series, low: pd.Series, close: pd.Series, 
                       volume: pd.Series, period: int = 14) -> pd.Series:
        """Calcule le Money Flow Index"""
        typical_price = (high + low + close) / 3
        raw_money_flow = typical_price * volume
        
        # Calculer la direction du flux monétaire (vectorisé)
        price_change = typical_price.diff()
        
        # Money flow positif quand le prix monte, négatif quand il descend
        positive_flow = raw_money_flow.where(price_change > 0, 0.0)
        negative_flow = raw_money_flow.where(price_change < 0, 0.0)
        
        # Somme sur la période
        positive_mf = positive_flow.rolling(window=period, min_periods=period).sum()
        negative_mf = negative_flow.rolling(window=period, min_periods=period).sum()
        
        # Calcul du MFI
        mfr = positive_mf / negative_mf
        mfi = 100 - (100 / (1 + mfr))
        
        return mfi
    
    def _calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, 
                       period: int = 14) -> pd.Series:
        """Calcule l'ATR"""
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period, min_periods=period).mean()
        return atr
    
    def _calculate_atr_percent(self, high: pd.Series, low: pd.Series, close: pd.Series,
                               atr_length: int, atr_smoothing: int, atr_mult: float) -> pd.Series:
        """Calcule l'ATR en pourcentage (lissé)"""
        atr_raw = self._calculate_atr(high, low, close, atr_length)
        atr_pct = (atr_raw / close.shift(1)) * 100
        atr_smooth = atr_pct.rolling(window=atr_smoothing, min_periods=atr_smoothing).mean()
        return atr_smooth * atr_mult
    
    def _calc_required_deviation(self, so_number: int, price_deviation: float, deviation_scale: float) -> float:
        """Calcule la déviation requise pour un SO donné"""
        return price_deviation * (deviation_scale ** so_number)
    
    def _calc_cumulative_deviation(self, so_number: int, price_deviation: float, deviation_scale: float) -> float:
        """Calcule la déviation cumulative depuis le base order"""
        cum_dev = 0.0
        for i in range(so_number + 1):
            cum_dev += self._calc_required_deviation(i, price_deviation, deviation_scale)
        return cum_dev
    
    def _calc_so_size(self, so_number: int, safe_order: float, safe_order_volume_scale: float) -> float:
        """Calcule la taille du Safety Order basé sur le scaling"""
        return safe_order * (safe_order_volume_scale ** so_number)
    
    def generate_orders(self, df: pd.DataFrame, params: Dict[str, Any] | None = None) -> pd.DataFrame:
        """
        Génère les ordres DCA complets (Base Order + Safety Orders)
        
        Retourne un DataFrame avec les colonnes :
        - 'order_type': 'BO' (Base Order), 'SO' (Safety Order), 'TP' (Take Profit/Exit)
        - 'size': Taille de l'ordre en $
        - 'price': Prix de l'ordre
        - 'side': 1 (buy/long), -1 (sell/exit)
        """
        params = params or {}
        
        # Extraire les paramètres
        rsi_length = int(params.get("rsi_length", self.rsi_length))
        rsi_threshold = float(params.get("rsi_threshold", self.rsi_threshold))
        bb_length = int(params.get("bb_length", self.bb_length))
        bb_mult = float(params.get("bb_mult", self.bb_mult))
        bb_threshold = float(params.get("bb_threshold", self.bb_threshold))
        mfi_length = int(params.get("mfi_length", self.mfi_length))
        mfi_threshold = float(params.get("mfi_threshold", self.mfi_threshold))
        atr_length = int(params.get("atr_length", self.atr_length))
        atr_mult = float(params.get("atr_mult", self.atr_mult))
        atr_smoothing = int(params.get("atr_smoothing", self.atr_smoothing))
        dsc_mode = params.get("dsc_mode", self.dsc_mode)
        
        base_order = float(params.get("base_order", self.base_order))
        safe_order = float(params.get("safe_order", self.safe_order))
        max_safe_order = int(params.get("max_safe_order", self.max_safe_order))
        safe_order_volume_scale = float(params.get("safe_order_volume_scale", self.safe_order_volume_scale))
        price_deviation = float(params.get("price_deviation", self.price_deviation))
        deviation_scale = float(params.get("deviation_scale", self.deviation_scale))
        pricedevbase = params.get("pricedevbase", self.pricedevbase)
        
        take_profit = float(params.get("take_profit", self.take_profit))
        tp_type = params.get("tp_type", self.tp_type)
        
        dsc2_enabled = bool(params.get("dsc2_enabled", self.dsc2_enabled))
        dsc2 = params.get("dsc2", self.dsc2)
        
        # Normaliser les colonnes
        df_work = df.copy()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col.capitalize() in df_work.columns:
                df_work[col] = df_work[col.capitalize()]
        
        close = df_work['close'].astype(float)
        high = df_work['high'].astype(float)
        low = df_work['low'].astype(float)
        volume = df_work['volume'].astype(float)
        
        # Calculer les indicateurs
        rsi = self._calculate_rsi(close, rsi_length)
        bb_pct = self._calculate_bb_percent(close, bb_length, bb_mult)
        mfi = self._calculate_mfi(high, low, close, volume, mfi_length)
        atr_pct = self._calculate_atr_percent(high, low, close, atr_length, atr_smoothing, atr_mult)
        
        # Signaux individuels
        rsi_sig = rsi < rsi_threshold
        bb_sig = bb_pct < bb_threshold
        mfi_sig = mfi < mfi_threshold
        
        # ═══════════════════════════════════════════════════════════════
        # DEAL START CONDITION (DSC) - Primary Signal
        # ═══════════════════════════════════════════════════════════════
        # L'utilisateur choisit quel(s) indicateur(s) utiliser pour déclencher un Base Order
        # Seuls les indicateurs sélectionnés dans dsc_mode sont évalués
        if dsc_mode == "RSI":
            primary_signal = rsi_sig  # RSI < threshold uniquement
        elif dsc_mode == "Bollinger Band %":
            primary_signal = bb_sig  # BB% < threshold uniquement
        elif dsc_mode == "MFI":
            primary_signal = mfi_sig  # MFI < threshold uniquement
        elif dsc_mode == "RSI + BB":
            primary_signal = rsi_sig & bb_sig  # Les DEUX doivent être vrais
        elif dsc_mode == "RSI + MFI":
            primary_signal = rsi_sig & mfi_sig  # Les DEUX doivent être vrais
        elif dsc_mode == "BB + MFI":
            primary_signal = bb_sig & mfi_sig  # Les DEUX doivent être vrais
        elif dsc_mode == "All Three":
            primary_signal = rsi_sig & bb_sig & mfi_sig  # Les TROIS doivent être vrais
        else:
            primary_signal = rsi_sig & bb_sig  # Défaut: RSI + BB
        
        # ═══════════════════════════════════════════════════════════════
        # DOUBLE SAFETY CONDITION (DSC2) - Secondary Signal
        # ═══════════════════════════════════════════════════════════════
        # Si activé, ajoute une condition supplémentaire en AND avec primary_signal
        # Exemple: primary_signal = RSI < 30 ET secondary_signal = BB% < 0.0
        if dsc2_enabled:
            if dsc2 == "RSI":
                secondary_signal = rsi_sig
            elif dsc2 == "Bollinger Band %":
                secondary_signal = bb_sig
            elif dsc2 == "MFI":
                secondary_signal = mfi_sig
            else:
                secondary_signal = pd.Series(True, index=close.index)
            
            entry_signal = primary_signal & secondary_signal  # Les DEUX doivent être vrais
        else:
            entry_signal = primary_signal  # Pas de condition secondaire
        
        # ═══════════════════════════════════════════════════════════════
        # TIMING: Décalage pour exécution TradingView-style
        # ═══════════════════════════════════════════════════════════════
        # TradingView: Signal détecté au CLOSE de barre N → Exécution au OPEN de barre N+1
        # Python: On shift le signal d'une barre pour exécuter au CLOSE de barre N+1
        # (vectorbt utilise le close, donc shift(1) simule l'open de la barre suivante)
        entry_signal = entry_signal.shift(1).fillna(False)
        
        # Variables d'état du trade
        in_trade = False
        base_order_price = None
        last_so_price = None
        avg_entry_price = None
        total_position_size = 0.0
        total_invested = 0.0
        current_so_count = 0
        deal_number = 0
        
        # Liste des ordres
        orders = []
        
        # Boucle sur chaque bougie
        for i in range(len(df)):
            price = close.iloc[i]
            sig = entry_signal.iloc[i]
            
            # ════════════════════════════════════════════════════════════
            # BASE ORDER ENTRY
            # ════════════════════════════════════════════════════════════
            if not in_trade and sig:
                in_trade = True
                base_order_price = price
                last_so_price = price
                current_so_count = 0
                deal_number += 1
                
                qty = base_order / price
                total_position_size = qty
                total_invested = base_order
                avg_entry_price = price
                
                orders.append({
                    'timestamp': df.index[i],
                    'order_type': 'BO',
                    'size': base_order,
                    'price': price,
                    'side': 1,
                    'deal_number': deal_number
                })
                
                continue
            
            # ════════════════════════════════════════════════════════════
            # SAFETY ORDER LOGIC
            # ════════════════════════════════════════════════════════════
            if in_trade and current_so_count < max_safe_order:
                # Calculer le prix de déclenchement du SO
                if pricedevbase == "From Base Order":
                    cum_dev = self._calc_cumulative_deviation(current_so_count, price_deviation, deviation_scale)
                    trigger_price = base_order_price * (1 - cum_dev / 100)
                
                elif pricedevbase == "From Last Safety Order":
                    ref_price = last_so_price
                    req_dev = self._calc_required_deviation(current_so_count, price_deviation, deviation_scale)
                    trigger_price = ref_price * (1 - req_dev / 100)
                
                elif pricedevbase == "ATR":
                    ref_price = last_so_price
                    atr_val = atr_pct.iloc[i] if not pd.isna(atr_pct.iloc[i]) else 0
                    trigger_price = ref_price * (1 - atr_val / 100)
                
                else:
                    trigger_price = base_order_price * (1 - price_deviation / 100)
                
                # Vérifier si le prix est en dessous du trigger ET signal d'entrée actif
                if price <= trigger_price and sig:
                    # Calculer la taille du SO
                    so_size = self._calc_so_size(current_so_count, safe_order, safe_order_volume_scale)
                    so_qty = so_size / price
                    
                    # Mettre à jour le prix moyen pondéré
                    total_invested += so_size
                    total_position_size += so_qty
                    avg_entry_price = total_invested / total_position_size
                    
                    last_so_price = price
                    current_so_count += 1
                    
                    orders.append({
                        'timestamp': df.index[i],
                        'order_type': f'SO_{current_so_count}',
                        'size': so_size,
                        'price': price,
                        'side': 1,
                        'deal_number': deal_number
                    })
            
            # ════════════════════════════════════════════════════════════
            # TAKE PROFIT EXIT
            # ════════════════════════════════════════════════════════════
            if in_trade:
                # Calculer le prix TP
                if tp_type == "From Average Entry":
                    tp_price = avg_entry_price * (1 + take_profit / 100)
                else:  # "From Base Order"
                    tp_price = base_order_price * (1 + take_profit / 100)
                
                # Vérifier si TP atteint
                if price >= tp_price:
                    # Ordre de sortie (vendre toute la position)
                    orders.append({
                        'timestamp': df.index[i],
                        'order_type': 'TP',
                        'size': total_invested,
                        'price': price,
                        'side': -1,
                        'deal_number': deal_number,
                        'avg_entry': avg_entry_price,
                        'profit_pct': ((price / avg_entry_price) - 1) * 100
                    })
                    
                    # Réinitialiser l'état
                    in_trade = False
                    base_order_price = None
                    last_so_price = None
                    avg_entry_price = None
                    total_position_size = 0.0
                    total_invested = 0.0
                    current_so_count = 0
        
        # Convertir en DataFrame
        orders_df = pd.DataFrame(orders)
        
        if len(orders_df) > 0:
            orders_df = orders_df.set_index('timestamp')
        
        return orders_df
    
    def generate_signals(self, df: pd.DataFrame, params: Dict[str, Any] | None = None) -> pd.DataFrame:
        """
        Génère des signaux compatibles avec le format standard du backtesteur
        
        Cette méthode convertit les ordres DCA en signaux simples
        pour compatibilité avec run_multi_vectorbt.py
        """
        orders_df = self.generate_orders(df, params)
        
        # Créer un DataFrame de signaux
        signals = pd.DataFrame(index=df.index)
        signals['long_entries'] = False
        signals['long_exits'] = False
        signals['side'] = 'flat'
        
        if len(orders_df) == 0:
            return signals
        
        # Marquer les entrées (Base Order uniquement pour le signal simple)
        base_orders = orders_df[orders_df['order_type'] == 'BO']
        for idx in base_orders.index:
            if idx in signals.index:
                signals.loc[idx, 'long_entries'] = True
        
        # Marquer les sorties (Take Profit)
        exits = orders_df[orders_df['order_type'] == 'TP']
        for idx in exits.index:
            if idx in signals.index:
                signals.loc[idx, 'long_exits'] = True
        
        # Calculer l'état persistant 'side'
        position = 0
        side_values = []
        
        for idx in df.index:
            if idx in signals.index:
                if signals.loc[idx, 'long_entries']:
                    position = 1
                elif signals.loc[idx, 'long_exits']:
                    position = 0
            side_values.append('long' if position == 1 else 'flat')
        
        signals['side'] = side_values
        
        return signals


# Fonction de compatibilité
def build_strategy(broker=None, data=None, params: Dict[str, Any] | None = None):
    """Wrapper pour compatibilité avec l'API Flask"""
    class Wrapper:
        def __init__(self, params):
            self.strategy = SmartBotV2DCAStrategyFull()
            self.params = params or {}
        
        def run(self):
            pass
    
    return Wrapper(params)
