import re

print("🔍 Analyse du dernier backtest KuCoin\n")
print("="*80)

# Lire les logs
with open('/tmp/kronos-flask.log', 'r') as f:
    logs = f.read()

# Trouver le dernier backtest (chercher les marqueurs)
last_backtest_start = logs.rfind('🚀 Starting multi-asset backtest')
if last_backtest_start == -1:
    print("❌ Aucun backtest trouvé dans les logs")
    exit(1)

# Extraire la section du dernier backtest
last_backtest = logs[last_backtest_start:]

print("📊 PARAMÈTRES DU BACKTEST")
print("-"*80)

# Extraire les paramètres
params_patterns = {
    'Exchange': r'Exchange: (\w+)',
    'Period': r'Period: ([\d-]+) → ([\d-]+)',
    'Timeframe': r'Timeframe: (\w+)',
    'Capital': r'Capital: \$?([\d,]+)',
    'Max Active Trades': r'Max Active Trades: (\d+)',
    'Base Order Size': r'Base Order Size: ([\d.]+)%',
    'Safety Order Scale': r'Safety Order Volume Scale: ([\d.]+)x',
    'Take Profit': r'Take Profit: ([\d.]+)%',
    'Fees': r'Fees: ([\d.]+)',
    'Slippage': r'Slippage: ([\d.]+)',
}

for param, pattern in params_patterns.items():
    match = re.search(pattern, last_backtest)
    if match:
        if param == 'Period':
            print(f"   {param}: {match.group(1)} → {match.group(2)}")
        else:
            print(f"   {param}: {match.group(1)}")

# Assets
print("\n📦 ASSETS")
print("-"*80)

assets_requested = re.search(r'Requested (\d+) assets', last_backtest)
assets_with_data = re.search(r'(\d+) assets with data', last_backtest)
assets_trading = re.search(r'(\d+) assets will trade', last_backtest)

if assets_requested:
    print(f"   Requested: {assets_requested.group(1)}")
if assets_with_data:
    print(f"   With data: {assets_with_data.group(1)}")
if assets_trading:
    print(f"   Trading: {assets_trading.group(1)}")

# Capital allocation
capital_per_asset = re.search(r'Capital per trading asset: \$?([\d,]+\.?\d*)', last_backtest)
if capital_per_asset:
    print(f"   Capital per asset: ${capital_per_asset.group(1)}")

# Gating statistics
print("\n⚙️  GATING STATISTICS")
print("-"*80)

gating_stats = {
    'Max positions reached': r'Max simultaneous positions reached: (\d+) / (\d+)',
    'Total signals': r'Total entry signals: (\d+)',
    'Allowed': r'Entries allowed: (\d+) \(([\d.]+)%\)',
    'Blocked': r'Entries blocked: (\d+) \(([\d.]+)%\)',
}

for stat, pattern in gating_stats.items():
    match = re.search(pattern, last_backtest)
    if match:
        if stat == 'Max positions reached':
            print(f"   {stat}: {match.group(1)}/{match.group(2)}")
        elif stat in ['Allowed', 'Blocked']:
            print(f"   {stat}: {match.group(1)} ({match.group(2)}%)")
        else:
            print(f"   {stat}: {match.group(1)}")

# Résultats finaux
print("\n💰 RÉSULTATS")
print("-"*80)

# Chercher dans tout le backtest les valeurs finales
final_patterns = {
    'Start Value': r'Start Value[:\s]+\$?([\d,]+\.?\d*)',
    'End Value': r'End Value[:\s]+\$?([\d,]+\.?\d*)',
    'Total Return': r'Total Return[:\s]+\$?([-\d,]+\.?\d*)',
    'Total Return %': r'Return \[%\][:\s]+([-\d.]+)',
    'Max Drawdown': r'Max Drawdown \[%\][:\s]+([-\d.]+)',
    'Win Rate': r'Win Rate \[%\][:\s]+([\d.]+)',
    'Total Trades': r'Total Trades[:\s]+(\d+)',
}

found_results = False
for metric, pattern in final_patterns.items():
    match = re.search(pattern, last_backtest)
    if match:
        found_results = True
        value = match.group(1)
        print(f"   {metric}: {value}")

if not found_results:
    print("   ⚠️  Résultats finaux non trouvés - le backtest est peut-être encore en cours")
    print("\n   Vérification si le backtest s'est terminé...")
    if 'Combined Portfolio Statistics' in last_backtest:
        print("   ✅ Section 'Combined Portfolio Statistics' trouvée")
    else:
        print("   ❌ Backtest incomplet dans les logs")

# Vérifier les problèmes potentiels
print("\n🔧 DIAGNOSTIC")
print("-"*80)

issues = []

# Check 1: Capital utilisé
if capital_per_asset and assets_trading:
    try:
        cap_per = float(capital_per_asset.group(1).replace(',', ''))
        n_trading = int(assets_trading.group(1))
        total_allocated = cap_per * n_trading
        print(f"   Capital total alloué: ${total_allocated:,.2f}")
        
        if total_allocated < 9000:
            issues.append(f"⚠️  Seulement ${total_allocated:,.2f} alloué sur $10,000")
    except:
        pass

# Check 2: Base Order Size
if 'Base Order Size' in str(params_patterns):
    base_order = re.search(r'Base Order Size: ([\d.]+)%', last_backtest)
    if base_order:
        bos = float(base_order.group(1))
        if bos < 1:
            issues.append(f"⚠️  Base Order Size très faible: {bos}%")

# Check 3: Nombre de trades
total_trades_match = re.search(r'Total Trades[:\s]+(\d+)', last_backtest)
if total_trades_match:
    total_trades = int(total_trades_match.group(1))
    if total_trades == 0:
        issues.append("❌ AUCUN trade exécuté!")
    elif total_trades < 10:
        issues.append(f"⚠️  Très peu de trades: {total_trades}")

if issues:
    print("\n   Problèmes détectés:")
    for issue in issues:
        print(f"   {issue}")
else:
    print("   ✅ Aucun problème évident détecté")

print("\n" + "="*80)

