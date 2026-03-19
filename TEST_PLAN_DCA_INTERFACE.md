# 🧪 Test Plan - SmartBot V2 DCA Interface Complète

## ✅ Objectif

Vérifier que tous les nouveaux paramètres DCA sont correctement :
1. **Envoyés** par le frontend (JavaScript FormData)
2. **Reçus** par le backend (Flask app.py)
3. **Transmis** à la stratégie (smartbot_v2_dca_full.py)
4. **Utilisés** dans la logique DCA

---

## 🔍 Test 1 : Vérification des Champs HTML

### Checklist Frontend

Ouvrir `http://localhost:5002/upload_strategy.html` et vérifier :

- [ ] **Section "Order Settings"** visible avec 4 champs :
  - [ ] Base Order Size ($) - défaut : 100
  - [ ] Safety Order Size ($) - défaut : 200
  - [ ] Max Safety Orders - défaut : 10
  - [ ] Safety Order Volume Scale - défaut : 1.5

- [ ] **Section "Price Deviation Settings"** visible avec 6+ champs :
  - [ ] Price Deviation Type - select avec 3 options
  - [ ] Price Deviation (%) - défaut : 1.5
  - [ ] Deviation Scale - défaut : 1.0
  - [ ] ATR Smoothing - défaut : 14

- [ ] **Section "Take Profit Settings"** visible avec 2 champs :
  - [ ] Take Profit (%) - défaut : 1.5
  - [ ] Take Profit Type - select avec 2 options

- [ ] **Section "DSC2 Secondary Condition"** visible avec 2 champs :
  - [ ] Enable Secondary Condition - checkbox
  - [ ] Secondary Condition - select (RSI, BB, MFI)

- [ ] **Sections indicateurs** toujours présentes :
  - [ ] DSC Mode
  - [ ] RSI Length/Threshold
  - [ ] BB Length/Mult/Threshold
  - [ ] MFI Length/Threshold
  - [ ] ATR Length/Mult

---

## 🔍 Test 2 : Configuration Basique

### Étapes

1. Ouvrir `http://localhost:5002/upload_strategy.html`
2. Uploader `smartbot_v2_dca_full.py`
3. Configurer :
   - **Bases** : `BTC`
   - **Exchange** : `kucoin`
   - **Timeframe** : `1h`
   - **Période** : `2024-01-01` à `2024-01-31`
   - **Capital** : `10000`
   - **Max Active Trades** : `1`

4. **Paramètres DCA** (laisser défauts) :
   - Base Order : 100
   - Safety Order : 200
   - Max SO : 10
   - Volume Scale : 1.5
   - Deviation Type : From Base Order
   - Deviation : 1.5
   - Take Profit : 1.5
   - TP Type : From Average Entry

5. **DSC Mode** : RSI
6. Cliquer "Lancer le Backtest"

### Résultats Attendus

Dans les logs Flask (`tail -f /tmp/kronos-flask.log`), vous devriez voir :

```
📥 Requête backtest-custom-strategy reçue
🤖 Nom de la classe: SmartBotV2DCAFull
   Exchange: kucoin
   Paires: ['BTC']
   Période: 2024-01-01 → 2024-01-31
   Timeframe: 1h
   Capital: 10000
   Fees: 0.001, Slippage: 0.001
   Max Active Trades: 1
   🤖 DSC Mode: RSI
   📊 RSI Length: 14
   📉 RSI Threshold: 30.0
   📊 BB Length: 20
   📊 BB Multiplier: 2.0
   📉 BB Threshold: 0.0
   💰 MFI Length: 14
   📉 MFI Threshold: 20.0
   📊 ATR Length: 14
   📊 ATR Multiplier: 1.5
   💵 Base Order: $100.0        ← NOUVEAU
   💵 Safety Order: $200.0      ← NOUVEAU
   🔢 Max Safety Orders: 10     ← NOUVEAU
   📈 SO Volume Scale: 1.5      ← NOUVEAU
   📉 Price Deviation Type: From Base Order  ← NOUVEAU
   📉 Price Deviation: 1.5%     ← NOUVEAU
   📊 Deviation Scale: 1.0      ← NOUVEAU
   📊 ATR Smoothing: 14         ← NOUVEAU
   🎯 Take Profit: 1.5%         ← NOUVEAU
   🎯 TP Type: From Average Entry  ← NOUVEAU
```

