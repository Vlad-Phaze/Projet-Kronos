"""
Script de test pour SmartBot V2 DCA Strategy
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
sys.path.insert(0, '/Users/vladimirkronos/Downloads/Projet-Kronos-main')

from datafeed_tester.strategies.smartbot_v2_dca import SmartBotV2DCAStrategy

print("🧪 Test de la stratégie SmartBot V2 DCA")
print("="*80)

# 1. Créer des données de test
print("\n1️⃣  Génération de données de test...")
dates = pd.date_range(start='2024-01-01', end='2024-12-31', freq='1h')
n = len(dates)

# Simuler un prix qui oscille avec tendance
np.random.seed(42)
price_base = 50000
price = price_base + np.cumsum(np.random.randn(n) * 100)
price = np.maximum(price, 1000)  # Éviter les prix négatifs

df = pd.DataFrame({
    'open': price + np.random.randn(n) * 50,
    'high': price + np.abs(np.random.randn(n)) * 100,
    'low': price - np.abs(np.random.randn(n)) * 100,
    'close': price,
    'volume': np.random.randint(100, 1000, n)
}, index=dates)

print(f"   ✅ {len(df)} bougies générées")
print(f"   Prix: ${df['close'].min():.2f} - ${df['close'].max():.2f}")

# 2. Tester la stratégie
print("\n2️⃣  Test de la stratégie...")
strategy = SmartBotV2DCAStrategy()

# Test avec paramètres par défaut
try:
    signals = strategy.generate_signals(df)
    print(f"   ✅ Signaux générés avec succès")
    print(f"   Colonnes: {list(signals.columns)}")
    print(f"   Shape: {signals.shape}")
except Exception as e:
    print(f"   ❌ Erreur: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 3. Vérifier les colonnes requises
print("\n3️⃣  Vérification des colonnes requises...")
required_cols = ['long_entries', 'long_exits', 'side']
for col in required_cols:
    if col in signals.columns:
        print(f"   ✅ '{col}' présent")
    else:
        print(f"   ❌ '{col}' MANQUANT")

# 4. Analyser les signaux
print("\n4️⃣  Analyse des signaux...")
entry_count = signals['long_entries'].sum()
exit_count = signals['long_exits'].sum()
long_candles = (signals['side'] == 'long').sum()
flat_candles = (signals['side'] == 'flat').sum()

print(f"   Entrées (long_entries=True): {entry_count}")
print(f"   Sorties (long_exits=True): {exit_count}")
print(f"   Bougies en position: {long_candles} ({long_candles/len(signals)*100:.1f}%)")
print(f"   Bougies hors position: {flat_candles} ({flat_candles/len(signals)*100:.1f}%)")

# 5. Vérifier la cohérence
print("\n5️⃣  Vérification de la cohérence...")
errors = []

# Vérifier que side est bien 'long' ou 'flat'
unique_sides = signals['side'].unique()
if set(unique_sides) <= {'long', 'flat'}:
    print(f"   ✅ Valeurs 'side' correctes: {list(unique_sides)}")
else:
    errors.append(f"Valeurs 'side' incorrectes: {list(unique_sides)}")
    print(f"   ❌ Valeurs 'side' incorrectes: {list(unique_sides)}")

# Vérifier que les booléens sont bien des bool
if signals['long_entries'].dtype == bool:
    print(f"   ✅ 'long_entries' est bien de type bool")
else:
    errors.append(f"'long_entries' n'est pas bool: {signals['long_entries'].dtype}")
    print(f"   ⚠️  'long_entries' n'est pas bool: {signals['long_entries'].dtype}")

if signals['long_exits'].dtype == bool:
    print(f"   ✅ 'long_exits' est bien de type bool")
else:
    errors.append(f"'long_exits' n'est pas bool: {signals['long_exits'].dtype}")
    print(f"   ⚠️  'long_exits' n'est pas bool: {signals['long_exits'].dtype}")

# 6. Tester avec différents paramètres
print("\n6️⃣  Test avec paramètres personnalisés...")
custom_params = {
    'rsi_length': 20,
    'rsi_threshold': 35,
    'dsc_mode': 'RSI+MFI',
    'take_profit': 5.0
}

try:
    signals2 = strategy.generate_signals(df, custom_params)
    entry_count2 = signals2['long_entries'].sum()
    print(f"   ✅ Paramètres personnalisés fonctionnent")
    print(f"   Entrées avec nouveaux params: {entry_count2}")
except Exception as e:
    errors.append(f"Erreur avec paramètres personnalisés: {e}")
    print(f"   ❌ Erreur: {e}")

# 7. Tester les indicateurs
print("\n7️⃣  Vérification des indicateurs...")
indicator_cols = ['rsi', 'bb_pct', 'mfi', 'atr_pct']
for col in indicator_cols:
    if col in signals.columns:
        valid_count = signals[col].notna().sum()
        print(f"   ✅ '{col}': {valid_count}/{len(signals)} valeurs valides")
    else:
        print(f"   ⚠️  '{col}' non présent")

# 8. Afficher quelques exemples de signaux
print("\n8️⃣  Exemples de signaux d'entrée:")
entry_examples = signals[signals['long_entries'] == True].head(5)
if len(entry_examples) > 0:
    for idx, row in entry_examples.iterrows():
        print(f"   📅 {idx}: RSI={row['rsi']:.1f}, BB%={row['bb_pct']:.3f}, MFI={row['mfi']:.1f}")
else:
    print("   ⚠️  Aucun signal d'entrée trouvé")

# Résumé final
print("\n" + "="*80)
if len(errors) == 0:
    print("✅ TEST RÉUSSI - La stratégie est compatible avec le backtesteur")
    print("\n💡 Pour l'utiliser dans le backtesteur:")
    print("   1. Le fichier est: datafeed_tester/strategies/smartbot_v2_dca.py")
    print("   2. Uploadez ce fichier via l'interface web")
    print("   3. Sélectionnez les paramètres souhaités")
    print("   4. Lancez le backtest")
else:
    print("❌ TEST ÉCHOUÉ - Problèmes détectés:")
    for err in errors:
        print(f"   - {err}")
