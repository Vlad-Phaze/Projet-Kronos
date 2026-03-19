"""
Script pour comparer les résultats entre :
1. Version standalone (avec son propre fetcher Binance)
2. Version adaptée (avec le fetcher du projet)
"""
import pandas as pd
import numpy as np
from datafeed_tester.strategies.ma_crossover_vector_bt import ma_crossover_vectorbt, load_binance_data
from datafeed_tester.backtester_vectorbt import fetch_price_df
from datafeed_tester.strategies.ma_crossover_vector_bt import MACrossoverStrategy

print("=" * 100)
print(" " * 30 + "COMPARAISON DES DEUX VERSIONS")
print("=" * 100)

# Configuration
symbol = "BTC/USDT"
base = "BTC"
start = "2023-01-01"
end = "2024-01-01"
timeframe = "1h"
fast = 10
slow = 30

print("\n📊 Paramètres:")
print(f"   Période: {start} → {end}")
print(f"   Timeframe: {timeframe}")
print(f"   Fast MA: {fast}, Slow MA: {slow}")

# ============================================================================
# VERSION 1: Standalone (fetch Binance direct)
# ============================================================================
print("\n" + "=" * 100)
print("VERSION 1: Standalone (avec load_binance_data)")
print("=" * 100)

try:
    close_standalone = load_binance_data(symbol, start, end, timeframe=timeframe)
    print(f"✓ Données chargées: {len(close_standalone)} barres")
    print(f"  Date range: {close_standalone.index.min()} → {close_standalone.index.max()}")
    print(f"  Close min: ${close_standalone.min():.2f}, max: ${close_standalone.max():.2f}")
    
    pf_standalone, signals_standalone = ma_crossover_vectorbt(
        close=close_standalone,
        fast=fast,
        slow=slow,
        fees=0.0,
        slippage=0.0,
        long_short=False,
        init_cash=10_000,
        freq="1H"
    )
    
    stats_standalone = pf_standalone.stats()
    print("\n📈 Résultats Standalone:")
    print(f"   Start Value:      ${stats_standalone['Start Value']:.2f}")
    print(f"   End Value:        ${stats_standalone['End Value']:.2f}")
    print(f"   Total Return:     {stats_standalone['Total Return [%]']:.2f}%")
    print(f"   Max Drawdown:     {stats_standalone['Max Drawdown [%]']:.2f}%")
    print(f"   Total Trades:     {stats_standalone['Total Trades']}")
    print(f"   Win Rate:         {stats_standalone['Win Rate [%]']:.2f}%")
    print(f"   Profit Factor:    {stats_standalone['Profit Factor']:.2f}")
    
    # Afficher quelques trades
    try:
        trades_standalone = pf_standalone.trades.records_readable
        print(f"\n📝 Premiers 5 trades:")
        print(trades_standalone[['Entry Date', 'Exit Date', 'PnL', 'Return']].head(5).to_string())
    except:
        pass

except Exception as e:
    print(f"❌ Erreur version standalone: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# VERSION 2: Adaptée (avec fetcher du projet)
# ============================================================================
print("\n" + "=" * 100)
print("VERSION 2: Adaptée (avec fetch_price_df du projet)")
print("=" * 100)

try:
    df_adapted = fetch_price_df("binance", base, timeframe=timeframe, start=start, end=end)
    print(f"✓ Données chargées: {len(df_adapted)} barres")
    print(f"  Date range: {df_adapted.index.min()} → {df_adapted.index.max()}")
    
    if 'close' in df_adapted.columns:
        close_adapted = df_adapted['close']
    else:
        close_adapted = df_adapted['Close']
    
    print(f"  Close min: ${close_adapted.min():.2f}, max: ${close_adapted.max():.2f}")
    
    # Utiliser la classe adapter
    strategy = MACrossoverStrategy()
    signals_adapted = strategy.generate_signals(df_adapted, {'fast': fast, 'slow': slow})
    
    # Calculer portfolio avec vectorbt
    import vectorbt as vbt
    entries = signals_adapted['side'] == 'long'
    exits = signals_adapted['side'] != 'long'
    
    pf_adapted = vbt.Portfolio.from_signals(
        close_adapted,
        entries,
        exits,
        init_cash=10000.0,
        fees=0.0,
        slippage=0.0,
        freq="1H"
    )
    
    stats_adapted = pf_adapted.stats()
    print("\n📈 Résultats Adaptés:")
    print(f"   Start Value:      ${stats_adapted['Start Value']:.2f}")
    print(f"   End Value:        ${stats_adapted['End Value']:.2f}")
    print(f"   Total Return:     {stats_adapted['Total Return [%]']:.2f}%")
    print(f"   Max Drawdown:     {stats_adapted['Max Drawdown [%]']:.2f}%")
    print(f"   Total Trades:     {stats_adapted['Total Trades']}")
    print(f"   Win Rate:         {stats_adapted['Win Rate [%]']:.2f}%")
    print(f"   Profit Factor:    {stats_adapted['Profit Factor']:.2f}")
    
    # Afficher quelques trades
    try:
        trades_adapted = pf_adapted.trades.records_readable
        print(f"\n📝 Premiers 5 trades:")
        print(trades_adapted[['Entry Date', 'Exit Date', 'PnL', 'Return']].head(5).to_string())
    except:
        pass

except Exception as e:
    print(f"❌ Erreur version adaptée: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# COMPARAISON
# ============================================================================
print("\n" + "=" * 100)
print(" " * 35 + "COMPARAISON DÉTAILLÉE")
print("=" * 100)

try:
    print(f"\n{'Métrique':<30} {'Standalone':<20} {'Adaptée':<20} {'Différence':<15}")
    print("-" * 85)
    
    metrics = ['Start Value', 'End Value', 'Total Return [%]', 'Max Drawdown [%]', 
               'Total Trades', 'Win Rate [%]', 'Profit Factor']
    
    for metric in metrics:
        val_standalone = stats_standalone[metric]
        val_adapted = stats_adapted[metric]
        
        if isinstance(val_standalone, (int, float)) and isinstance(val_adapted, (int, float)):
            diff = val_adapted - val_standalone
            print(f"{metric:<30} {val_standalone:<20.2f} {val_adapted:<20.2f} {diff:<15.2f}")
        else:
            print(f"{metric:<30} {val_standalone:<20} {val_adapted:<20} {'N/A':<15}")
    
    print("\n💡 Analyse:")
    if abs(stats_standalone['Total Trades'] - stats_adapted['Total Trades']) > 0:
        print(f"   ⚠️  Nombre de trades différent: {stats_standalone['Total Trades']} vs {stats_adapted['Total Trades']}")
        print("   → Vérifier les timestamps et les données OHLCV exactes")
    
    if abs(stats_standalone['Total Return [%]'] - stats_adapted['Total Return [%]']) > 0.1:
        print(f"   ⚠️  Rendement différent: {stats_standalone['Total Return [%]']:.2f}% vs {stats_adapted['Total Return [%]']:.2f}%")
        print("   → Vérifier les prix d'entrée/sortie et l'exécution des signaux")

except Exception as e:
    print(f"❌ Erreur lors de la comparaison: {e}")

print("\n" + "=" * 100)
