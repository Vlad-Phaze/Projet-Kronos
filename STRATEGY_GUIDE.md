# 📘 Guide de Création de Stratégies Kronos

## 🎯 Vue d'ensemble

Ce guide explique comment créer des stratégies de trading compatibles avec le backtester Kronos qui utilise :
- **Fetcher multi-exchange** : agrégation de données OHLCV de 7 exchanges
- **vectorbt** : simulation de portfolio et calcul de statistiques
- **Flask API** : endpoint pour upload et exécution de stratégies custom

---

## ✅ Structure Requise

### 1. **Classe de Stratégie**

Votre fichier Python doit contenir **UNE classe** dont le nom contient le mot `"Strategy"` (ex: `MACrossoverStrategy`, `RSIStrategy`, `MyTradingStrategy`).

```python
class MACrossoverStrategy:
    """
    Exemple de stratégie Moving Average Crossover
    """
    pass
```

### 2. **Méthode `generate_signals()`**

Votre classe **DOIT** implémenter la méthode suivante :

```python
def generate_signals(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Génère les signaux de trading à partir des données OHLCV.
    
    Args:
        df (pd.DataFrame): DataFrame avec colonnes OHLCV en MINUSCULES
            - 'open': prix d'ouverture
            - 'high': prix le plus haut
            - 'low': prix le plus bas
            - 'close': prix de clôture
            - 'volume': volume échangé
            
        params (dict): Paramètres de la stratégie (ex: {'fast': 10, 'slow': 50})
    
    Returns:
        pd.DataFrame: DataFrame avec AU MINIMUM une colonne 'side'
            - 'side' = 'long' : position longue active
            - 'side' = 'flat' : pas de position
            - (autres colonnes optionnelles pour debug/analyse)
    """
    # Votre code ici
    pass
```

---

## 🔑 Règles Critiques

### ❗ 1. Noms de Colonnes en MINUSCULES

Le fetcher Kronos normalise automatiquement les colonnes OHLCV en **minuscules** :

```python
# ✅ CORRECT
df['close']
df['high']
df['low']

# ❌ INCORRECT
df['Close']
df['HIGH']
df['Low']
```

### ❗ 2. Colonne 'side' OBLIGATOIRE

Le DataFrame retourné **DOIT** contenir une colonne `'side'` avec les valeurs :
- `'long'` : entrer ou maintenir une position longue
- `'flat'` : sortir ou rester hors du marché

```python
out = pd.DataFrame(index=df.index)
out['side'] = 'flat'  # Valeur par défaut
out.loc[condition_achat, 'side'] = 'long'
return out
```

### ❗ 3. Gestion d'État des Positions

**IMPORTANT** : Les signaux doivent maintenir l'état de position entre les barres, pas seulement signaler les entrées/sorties ponctuelles.

#### ❌ MAUVAISE APPROCHE (signaux ponctuels)
```python
# NE FAIT QUE MARQUER LES POINTS D'ENTRÉE
out['side'] = np.where(long_entries, 'long', 'flat')
# Problème : la position est 'long' seulement à la barre d'entrée !
```

#### ✅ BONNE APPROCHE (état maintenu)
```python
# Initialisation
position = 0  # 0 = flat, 1 = long
out = pd.DataFrame(index=df.index)
out['side'] = 'flat'

# Boucle pour maintenir l'état
for i in range(len(df)):
    if long_entries.iloc[i] and position == 0:
        position = 1  # Entrer en position
    elif long_exits.iloc[i] and position == 1:
        position = 0  # Sortir de position
    
    out.iloc[i, out.columns.get_loc('side')] = 'long' if position == 1 else 'flat'

return out
```

### ❗ 4. Paramètre `min_periods` dans les Indicateurs

Utilisez `min_periods=window` pour éviter les signaux prématurés avec des données incomplètes :

```python
# ✅ CORRECT
fast_ma = df['close'].rolling(window=10, min_periods=10).mean()
slow_ma = df['close'].rolling(window=50, min_periods=50).mean()

# ❌ INCORRECT (signaux avec seulement 1-2 barres)
fast_ma = df['close'].rolling(window=10, min_periods=1).mean()
```

---

## 📝 Template de Stratégie Complète

Voici un template prêt à l'emploi que vous pouvez copier et modifier :

