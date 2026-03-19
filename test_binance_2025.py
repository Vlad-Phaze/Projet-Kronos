import ccxt
from datetime import datetime, timedelta
import time

# Paires à tester
pairs_to_test = ['GRT', 'AERO', 'FARTCOIN', 'MON', 'POPCAT', 'SPX', 'HYPE', 'FLR', 'KAS', 'XMR']

# Initialiser Binance
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

print("🔍 Test de disponibilité des paires sur Binance pour 2025\n")
print("="*80)

# Charger les marchés
try:
    markets = exchange.load_markets()
    print(f"✅ Connecté à Binance - {len(markets)} marchés disponibles\n")
except Exception as e:
    print(f"❌ Erreur de connexion: {e}")
    exit(1)

# Période de test: 2025
start_date = datetime(2025, 1, 1)
end_date = datetime(2025, 12, 31)
since = int(start_date.timestamp() * 1000)

results = []

for base in pairs_to_test:
    symbol = f"{base}/USDT"
    print(f"\n📊 Test: {symbol}")
    print("-" * 40)
    
    # Vérifier si le symbole existe
    if symbol not in markets:
        print(f"❌ Symbole {symbol} NON DISPONIBLE sur Binance")
        results.append({
            'pair': base,
            'symbol': symbol,
            'available': False,
            'reason': 'Symbole non listé sur Binance',
            'data_2025': False
        })
        continue
    
    print(f"✅ Symbole existe sur Binance")
    
    # Vérifier la date de listing
    market_info = markets[symbol]
    print(f"   Market Info: {market_info.get('info', {}).get('status', 'N/A')}")
    
    # Tester la récupération de données pour 2025
    try:
        print(f"   Tentative de récupération OHLCV pour 2025...")
        ohlcv = exchange.fetch_ohlcv(symbol, '1d', since=since, limit=10)
        
        if ohlcv and len(ohlcv) > 0:
            first_candle_date = datetime.fromtimestamp(ohlcv[0][0] / 1000)
            last_candle_date = datetime.fromtimestamp(ohlcv[-1][0] / 1000)
            print(f"   ✅ Données disponibles")
            print(f"   📅 Première bougie: {first_candle_date}")
            print(f"   📅 Dernière bougie: {last_candle_date}")
            
            # Vérifier si les données sont en 2025
            has_2025_data = any(datetime.fromtimestamp(c[0]/1000).year == 2025 for c in ohlcv)
            
            results.append({
                'pair': base,
                'symbol': symbol,
                'available': True,
                'data_2025': has_2025_data,
                'first_date': first_candle_date,
                'last_date': last_candle_date,
                'candles_fetched': len(ohlcv)
            })
        else:
            print(f"   ⚠️  Aucune donnée retournée")
            results.append({
                'pair': base,
                'symbol': symbol,
                'available': True,
                'data_2025': False,
                'reason': 'Aucune donnée OHLCV disponible'
            })
    
    except Exception as e:
        print(f"   ❌ Erreur lors de la récupération: {str(e)}")
        results.append({
            'pair': base,
            'symbol': symbol,
            'available': True,
            'data_2025': False,
            'reason': f'Erreur: {str(e)}'
        })
    
    time.sleep(0.5)  # Rate limiting

# Résumé
print("\n" + "="*80)
print("📋 RÉSUMÉ DES RÉSULTATS")
print("="*80)

print("\n✅ Paires AVEC données 2025:")
for r in results:
    if r.get('data_2025'):
        print(f"   - {r['pair']}: {r.get('first_date', 'N/A')} → {r.get('last_date', 'N/A')}")

print("\n❌ Paires SANS données 2025:")
for r in results:
    if not r.get('data_2025'):
        reason = r.get('reason', 'Inconnue')
        print(f"   - {r['pair']}: {reason}")

print("\n📊 Statistiques:")
total = len(results)
with_data = sum(1 for r in results if r.get('data_2025'))
without_data = total - with_data
print(f"   Total: {total}")
print(f"   Avec données 2025: {with_data} ({with_data/total*100:.1f}%)")
print(f"   Sans données 2025: {without_data} ({without_data/total*100:.1f}%)")