**Validation** : ✅ Tous les nouveaux paramètres apparaissent dans les logs

---

## 🔍 Test 3 : Vérification de la Logique DCA

### Étapes

Même config que Test 2, mais analyser les résultats du backtest :

### Dans les Résultats Attendus

1. **Section "Per Asset Stats"** pour BTC :
   - `num_closed_trades` > 0 (au moins quelques trades)
   - `avg_num_orders` devrait être **> 1** (prouve que les SO sont utilisés)
   - `max_num_orders` devrait être entre 2 et 11 (1 Base + jusqu'à 10 SO)

2. **Logs détaillés** :
   Chercher dans `/tmp/kronos-flask.log` des lignes comme :
   ```
   🟢 BTC-USDT: ENTRY LONG | QTY=0.002 | PRICE=$45,000
   🟡 BTC-USDT: SAFETY ORDER 1 | QTY=0.004 | PRICE=$44,325 (SO size=$200)
   🟡 BTC-USDT: SAFETY ORDER 2 | QTY=0.006 | PRICE=$43,650 (SO size=$300)
   🔴 BTC-USDT: EXIT LONG | PRICE=$44,492 | PROFIT=+1.5%
   ```

**Validation** : ✅ Les Safety Orders sont bien déclenchés et la logique DCA fonctionne

---

## 🔍 Test 4 : Modification des Paramètres DCA

### Étapes

1. Même setup que Test 2
2. **Changer les paramètres DCA** :
   - Base Order : **50**
   - Safety Order : **100**
   - Max SO : **5** (plus conservatif)
   - Volume Scale : **2.0** (agressif)
   - Deviation : **2.0** (plus patient)
   - Take Profit : **2.5** (plus gros profits)

3. Lancer le backtest

### Résultats Attendus

Dans les logs :
```
💵 Base Order: $50.0
💵 Safety Order: $100.0
🔢 Max Safety Orders: 5
📈 SO Volume Scale: 2.0
📉 Price Deviation: 2.0%
🎯 Take Profit: 2.5%
```

**Validation** : ✅ Les nouveaux paramètres personnalisés sont bien pris en compte

---

## 🔍 Test 5 : Mode Price Deviation "ATR"

### Étapes

1. Même setup que Test 2
2. **Changer Price Deviation Type** :
   - Type : **ATR** (au lieu de "From Base Order")
   - ATR Mult : 1.5
   - ATR Smoothing : 14

3. Lancer le backtest

### Résultats Attendus

Dans les logs :
```
📉 Price Deviation Type: ATR
📊 ATR Multiplier: 1.5
📊 ATR Smoothing: 14
```

**Validation** : ✅ Le mode ATR est bien activé

---

## 🔍 Test 6 : DSC2 Secondary Condition

### Étapes

1. Même setup que Test 2
2. **Activer DSC2** :
   - Cocher "Enable Secondary Condition"
   - Sélectionner DSC2 : **BB** (Bollinger Bands)
   - DSC Mode principal : **RSI**

3. Lancer le backtest

### Résultats Attendus

Dans les logs :
```
🤖 DSC Mode: RSI
🔀 DSC2 Enabled: true
🔀 DSC2 Condition: BB
```

**Validation** : ✅ La condition secondaire DSC2 est activée

---

## 🔍 Test 7 : Test Multi-Paires avec DCA

### Étapes

1. Uploader `smartbot_v2_dca_full.py`
2. Configurer :
   - **Bases** : `BTC,ETH,SOL`
   - **Exchange** : `kucoin`
   - **Timeframe** : `4h`
   - **Période** : `2024-01-01` à `2024-02-01`
   - **Capital** : `30000`
   - **Max Active Trades** : `3`

3. **Paramètres DCA** (défauts) :
   - Base Order : 100
   - Safety Order : 200
   - Max SO : 10

4. Lancer le backtest

### Résultats Attendus

1. **3 assets testés** : BTC, ETH, SOL
2. **Chaque asset** devrait avoir :
   - `num_closed_trades` > 0
   - `avg_num_orders` > 1 (preuve de DCA)
3. **Combined Stats** :
   - `total_return_pct` calculé sur ensemble du portefeuille
   - Capital réparti entre les 3 paires

**Validation** : ✅ Le DCA fonctionne correctement sur multi-paires

---

## 🔍 Test 8 : Capital Maximum

### Objectif
Vérifier que le calcul du capital max pour DCA est cohérent.

### Calcul Théorique

Avec configuration :
- Base Order : $100
- Safety Order : $200
- Max SO : 10
- Volume Scale : 1.5

**Capital max par deal** :
```
Base = $100
SO1  = $200 × 1.5⁰ = $200
SO2  = $200 × 1.5¹ = $300
SO3  = $200 × 1.5² = $450
SO4  = $200 × 1.5³ = $675
SO5  = $200 × 1.5⁴ = $1,013
SO6  = $200 × 1.5⁵ = $1,519
SO7  = $200 × 1.5⁶ = $2,279
SO8  = $200 × 1.5⁷ = $3,418
SO9  = $200 × 1.5⁸ = $5,127
SO10 = $200 × 1.5⁹ = $7,691

TOTAL = $100 + $23,672 = $23,772
```

### Test

1. Config avec capital **$5,000** (insuffisant pour 1 deal complet)
2. Lancer le backtest
3. Vérifier que :
   - Les deals se ferment avant d'atteindre 10 SO (capital épuisé)
   - Ou warning dans les logs sur capital insuffisant

**Validation** : ✅ Le système gère correctement le manque de capital

---

## 🔍 Test 9 : Comparaison avec Test Unitaire

### Objectif
Comparer les résultats du backtest web avec le test unitaire `test_smartbot_v2_full.py`

### Étapes

1. Exécuter le test unitaire :
   ```bash
   python test_smartbot_v2_full.py
   ```
   
   Résultats attendus :
   ```
   ✅ TEST RÉUSSI - Logique DCA complète fonctionnelle
   📊 2 Base Orders, 5 Safety Orders, 1 Take Profit
   💰 Volume Scaling: [100.0, 200.0, 300.0, 450.0, 675.0, 1012.5] ✅
   📉 Deviations: [-1.53%, -3.06%, -4.50%, -6.00%, -7.51%] ✅
   📈 Profit: +2.15% (+$58.97) ✅
   ```

2. Comparer avec backtest web sur même période/config

**Validation** : ✅ Les résultats sont cohérents entre test unitaire et backtest web

---

## 📊 Résumé des Validations

| Test | Objectif | Statut |
|------|----------|--------|
| 1 | Champs HTML présents | ⏳ À tester |
| 2 | Params envoyés au backend | ⏳ À tester |
| 3 | Logique DCA active | ⏳ À tester |
| 4 | Params personnalisés | ⏳ À tester |
| 5 | Mode ATR | ⏳ À tester |
| 6 | DSC2 secondaire | ⏳ À tester |
| 7 | Multi-paires DCA | ⏳ À tester |
| 8 | Gestion capital max | ⏳ À tester |
| 9 | Cohérence avec test unitaire | ⏳ À tester |

---

## 🐛 Debugging

### Si les paramètres n'apparaissent pas dans les logs

1. **Vérifier le HTML** :
   ```bash
   grep -A2 "baseOrderDollars" front/upload_strategy.html
   ```

2. **Vérifier le JavaScript** :
   ```bash
   grep "base_order" front/upload_strategy.html
   ```

3. **Vérifier app.py** :
   ```bash
   grep "base_order = request.form.get" datafeed_tester/app.py
   ```

4. **Redémarrer Flask** :
   ```bash
   pkill -f "python.*app.py"
   cd datafeed_tester && nohup python app.py > /tmp/kronos-flask.log 2>&1 &
   ```

### Si les SO ne se déclenchent pas

1. Vérifier que `smartbot_v2_dca_full.py` est bien uploadé (pas `smartbot_v2_dca.py`)
2. Vérifier les logs pour voir les paramètres DCA reçus
3. Augmenter `Max SO` si besoin
4. Diminuer `Price Deviation` pour déclencher plus tôt

---

## ✅ Critères de Succès Global

- [ ] Tous les 18+ nouveaux champs DCA sont visibles dans l'interface
- [ ] Les valeurs par défaut correspondent aux valeurs PineScript
- [ ] Les paramètres sont correctement envoyés au backend (logs)
- [ ] La stratégie utilise les paramètres (avg_num_orders > 1)
- [ ] Les 3 modes de Price Deviation fonctionnent
- [ ] DSC2 peut être activé/désactivé
- [ ] Multi-paires fonctionne avec DCA
- [ ] Résultats cohérents avec tests unitaires

---

**Si tous les tests passent → Interface DCA complète ✅**