```python
import pandas as pd
import numpy as np


class MyCustomStrategy:
    """
    Template de stratégie pour Kronos Backtester
    
    Cette stratégie est compatible avec :
    - Fetcher multi-exchange Kronos
    - vectorbt Portfolio.from_signals()
    - Flask API /backtest-custom-strategy
    """
    
    def __init__(self):
        """Optionnel : initialisation de variables"""
        self.name = "My Custom Strategy"
    
    def generate_signals(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Génère les signaux de trading.
        
        Args:
            df: DataFrame OHLCV (colonnes en minuscules)
            params: Dictionnaire de paramètres
        
        Returns:
            DataFrame avec colonne 'side' ('long' ou 'flat')
        """
        # 1. Extraire les paramètres
        param1 = params.get('param1', 14)  # Valeur par défaut si absent
        param2 = params.get('param2', 30)
        
        # 2. Calculer les indicateurs
        # IMPORTANT : min_periods = window pour éviter signaux prématurés
        indicator1 = df['close'].rolling(window=param1, min_periods=param1).mean()
        indicator2 = df['close'].rolling(window=param2, min_periods=param2).mean()
        
        # 3. Définir les conditions d'entrée/sortie
        long_entries = (indicator1 > indicator2)  # Exemple : golden cross
        long_exits = (indicator1 < indicator2)    # Exemple : death cross
        
        # 4. Créer le DataFrame de sortie
        out = pd.DataFrame(index=df.index)
        out['side'] = 'flat'
        
        # 5. Maintenir l'état de position (CRITIQUE)
        position = 0  # 0 = flat, 1 = long
        
        for i in range(len(df)):
            # Entrée en position
            if long_entries.iloc[i] and position == 0:
                position = 1
            
            # Sortie de position
            elif long_exits.iloc[i] and position == 1:
                position = 0
            
            # Assigner l'état
            out.iloc[i, out.columns.get_loc('side')] = 'long' if position == 1 else 'flat'
        
        # 6. (Optionnel) Ajouter des colonnes de debug
        out['indicator1'] = indicator1
        out['indicator2'] = indicator2
        out['entry_signal'] = long_entries
        out['exit_signal'] = long_exits
        
        return out


# Optionnel : fonction wrapper pour compatibilité API
def build_strategy():
    """Retourne une instance de la stratégie"""
    return MyCustomStrategy()
```

---

## 🧪 Exemple Complet : MA Crossover

Voici un exemple réel et testé de stratégie Moving Average Crossover :

```python
import pandas as pd
import numpy as np


class MACrossoverStrategy:
    """
    Stratégie de croisement de moyennes mobiles (Golden/Death Cross)
    
    Signaux :
    - LONG : MA rapide croise au-dessus de MA lente
    - EXIT : MA rapide croise en-dessous de MA lente
    """
    
    def generate_signals(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        # Paramètres par défaut
        fast = params.get('fast', 10)
        slow = params.get('slow', 50)
        
        # Calcul des moyennes mobiles
        # IMPORTANT : min_periods = window
        fast_ma = df['close'].rolling(window=fast, min_periods=fast).mean()
        slow_ma = df['close'].rolling(window=slow, min_periods=slow).mean()
        
        # Détection des croisements
        long_entries = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        long_exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        
        # Initialisation de la sortie
        out = pd.DataFrame(index=df.index)
        out['side'] = 'flat'
        
        # Maintien de l'état de position
        position = 0
        
        for i in range(len(df)):
            if long_entries.iloc[i] and position == 0:
                position = 1  # Entrer
            elif long_exits.iloc[i] and position == 1:
                position = 0  # Sortir
            
            out.iloc[i, out.columns.get_loc('side')] = 'long' if position == 1 else 'flat'
        
        return out
```

---

## 🚀 Utilisation avec le Backtester

### Option 1 : Via Flask API (Upload de fichier)

1. Accédez à `http://localhost:5002/upload_strategy.html`
2. Uploadez votre fichier `.py`
3. Configurez les paramètres :
   - Cryptos : `BTC,ETH,SOL`
   - Exchange : laissez vide pour fusion multi-exchange
   - Dates : `2023-01-01` à `2024-01-01`
   - Capital : `10000`
   - Fees : `0.05%`, Slippage : `0.02%`

### Option 2 : Via CLI

```bash
cd datafeed_tester

# Single asset
python run_multi_vectorbt.py \
  --bases BTC \
  --strategy strategies.ma_crossover_vector_bt:MACrossoverStrategy \
  --start 2023-01-01 \
  --end 2024-01-01 \
  --init-cash 10000

# Multi-asset
python run_multi_vectorbt.py \
  --bases BTC,ETH,SOL,XRP \
  --strategy strategies.ma_crossover_vector_bt:MACrossoverStrategy \
  --start 2023-01-01 \
  --end 2024-01-01 \
  --init-cash 10000 \
  --max-active-trades 2
```

### Option 3 : Via Python Script

