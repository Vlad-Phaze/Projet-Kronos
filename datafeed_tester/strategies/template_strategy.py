"""
TEMPLATE DE STRATÉGIE KRONOS BACKTESTER

Copiez ce fichier et modifiez-le pour créer votre propre stratégie.
Compatible avec le fetcher multi-exchange et vectorbt.

RÈGLES IMPORTANTES :
1. La classe DOIT contenir "Strategy" dans son nom
2. Méthode generate_signals(df, params) OBLIGATOIRE
3. Colonnes OHLCV en MINUSCULES : 'open', 'high', 'low', 'close', 'volume'
4. Retourner un DataFrame avec colonne 'side' ('long' ou 'flat')
5. MAINTENIR l'état de position entre les barres (pas seulement signaler l'entrée)

Consultez STRATEGY_GUIDE.md pour plus de détails.
"""

import pandas as pd
import numpy as np


class TemplateStrategy:
    """
    Template de stratégie pour Kronos Backtester
    
    Remplacez cette description par celle de votre stratégie.
    """
    
    def __init__(self):
        """Optionnel : initialisation"""
        self.name = "Template Strategy"
        self.version = "1.0"
    
    def generate_signals(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Génère les signaux de trading.
        
        Args:
            df (pd.DataFrame): DataFrame OHLCV avec colonnes en minuscules
                - 'open', 'high', 'low', 'close', 'volume'
                
            params (dict): Paramètres de la stratégie
                Exemples d'accès :
                - period = params.get('period', 14)  # défaut : 14
                - threshold = params.get('threshold', 0.02)
        
        Returns:
            pd.DataFrame: DataFrame avec AU MINIMUM la colonne 'side'
                - 'side' = 'long' : position longue active
                - 'side' = 'flat' : pas de position
        """
        
        # ========================================
        # 1. EXTRAIRE LES PARAMÈTRES
        # ========================================
        param1 = params.get('param1', 14)      # Valeur par défaut
        param2 = params.get('param2', 30)
        threshold = params.get('threshold', 0.02)
        
        
        # ========================================
        # 2. CALCULER LES INDICATEURS
        # ========================================
        # IMPORTANT : min_periods = window pour éviter signaux prématurés
        
        # Exemple : Moyennes mobiles
        ma_short = df['close'].rolling(window=param1, min_periods=param1).mean()
        ma_long = df['close'].rolling(window=param2, min_periods=param2).mean()
        
        # Exemple : RSI (avec pandas_ta si installé)
        # import pandas_ta as ta
        # rsi = ta.rsi(df['close'], length=param1)
        
        # Exemple : Volatilité
        returns = df['close'].pct_change()
        volatility = returns.rolling(window=20, min_periods=20).std()
        
        
        # ========================================
        # 3. DÉFINIR LES CONDITIONS D'ENTRÉE/SORTIE
        # ========================================
        
        # Exemple : Golden Cross (MA courte > MA longue)
        long_entries = (ma_short > ma_long) & (ma_short.shift(1) <= ma_long.shift(1))
        
        # Exemple : Death Cross (MA courte < MA longue)
        long_exits = (ma_short < ma_long) & (ma_short.shift(1) >= ma_long.shift(1))
        
        # Vous pouvez ajouter des filtres supplémentaires
        # Exemple : ne trader que si volatilité faible
        # low_volatility_filter = volatility < threshold
        # long_entries = long_entries & low_volatility_filter
        
        
        # ========================================
        # 4. CRÉER LE DATAFRAME DE SORTIE
        # ========================================
        out = pd.DataFrame(index=df.index)
        out['side'] = 'flat'  # Valeur par défaut
        
        
        # ========================================
        # 5. MAINTENIR L'ÉTAT DE POSITION
        # ========================================
        # CRITIQUE : ne pas utiliser simplement np.where() !
        # Il faut une boucle pour maintenir l'état entre les barres
        
        position = 0  # 0 = flat, 1 = long
        
        for i in range(len(df)):
            # Entrée en position longue
            if long_entries.iloc[i] and position == 0:
                position = 1
            
            # Sortie de position
            elif long_exits.iloc[i] and position == 1:
                position = 0
            
            # Assigner l'état actuel
            out.iloc[i, out.columns.get_loc('side')] = 'long' if position == 1 else 'flat'
        
        
        # ========================================
        # 6. (OPTIONNEL) AJOUTER DES COLONNES DE DEBUG
        # ========================================
        # Ces colonnes seront sauvegardées dans les CSV de résultats
        out['ma_short'] = ma_short
        out['ma_long'] = ma_long
        out['entry_signal'] = long_entries
        out['exit_signal'] = long_exits
        out['volatility'] = volatility
        
        
        return out


# ========================================
# FONCTION WRAPPER (OPTIONNEL)
# ========================================
def build_strategy():
    """
    Retourne une instance de la stratégie.
    Utilisé par certaines versions de l'API.
    """
    return TemplateStrategy()


# ========================================
# TEST LOCAL
# ========================================
if __name__ == '__main__':
    """
    Code de test pour vérifier votre stratégie localement
    avant de l'uploader sur le backtester.
    """
    import ccxt
    
    print("=" * 60)
    print("TEST LOCAL DE LA STRATÉGIE")
    print("=" * 60)
    
    try:
        # Fetch test data from Binance
        print("\n📊 Récupération des données de test (Binance BTC/USDT, 1h)...")
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv('BTC/USDT', '1h', limit=500)
        
        # Convert to DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # Normaliser les colonnes en minuscules (comme le fetcher Kronos)
        df.columns = [col.lower() if isinstance(col, str) else col for col in df.columns]
        
        print(f"✅ {len(df)} barres récupérées")
        print(f"   Période : {df.index[0]} à {df.index[-1]}")
        print(f"   Prix : ${df['close'].iloc[0]:.2f} → ${df['close'].iloc[-1]:.2f}")
        
        # Instancier la stratégie
        print("\n🧠 Génération des signaux...")
        strategy = TemplateStrategy()
        params = {
            'param1': 10,
            'param2': 50,
            'threshold': 0.02
        }
        signals = strategy.generate_signals(df, params)
        
        # Analyser les résultats
        print(f"✅ Signaux générés : {len(signals)} barres")
        
        # Compter les changements de position (trades)
        position_changes = (signals['side'] != signals['side'].shift()).sum()
        long_bars = (signals['side'] == 'long').sum()
        
        print(f"\n📈 STATISTIQUES DES SIGNAUX:")
        print(f"   Changements de position : {position_changes}")
        print(f"   Barres en position 'long' : {long_bars} ({long_bars/len(signals)*100:.1f}%)")
        print(f"   Barres en position 'flat' : {len(signals) - long_bars} ({(len(signals)-long_bars)/len(signals)*100:.1f}%)")
        
        # Afficher les derniers signaux
        print(f"\n🔍 DERNIERS SIGNAUX (20 dernières barres):")
        print(signals[['side', 'ma_short', 'ma_long', 'entry_signal', 'exit_signal']].tail(20))
        
        # Vérification de cohérence
        print(f"\n✅ VÉRIFICATIONS:")
        if 'side' in signals.columns:
            print("   ✓ Colonne 'side' présente")
        else:
            print("   ✗ ERREUR : Colonne 'side' manquante !")
        
        unique_sides = signals['side'].unique()
        if set(unique_sides).issubset({'long', 'flat'}):
            print(f"   ✓ Valeurs 'side' valides : {unique_sides}")
        else:
            print(f"   ✗ ERREUR : Valeurs 'side' invalides : {unique_sides}")
        
        if position_changes > 0:
            print(f"   ✓ La stratégie génère des trades ({position_changes} changements)")
        else:
            print("   ⚠️  Aucun trade généré - vérifiez vos conditions d'entrée/sortie")
        
        print("\n" + "=" * 60)
        print("✅ TEST TERMINÉ - Stratégie prête à être uploadée !")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ ERREUR lors du test : {e}")
        import traceback
        traceback.print_exc()
