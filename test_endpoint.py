"""Script de test pour déboguer l'endpoint SmartBot V2"""
import sys
sys.path.insert(0, r'C:\Projet-Kronos')

import pandas as pd
import yfinance as yf
from backtester_exact import ParametresDCA_SmartBotV2, backtest_smartbot_v2

# Test de téléchargement yfinance
print("=" * 80)
print("TEST 1: Téléchargement via yfinance")
print("=" * 80)

ticker = "BTC-USD"
start_date = "2024-01-01"
end_date = "2025-01-01"
timeframe = "1d"

print(f"📥 Téléchargement {ticker} ({timeframe}, {start_date} → {end_date})")
df = yf.download(ticker, start=start_date, end=end_date, interval=timeframe, progress=False)

print(f"\n✅ {len(df)} bougies téléchargées")
print(f"📊 Type de colonnes: {type(df.columns)}")
print(f"📋 Colonnes: {list(df.columns)}")
print(f"\n🔍 Aperçu des données:")
print(df.head())

# Gérer le multi-index
print("\n" + "=" * 80)
print("TEST 2: Traitement des colonnes")
print("=" * 80)

if isinstance(df.columns, pd.MultiIndex):
    print("🔧 Multi-index détecté, aplatissement...")
    df.columns = df.columns.get_level_values(0)
    print(f"✅ Colonnes aplaties: {list(df.columns)}")

# Supprimer Adj Close si présente
if 'Adj Close' in df.columns:
    df = df.drop('Adj Close', axis=1)
    print("🗑️ Adj Close supprimée")

# Vérifier colonnes requises
required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
missing = [col for col in required_cols if col not in df.columns]

if missing:
    print(f"❌ ERREUR: Colonnes manquantes: {missing}")
    print(f"📋 Colonnes disponibles: {list(df.columns)}")
    sys.exit(1)

df = df[required_cols]
df = df.dropna()

print(f"✅ Données standardisées: {len(df)} bougies")
print(f"📋 Colonnes finales: {list(df.columns)}")

# Test du backtester
print("\n" + "=" * 80)
print("TEST 3: Exécution du backtest")
print("=" * 80)

try:
    params = ParametresDCA_SmartBotV2(
        dsc='RSI + MFI',
        base_order=1000.0,
        safe_order=1500.0,
        max_safe_order=20,
        safe_order_volume_scale=1.5,
        pricedevbase='ATR',
        price_deviation=4.0,
        take_profit=1.5,
        tp_type='From Average Entry',
        commission=0.001,
        rsi_length=2,
        rsi_threshold=3,
        mfi_length=14,
        mfi_threshold=30,
        bb_length=20,
        atr_length=14,
        atr_mult=3.0,
        atr_step_scale=1.2
    )
    
    print("✅ Paramètres créés")
    print(f"🎯 DSC: {params.dsc}")
    print(f"💰 Base Order: {params.base_order}")
    print(f"🔄 Safe Order: {params.safe_order}")
    
    print("\n🚀 Lancement du backtest...")
    results = backtest_smartbot_v2(df, params)
    
    print("\n✅ BACKTEST RÉUSSI!")
    print(f"📈 Trades: {results['total_trades']}")
    print(f"🎯 Win Rate: {results['win_rate']:.1f}%")
    print(f"💰 PnL Total: {results['total_pnl']:.2f}")
    
except Exception as e:
    print(f"\n❌ ERREUR: {type(e).__name__}: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("✅ TOUS LES TESTS RÉUSSIS!")
print("=" * 80)