```python
from datafeed_tester.run_multi_vectorbt import run_multi_backtest

result = run_multi_backtest(
    bases=['BTC', 'ETH'],
    strategy_ref='strategies.ma_crossover_vector_bt:MACrossoverStrategy',
    start_date='2023-01-01',
    end_date='2024-01-01',
    init_cash=10000,
    fee=0.0005,
    slippage=0.0002
)

print(result['combined_stats'])
```

---

## 📊 Format des Données OHLCV

Le DataFrame `df` reçu par `generate_signals()` a la structure suivante :

```python
# Index : DatetimeIndex
# Colonnes (en minuscules) :
df.columns = ['open', 'high', 'low', 'close', 'volume']

# Exemple :
#                      open     high      low    close      volume
# 2023-01-01 00:00:00  16500.0  16600.0  16450.0  16550.0  1234567.89
# 2023-01-01 01:00:00  16550.0  16700.0  16500.0  16680.0  9876543.21
# ...
```

### Source des Données

Par défaut, le fetcher agrège les données de **7 exchanges** :
- Binance
- Coinbase
- KuCoin
- OKX
- Bybit
- Bitfinex
- Bitstamp

Pour chaque timestamp, les valeurs OHLCV sont la **médiane** des 7 sources disponibles, ce qui réduit le bruit et améliore la robustesse.

---

## ⚙️ Paramètres Disponibles

### Dans `params` dict

Vous pouvez accéder à ces paramètres dans votre méthode `generate_signals()` :

```python
def generate_signals(self, df, params):
    # Paramètres de stratégie custom
    rsi_period = params.get('rsi_period', 14)
    rsi_oversold = params.get('rsi_oversold', 30)
    
    # Paramètres de backtesting (pour info)
    init_cash = params.get('init_cash', 10000)
    fee = params.get('fee', 0.0005)
    
    # ...
```

### Paramètres Backtesting

- `init_cash` : Capital initial (défaut : 10000)
- `fee` : Frais de trading en décimal (0.0005 = 0.05%)
- `slippage` : Slippage en décimal (0.0002 = 0.02%)
- `timeframe` : Intervalle des bougies ('1h', '4h', '1d')
- `exchange` : Exchange spécifique ou '' pour fusion

---

## 🧰 Bibliothèques Disponibles

Votre environnement Python inclut :

```python
# Manipulation de données
import pandas as pd
import numpy as np

# Indicateurs techniques
import pandas_ta as ta
# Exemple : ta.rsi(df['close'], length=14)
#          ta.bbands(df['close'], length=20, std=2)
#          ta.ema(df['close'], length=50)

# Backtesting
import vectorbt as vbt

# Exchange data
import ccxt
```

### Exemples d'Indicateurs avec pandas_ta

```python
# RSI
rsi = ta.rsi(df['close'], length=14)

# Bollinger Bands
bb = ta.bbands(df['close'], length=20, std=2)
# bb contient : BBL_20_2.0, BBM_20_2.0, BBU_20_2.0, BBB_20_2.0, BBP_20_2.0

# MACD
macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
# macd contient : MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9

# EMA
ema_20 = ta.ema(df['close'], length=20)

# ATR (volatilité)
atr = ta.atr(df['high'], df['low'], df['close'], length=14)
```

---

## 🐛 Debugging et Tests

### 1. Ajouter des colonnes de debug

```python
def generate_signals(self, df, params):
    # ... calculs ...
    
    out = pd.DataFrame(index=df.index)
    out['side'] = 'long' if position else 'flat'
    
    # Colonnes de debug (optionnelles mais utiles)
    out['fast_ma'] = fast_ma
    out['slow_ma'] = slow_ma
    out['entry'] = long_entries
    out['exit'] = long_exits
    
    return out
```

Ces colonnes seront sauvegardées dans les CSV de résultats.

### 2. Tester localement

```python
# Test rapide de votre stratégie
if __name__ == '__main__':
    import ccxt
    
    # Fetch test data
    exchange = ccxt.binance()
    ohlcv = exchange.fetch_ohlcv('BTC/USDT', '1h', limit=500)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    # Normaliser en minuscules
    df.columns = [col.lower() for col in df.columns]
    
    # Test de la stratégie
    strategy = MyCustomStrategy()
    signals = strategy.generate_signals(df, {'param1': 10, 'param2': 50})
    
    print("Signaux générés :")
    print(signals.tail(20))
    print(f"\nNombre de trades potentiels : {(signals['side'] != signals['side'].shift()).sum()}")
```

### 3. Vérifier les résultats

Après un backtest, consultez les CSV générés :

```bash
ls -lh datafeed_tester/*.csv

# Voir les stats
cat datafeed_tester/multi_vectorbt_combined_stats.csv

# Voir l'équité
head datafeed_tester/multi_vectorbt_combined_equity.csv
```

