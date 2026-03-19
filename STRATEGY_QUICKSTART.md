# 📋 Quick Start - Création de Stratégies Kronos

## 🚀 En 3 étapes

### 1. Copier le template
```bash
cp datafeed_tester/strategies/template_strategy.py datafeed_tester/strategies/ma_strategie.py
```

### 2. Modifier le code
```python
class MaStrategy:  # Nom doit contenir "Strategy"
    
    def generate_signals(self, df, params):
        # df contient : 'open', 'high', 'low', 'close', 'volume' (minuscules!)
        
        # Calculer indicateurs
        ma = df['close'].rolling(window=20, min_periods=20).mean()
        
        # Conditions
        long_entries = df['close'] > ma
        long_exits = df['close'] < ma
        
        # Maintenir l'état (IMPORTANT!)
        out = pd.DataFrame(index=df.index)
        out['side'] = 'flat'
        position = 0
        
        for i in range(len(df)):
            if long_entries.iloc[i] and position == 0:
                position = 1
            elif long_exits.iloc[i] and position == 1:
                position = 0
            out.iloc[i, out.columns.get_loc('side')] = 'long' if position else 'flat'
        
        return out
```

### 3. Tester
```bash
# Test local
python datafeed_tester/strategies/ma_strategie.py

# Backtest via API
# → Ouvrir http://localhost:5002/upload_strategy.html
# → Upload ma_strategie.py
```

## ✅ Checklist Obligatoire

- [ ] Classe avec "Strategy" dans le nom
- [ ] Méthode `generate_signals(df, params)` présente
- [ ] Colonnes OHLCV en **minuscules** : `df['close']` pas `df['Close']`
- [ ] Retourne DataFrame avec colonne `'side'`
- [ ] Valeurs 'side' : `'long'` ou `'flat'` seulement
- [ ] `min_periods=window` dans les rolling()
- [ ] **État maintenu** avec boucle (pas juste np.where sur entry!)

## 📖 Documentation Complète

Voir **[STRATEGY_GUIDE.md](STRATEGY_GUIDE.md)** pour :
- Guide détaillé avec exemples
- Template commenté
- FAQ et bonnes pratiques
- Debugging

## 🧪 Exemple Testé

Voir **[ma_crossover_vector_bt.py](datafeed_tester/strategies/ma_crossover_vector_bt.py)** :
- Stratégie complète et fonctionnelle
- Golden/Death Cross
- Testé sur BTC 2023 : +50% return

## 🌐 Upload via Web

1. Lancer le serveur :
   ```bash
   cd datafeed_tester && python app.py
   ```

2. Ouvrir : `http://localhost:5002/upload_strategy.html`

3. Uploader votre fichier `.py`

4. Résultats en temps réel !

## 💡 Exemple Ultra-Simple

```python
import pandas as pd

class SimpleStrategy:
    def generate_signals(self, df, params):
        out = pd.DataFrame(index=df.index)
        out['side'] = 'flat'
        
        # Toujours long si prix > moyenne 20
        ma20 = df['close'].rolling(20, min_periods=20).mean()
        
        position = 0
        for i in range(len(df)):
            if df['close'].iloc[i] > ma20.iloc[i] and position == 0:
                position = 1
            elif df['close'].iloc[i] < ma20.iloc[i] and position == 1:
                position = 0
            out.iloc[i, 0] = 'long' if position else 'flat'
        
        return out
```

## 📊 Indicateurs Disponibles

```python
import pandas_ta as ta

# RSI
rsi = ta.rsi(df['close'], length=14)

# Bollinger Bands
bb = ta.bbands(df['close'], length=20, std=2)

# MACD
macd = ta.macd(df['close'])

# EMA
ema = ta.ema(df['close'], length=50)
```

## ⚠️ Erreurs Fréquentes

### ❌ Ne pas maintenir l'état
```python
# MAUVAIS
out['side'] = np.where(entry, 'long', 'flat')  # Position seulement à l'entrée!
```

### ✅ Maintenir l'état
```python
# BON
position = 0
for i in range(len(df)):
    if entry[i]: position = 1
    if exit[i]: position = 0
    out.iloc[i, 0] = 'long' if position else 'flat'
```

### ❌ Colonnes en majuscules
```python
# MAUVAIS
df['Close']  # N'existe pas!
```

### ✅ Colonnes en minuscules
```python
# BON
df['close']  # Normalisé par le fetcher
```

---

**Besoin d'aide ?** Consultez [STRATEGY_GUIDE.md](STRATEGY_GUIDE.md) pour le guide complet !
