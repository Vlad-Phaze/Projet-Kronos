"""
SmartBot V2 DCA Strategy
Stratégie DCA avec conditions multiples (RSI, BB%, MFI) et gestion des Safety Orders
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

try:
    import vectorbt as vbt
except ImportError:
    vbt = None


class SmartBotV2DCAStrategy:
    """
    Stratégie DCA intelligente avec indicateurs multiples
    
    Paramètres:
    - rsi_length: Période RSI (défaut: 14)
    - rsi_threshold: Seuil RSI pour entrée (défaut: 30)
    - bb_length: Période Bollinger Bands (défaut: 20)
    - bb_mult: Multiplicateur BB (défaut: 2.0)
    - bb_threshold: Seuil BB% pour entrée (défaut: 0.2)
    - mfi_length: Période MFI (défaut: 14)
    - mfi_threshold: Seuil MFI pour entrée (défaut: 30)
    - atr_length: Période ATR (défaut: 14)
    - atr_mult: Multiplicateur ATR (défaut: 1.0)
    - dsc_mode: Mode de combinaison ("RSI", "BB", "MFI", "RSI+BB", "RSI+MFI", "BB+MFI", "ALL")
    - take_profit: Take profit en % (défaut: 3.0)
    """
    
    # Paramètres par défaut (alignés avec PineScript)
    rsi_length: int = 14
    rsi_threshold: float = 30.0
    bb_length: int = 20
    bb_mult: float = 2.0
    bb_threshold: float = 0.0  # ✅ CORRIGÉ: 0.0 au lieu de 0.2 (correspond à la bande basse)
    mfi_length: int = 14
    mfi_threshold: float = 20.0  # ✅ CORRIGÉ: 20 au lieu de 30
    atr_length: int = 14
    atr_mult: float = 1.5  # ✅ CORRIGÉ: 1.5 au lieu de 1.0
    atr_smoothing: int = 14  # ✅ AJOUTÉ: Période de lissage ATR
    dsc_mode: str = "RSI+BB"
    take_profit: float = 1.5  # ✅ CORRIGÉ: 1.5% au lieu de 3.0%
    
    # Paramètres DCA (nouveaux, alignés avec PineScript)
    base_order: float = 100.0  # ✅ AJOUTÉ: Base Order Size ($)
    safe_order: float = 200.0  # ✅ AJOUTÉ: Safety Order Size ($)
    max_safe_order: int = 10  # ✅ AJOUTÉ: Max Safety Orders
    safe_order_volume_scale: float = 1.5  # ✅ AJOUTÉ: SO Volume Scale
    price_deviation: float = 1.5  # ✅ AJOUTÉ: Price Deviation (%)
    deviation_scale: float = 1.0  # ✅ AJOUTÉ: Deviation Scale
    pricedevbase: str = "From Base Order"  # ✅ AJOUTÉ: Deviation method
    tp_type: str = "From Average Entry"  # ✅ AJOUTÉ: TP calculation type
    dsc2_enabled: bool = False  # ✅ AJOUTÉ: Secondary condition enabled
    dsc2: str = "Bollinger Band %"  # ✅ AJOUTÉ: Secondary condition type
    
    def __init__(self, *args, **kwargs):
        """Initialisation de la stratégie"""
        pass
    
    def _calculate_rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        """Calcule le RSI manuellement"""
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
        
        money_flow_positive = pd.Series(0.0, index=close.index)
        money_flow_negative = pd.Series(0.0, index=close.index)
        
        for i in range(1, len(typical_price)):
            if typical_price.iloc[i] > typical_price.iloc[i-1]:
                money_flow_positive.iloc[i] = raw_money_flow.iloc[i]
            elif typical_price.iloc[i] < typical_price.iloc[i-1]:
                money_flow_negative.iloc[i] = raw_money_flow.iloc[i]
        
        mf_positive = money_flow_positive.rolling(window=period, min_periods=period).sum()
        mf_negative = money_flow_negative.rolling(window=period, min_periods=period).sum()
        
        mfi = 100 - (100 / (1 + (mf_positive / mf_negative)))
        return mfi
    
    def _calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, 
                       period: int = 14) -> pd.Series:
        """Calcule l'ATR (Average True Range)"""
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period, min_periods=period).mean()
        return atr
    
    def generate_signals(self, df: pd.DataFrame, params: Dict[str, Any] | None = None) -> pd.DataFrame:
        """
        Génère des signaux de trading basés sur RSI, BB%, MFI
        
        Args:
            df: DataFrame OHLCV (doit contenir: open, high, low, close, volume)
            params: Paramètres optionnels
        
        Returns:
            DataFrame avec colonnes:
            - 'long_entries': bool
            - 'long_exits': bool
            - 'side': 'long' ou 'flat'
        """
        params = params or {}
        
        # Récupérer les paramètres
        rsi_length = int(params.get("rsi_length", self.rsi_length))
        rsi_threshold = float(params.get("rsi_threshold", self.rsi_threshold))
        bb_length = int(params.get("bb_length", self.bb_length))
        bb_mult = float(params.get("bb_mult", self.bb_mult))
        bb_threshold = float(params.get("bb_threshold", self.bb_threshold))
        mfi_length = int(params.get("mfi_length", self.mfi_length))
        mfi_threshold = float(params.get("mfi_threshold", self.mfi_threshold))
        atr_length = int(params.get("atr_length", self.atr_length))
        atr_mult = float(params.get("atr_mult", self.atr_mult))
        dsc_mode = params.get("dsc_mode", self.dsc_mode)
        take_profit = float(params.get("take_profit", self.take_profit))
        
        # Normaliser les noms de colonnes
        df_work = df.copy()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col.capitalize() in df_work.columns:
                df_work[col] = df_work[col.capitalize()]
        
        # Vérifier que les colonnes nécessaires existent
        required_cols = ['close', 'high', 'low', 'volume']
        for col in required_cols:
            if col not in df_work.columns:
                raise ValueError(f"DataFrame doit contenir la colonne '{col}'")
        
        close = df_work['close'].astype(float)
        high = df_work['high'].astype(float)
        low = df_work['low'].astype(float)
        volume = df_work['volume'].astype(float)
        
        # Calculer les indicateurs
        rsi = self._calculate_rsi(close, rsi_length)
        bb_pct = self._calculate_bb_percent(close, bb_length, bb_mult)
        mfi = self._calculate_mfi(high, low, close, volume, mfi_length)
        atr = self._calculate_atr(high, low, close, atr_length)
        atr_pct = (atr / close.shift(1)) * 100 * atr_mult
        
        # Signaux individuels
        rsi_sig = rsi < rsi_threshold
        bb_sig = bb_pct < bb_threshold
        mfi_sig = mfi < mfi_threshold
        
        # Combiner les signaux selon le mode
        if dsc_mode == "RSI":
            entry_signal = rsi_sig
        elif dsc_mode == "BB":
            entry_signal = bb_sig
        elif dsc_mode == "MFI":
            entry_signal = mfi_sig
        elif dsc_mode == "RSI+BB":
            entry_signal = rsi_sig & bb_sig
        elif dsc_mode == "RSI+MFI":
            entry_signal = rsi_sig & mfi_sig
        elif dsc_mode == "BB+MFI":
            entry_signal = bb_sig & mfi_sig
        elif dsc_mode == "ALL":
            entry_signal = rsi_sig & bb_sig & mfi_sig
        else:
            # Par défaut: RSI+BB
            entry_signal = rsi_sig & bb_sig
        
        # État de la stratégie avec machine à états simple
        # Note: Cette version simplifiée génère des signaux d'entrée/sortie
        # Le DCA complet (safety orders) nécessite une logique plus complexe
        # qui devrait être gérée au niveau du portfolio
        
        signals = pd.DataFrame(index=df.index)
        signals['long_entries'] = entry_signal.fillna(False)
        
        # Sortie basée sur take profit (simplifié)
        # Dans une vraie implémentation DCA, ceci devrait tracker le prix moyen d'entrée
        # Pour l'instant, on utilise un simple croisement inverse ou condition RSI haute
        exit_signal = (rsi > (100 - rsi_threshold)) | (bb_pct > (1 - bb_threshold))
        signals['long_exits'] = exit_signal.fillna(False)
        
        # Créer l'état persistant 'side'
        position = 0  # 0 = flat, 1 = long
        side_values = []
        entry_price = None
        
        for idx in df.index:
            if idx in signals.index:
                # Signal d'entrée
                if signals.loc[idx, 'long_entries'] and position == 0:
                    position = 1
                    entry_price = close.loc[idx]
                
                # Signal de sortie (take profit ou condition inverse)
                elif position == 1:
                    current_price = close.loc[idx]
                    # Take profit atteint
                    if entry_price and current_price >= entry_price * (1 + take_profit / 100):
                        position = 0
                        entry_price = None
                    # Ou signal de sortie
                    elif signals.loc[idx, 'long_exits']:
                        position = 0
                        entry_price = None
            
            side_values.append('long' if position == 1 else 'flat')
        
        signals['side'] = side_values
        
        # Ajouter les indicateurs pour debug/visualisation
        signals['rsi'] = rsi
        signals['bb_pct'] = bb_pct
        signals['mfi'] = mfi
        signals['atr_pct'] = atr_pct
        
        return signals


# Fonction de compatibilité (optionnelle)
def build_strategy(broker=None, data=None, params: Dict[str, Any] | None = None):
    """Wrapper pour compatibilité avec l'API Flask"""
    class Wrapper:
        def __init__(self, params):
            self.strategy = SmartBotV2DCAStrategy()
            self.params = params or {}
        
        def run(self):
            # Cette méthode n'est pas utilisée dans le workflow actuel
            pass
    
    return Wrapper(params)