---

## 📈 Statistiques Retournées

Le backtester calcule automatiquement :

### Stats Globales (combined)
- `start_value` : Capital initial
- `end_value` : Capital final
- `total_return_pct` : Rendement total en %
- `max_drawdown_pct` : Drawdown maximum en %
- `num_assets` : Nombre d'assets tradés

### Stats par Asset
- `start_value` : Capital alloué
- `end_value` : Capital final
- `total_return_pct` : Rendement en %
- `max_drawdown_pct` : Drawdown max en %
- `total_trades` : Nombre de trades
- `win_rate_pct` : Taux de réussite en %
- `profit_factor` : Ratio gains/pertes
- `total_fees_paid` : Frais totaux payés

---

## ❓ FAQ

### Q : Puis-je trader à découvert (short) ?

**R :** Actuellement, seules les positions `'long'` et `'flat'` sont supportées. Pour le short, vous devrez modifier le code de `run_multi_vectorbt.py` pour accepter `'short'` dans la colonne `'side'`.

### Q : Comment gérer plusieurs assets simultanément ?

**R :** La stratégie reçoit les données d'un seul asset à la fois. Le runner appelle `generate_signals()` pour chaque asset séparément, puis agrège les résultats avec un système de gating global (`max_active_trades`).

### Q : Mes résultats diffèrent entre Binance direct et multi-exchange fusion

**R :** C'est normal ! La fusion médiane de 7 exchanges produit des prix légèrement différents. Une différence de 3-5% est acceptable et indique une stratégie robuste.

### Q : Comment ajouter des stop-loss / take-profit ?

**R :** Vous devez les implémenter dans votre logique de signaux. Exemple :

```python
def generate_signals(self, df, params):
    stop_loss_pct = params.get('stop_loss', 0.05)  # 5%
    take_profit_pct = params.get('take_profit', 0.10)  # 10%
    
    entry_price = None
    position = 0
    out = pd.DataFrame(index=df.index)
    out['side'] = 'flat'
    
    for i in range(len(df)):
        current_price = df['close'].iloc[i]
        
        if position == 0:
            # Logique d'entrée
            if buy_condition:
                position = 1
                entry_price = current_price
        else:
            # Check stop-loss
            if current_price <= entry_price * (1 - stop_loss_pct):
                position = 0
                entry_price = None
            
            # Check take-profit
            elif current_price >= entry_price * (1 + take_profit_pct):
                position = 0
                entry_price = None
        
        out.iloc[i, out.columns.get_loc('side')] = 'long' if position else 'flat'
    
    return out
```

### Q : Puis-je utiliser des données externes (API, fichiers) ?

**R :** Oui, mais assurez-vous que votre code est autonome. Toutes les dépendances doivent être installées dans `venv312`.

### Q : Comment optimiser les paramètres ?

**R :** Utilisez une boucle externe pour tester plusieurs combinaisons :

```python
for fast in range(5, 30, 5):
    for slow in range(30, 100, 10):
        result = run_multi_backtest(
            bases=['BTC'],
            strategy_ref='...',
            params={'fast': fast, 'slow': slow}
        )
        print(f"fast={fast}, slow={slow}: {result['combined_stats']['total_return_pct']:.2f}%")
```

---

## 🎓 Bonnes Pratiques

1. **Testez d'abord sur une seule crypto et une période courte**
   ```bash
   --bases BTC --start 2024-01-01 --end 2024-03-01
   ```

2. **Vérifiez le nombre de trades**
   - Trop peu (< 10) : stratégie trop restrictive
   - Trop (> 500) : surtrading, frais élevés

3. **Analysez le drawdown**
   - < 20% : excellent
   - 20-40% : acceptable
   - > 40% : risque élevé

4. **Validez sur plusieurs périodes**
   - Bull market : 2023
   - Bear market : 2022
   - Sideways : 2019

5. **Utilisez des paramètres robustes**
   - Évitez l'overfitting (trop de paramètres)
   - Préférez des règles simples et explicables

---

## 📚 Ressources

- **vectorbt docs** : https://vectorbt.dev
- **pandas_ta docs** : https://github.com/twopirllc/pandas-ta
- **ccxt docs** : https://docs.ccxt.com

---

## ✉️ Support

Pour toute question ou problème, consultez le code source dans :
- `datafeed_tester/run_multi_vectorbt.py` : orchestration
- `datafeed_tester/backtester_vectorbt.py` : fetching
- `datafeed_tester/app.py` : API Flask

---

**Version :** 1.0  
**Dernière mise à jour :** Janvier 2026  
**Projet :** Kronos Backtester by Vlad-Phaze
