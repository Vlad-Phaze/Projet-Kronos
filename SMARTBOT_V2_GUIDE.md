# SmartBot V2 DCA Strategy - Guide d'Utilisation

## 📋 Description

La **SmartBot V2 DCA Strategy** est une stratégie de Dollar Cost Averaging (DCA) intelligente qui utilise plusieurs indicateurs techniques pour identifier les points d'entrée optimaux en survente.

## 🎯 Logique de la Stratégie

### Indicateurs Utilisés

1. **RSI (Relative Strength Index)** - Identifie les conditions de survente
2. **Bollinger Band %** - Mesure la position du prix dans les bandes
3. **MFI (Money Flow Index)** - Volume-weighted RSI, détecte la pression d'achat/vente
4. **ATR (Average True Range)** - Volatilité pour ajuster les niveaux d'entrée

### Conditions d'Entrée

La stratégie génère un signal d'entrée quand les indicateurs sélectionnés indiquent une survente :
- **RSI < seuil** (défaut: 30)
- **BB% < seuil** (défaut: 0.2, soit dans les 20% inférieurs de la bande)
- **MFI < seuil** (défaut: 30)

Vous pouvez combiner ces indicateurs selon différents modes (voir paramètres).

### Conditions de Sortie

La stratégie sort de position quand :
1. **Take Profit atteint** : Le prix augmente de X% depuis l'entrée (défaut: 3%)
2. **Signal inverse** : Les indicateurs montrent une condition de surachat

## ⚙️ Paramètres

### Paramètres RSI
- `rsi_length` : Période de calcul du RSI (défaut: **14**)
- `rsi_threshold` : Seuil de survente (défaut: **30**)

### Paramètres Bollinger Bands
- `bb_length` : Période des Bollinger Bands (défaut: **20**)
- `bb_mult` : Multiplicateur de l'écart-type (défaut: **2.0**)
- `bb_threshold` : Seuil BB% pour entrée (défaut: **0.2**, soit 20%)

### Paramètres MFI
- `mfi_length` : Période du Money Flow Index (défaut: **14**)
- `mfi_threshold` : Seuil de survente MFI (défaut: **30**)

### Paramètres ATR
- `atr_length` : Période de l'ATR (défaut: **14**)
- `atr_mult` : Multiplicateur ATR (défaut: **1.0**)

### Mode de Combinaison
- `dsc_mode` : Comment combiner les indicateurs
  - `"RSI"` : Utilise seulement RSI
  - `"BB"` : Utilise seulement Bollinger Band %
  - `"MFI"` : Utilise seulement MFI
  - `"RSI+BB"` : RSI ET BB doivent être en survente (défaut) ⭐
  - `"RSI+MFI"` : RSI ET MFI doivent être en survente
  - `"BB+MFI"` : BB ET MFI doivent être en survente
  - `"ALL"` : Les trois indicateurs doivent être en survente (plus strict)

### Gestion de Position
- `take_profit` : Take profit en % (défaut: **3.0%**)

## 📊 Exemples d'Utilisation

### Configuration Conservative (Moins de trades, plus sûrs)
```python
{
    'rsi_length': 14,
    'rsi_threshold': 25,      # Plus strict (survente plus forte)
    'bb_threshold': 0.15,     # Plus strict (plus près de la bande basse)
    'mfi_threshold': 25,      # Plus strict
    'dsc_mode': 'ALL',        # Tous les indicateurs doivent confirmer
    'take_profit': 5.0        # TP plus large
}
```

### Configuration Aggressive (Plus de trades)
```python
{
    'rsi_length': 14,
    'rsi_threshold': 40,      # Moins strict
    'bb_threshold': 0.3,      # Moins strict
    'mfi_threshold': 40,      # Moins strict
    'dsc_mode': 'RSI+BB',     # Seulement 2 indicateurs
    'take_profit': 2.0        # TP plus serré
}
```

### Configuration Équilibrée (Recommandée) ⭐
```python
{
    'rsi_length': 14,
    'rsi_threshold': 30,
    'bb_threshold': 0.2,
    'mfi_threshold': 30,
    'dsc_mode': 'RSI+BB',
    'take_profit': 3.0
}
```

## 🚀 Utilisation dans le Backtesteur

### 1. Via l'Interface Web

1. Allez sur `http://localhost:5002`
2. Cliquez sur "📤 Upload Custom Strategy"
3. Sélectionnez le fichier : `datafeed_tester/strategies/smartbot_v2_dca.py`
4. Configurez les paramètres :
   - Exchange : `kucoin` (meilleure couverture)
   - Période : ex. `2023-01-01` à `2024-01-01`
   - Timeframe : `4h` (recommandé pour DCA)
   - Capital : `10000`
   - Cryptos : Votre liste de paires
5. Ajustez les paramètres de la stratégie si besoin
6. Lancez le backtest

### 2. Via Code Python

```python
from datafeed_tester.strategies.smartbot_v2_dca import SmartBotV2DCAStrategy

# Initialiser la stratégie
strategy = SmartBotV2DCAStrategy()

# Générer des signaux
params = {
    'rsi_threshold': 30,
    'dsc_mode': 'RSI+BB',
    'take_profit': 3.0
}
signals = strategy.generate_signals(df, params)

# signals contient:
# - long_entries: bool
# - long_exits: bool
# - side: 'long' ou 'flat'
# - rsi, bb_pct, mfi, atr_pct (pour debug)
```

## 📈 Métriques de Performance

La stratégie génère des signaux qui seront ensuite exécutés par le backtesteur avec :
- Gestion du `max_active_trades` (limite de positions simultanées)
- Frais et slippage configurables
- Redistribution du capital sur les paires actives

## ⚠️ Limitations et Notes

### Version Simplifiée du DCA
Cette version génère des **signaux d'entrée/sortie simples**. Le vrai système DCA avec :
- **Safety Orders** multiples
- **Pyramiding** avec volume scale
- **Average down** automatique

...nécessiterait une logique plus complexe au niveau du portfolio, pas au niveau de la génération de signaux.

### Recommandations
- Testez d'abord avec 1-2 paires avant de lancer sur 84 paires
- Utilisez des timeframes 4h ou 1d pour le DCA (pas 1m ou 5m)
- Combinez avec `max_active_trades` pour gérer le risque
- Vérifiez les résultats sur différentes périodes (bullish, bearish, sideways)

## 🔧 Personnalisation

Pour ajouter vos propres modifications, éditez le fichier :
`datafeed_tester/strategies/smartbot_v2_dca.py`

Vous pouvez :
1. Ajouter d'autres indicateurs (Stochastic, MACD, etc.)
2. Modifier la logique de combinaison des signaux
3. Implémenter des filtres supplémentaires (volume, tendance, etc.)
4. Ajuster la logique de sortie

## 📞 Support

En cas de problème :
1. Vérifiez que les données OHLCV contiennent `open`, `high`, `low`, `close`, `volume`
2. Testez avec le script : `python test_smartbot_v2.py`
3. Consultez les logs du backtesteur dans `/tmp/kronos-flask.log`

## ✅ Statut du Test

**TEST RÉUSSI** ✅
- Génération de signaux : ✅
- Compatibilité backtesteur : ✅
- Indicateurs fonctionnels : ✅
- Paramètres personnalisables : ✅
