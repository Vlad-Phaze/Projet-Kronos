#!/usr/bin/env python3
"""Test du rapport TradingView style"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import yfinance as yf
from backtester_exact import backtest_smartbot_v2, ParametresDCA_SmartBotV2, print_tradingview_style_report, export_tradingview_csv

print("\n" + "="*80)
print("🤖 TEST RAPPORT TRADINGVIEW STYLE")
print("="*80 + "\n")

# Téléchargement des données
print("📥 Téléchargement des données BTC-USD...")
data = yf.download("BTC-USD", start="2024-01-01", end="2025-01-01", interval="1d", progress=False)

if len(data.columns) == 6:
    data.columns = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
    data = data.drop('Adj Close', axis=1)
elif len(data.columns) == 5:
    data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']

data = data.dropna()
print(f"✅ {len(data)} barres téléchargées\n")

# Configuration SmartBot V2
params = ParametresDCA_SmartBotV2(
    dsc="RSI + MFI",
    base_order=1000.0,
    safe_order=1500.0,
    max_safe_order=20,
    safe_order_volume_scale=1.5,
    pricedevbase="ATR",
    atr_mult=3.0,
    take_profit=1.5,
    tp_type="From Average Entry",
    rsi_length=2,
    dsc_rsi_threshold_low=3,
    mfi_length=14,
    mfi_threshold_low=30,
)

# Exécution du backtest
print("🚀 Lancement du backtest...\n")
trades, equity, stats = backtest_smartbot_v2(data, params)

# Affichage du rapport TradingView style
print_tradingview_style_report(trades)

# Export CSV
export_tradingview_csv(trades, "test_tradingview_report.csv")

print("\n✨ Test terminé!")
