"""
Script de diagnostic pour comparer les résultats avec TradingView
"""
import pandas as pd
import sys
sys.path.insert(0, '.')

from backtester_exact import backtest_smartbot_v2, ParametresDCA_SmartBotV2
import yfinance as yf

# Charger les données BTC
print("📊 Téléchargement des données BTC...")
btc = yf.download("BTC-USD", start="2024-01-01", end="2025-01-01", interval="4h")
btc = btc.rename(columns={'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'})

print(f"✅ {len(btc)} bougies téléchargées\n")

# Paramètres TradingView (à ajuster selon vos settings)
params = ParametresDCA_SmartBotV2(
    # Deal Start Conditions
    dsc="All Three",
    dsc_rsi_threshold_low=30,
    
    # RSI
    rsi_length=14,
    
    # Bollinger Bands
    bb_length=20,
    bb_mult=2.0,
    bb_threshold_low=0.0,
    
    # MFI
    mfi_length=14,
    mfi_threshold_low=20,
    
    # Price Deviation
    pricedevbase="ATR",
    atr_length=14,
    atr_mult=3.0,
    atr_mult_step_scale=1.2,
    
    # Orders
    quantite_base=1000.0,
    so_size=1500.0,
    volume_scale=1.0,
    nb_max_so=15,
    so_step_scale=1.0,
    
    # Take Profit
    tp_minimum=0.015,  # 1.5%
    
    # Capital
    initial_capital=100000.0
)

print("🚀 Lancement du backtest...")
print("="*80)

trades, equity, stats = backtest_smartbot_v2(btc, params)

print("\n" + "="*80)
print("📊 COMPARAISON AVEC TRADINGVIEW")
print("="*80)

# Données TradingView du CSV
tv_trades = [
    {"date": "2024-01-22", "type": "BO_0", "price": 40774},
    {"date": "2024-06-11", "type": "BO_0", "price": 66824},
    {"date": "2024-06-24", "type": "BO_0", "price": 62823},
    {"date": "2024-06-24", "type": "SO_1", "price": 59269},
    {"date": "2024-07-03", "type": "BO_0", "price": 59630},
    {"date": "2024-07-25", "type": "BO_0", "price": 64075},
    {"date": "2024-08-05", "type": "BO_0", "price": 53893},
    {"date": "2024-08-27", "type": "BO_0", "price": 61687},
    {"date": "2024-09-30", "type": "BO_0", "price": 63421},
    {"date": "2024-11-25", "type": "BO_0", "price": 93035},
]

print("\n🎯 TradingView: 10 positions (9 BO + 1 SO)")
print(f"🎯 Notre Backtester: {stats['total_individual_positions']} positions")
print(f"   └─ {stats['total_trades']} deals")
print(f"   └─ {stats['total_orders_placed']} ordres (BO + SO)")

print("\n📅 Dates d'entrée TradingView:")
for t in tv_trades:
    print(f"   {t['date']}: {t['type']} @ ${t['price']}")

print("\n📅 Dates d'entrée Notre Backtester:")
if not trades.empty:
    for idx, trade in trades.iterrows():
        entry_date = trade['entry_time'].strftime('%Y-%m-%d')
        price = trade['entry_price']
        so_count = trade.get('so_count', 0)
        trade_type = f"BO + {so_count} SO" if so_count > 0 else "BO only"
        print(f"   {entry_date}: {trade_type} @ ${price:.2f}")

print("\n" + "="*80)
print("🔍 DIAGNOSTIC")
print("="*80)

# Comparer les dates
tv_dates = set([t['date'] for t in tv_trades if t['type'] == 'BO_0'])
our_dates = set([trade['entry_time'].strftime('%Y-%m-%d') for _, trade in trades.iterrows()])

missing_in_ours = tv_dates - our_dates
extra_in_ours = our_dates - tv_dates

if missing_in_ours:
    print(f"\n❌ Trades manquants dans notre backtester:")
    for date in sorted(missing_in_ours):
        print(f"   - {date}")

if extra_in_ours:
    print(f"\n➕ Trades supplémentaires dans notre backtester:")
    for date in sorted(extra_in_ours):
        print(f"   - {date}")

if not missing_in_ours and not extra_in_ours:
    print("\n✅ Les dates correspondent parfaitement!")

print("\n💡 RECOMMANDATIONS:")
print("   1. Vérifier les paramètres DSC (Deal Start Conditions)")
print("   2. Vérifier le seuil RSI (actuellement: {})".format(params.dsc_rsi_threshold_low))
print("   3. Vérifier le timeframe (4h)")
print("   4. Vérifier la source des données (exchange)")
