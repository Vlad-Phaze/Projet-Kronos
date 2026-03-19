#!/usr/bin/env python3
"""
Test quel exchange a le plus de couverture pour les 84 paires
"""
import ccxt
import pandas as pd
from datetime import datetime

# Les 84 paires de la liste complète
CRYPTO_LIST = [
    'BTC', 'ETH', 'BNB', 'BCH', 'SOL', 'AAVE', 'LTC', 'LINK', 'ETC', 'EIGEN',
    'UNI', 'INJ', 'ICP', 'PEPE', 'BAT', 'WLD', 'SKY', 'BONK', 'SHIB', 'PENGU',
    'TIA', 'XPL', 'TON', 'XLM', 'ATOM', 'ZK', 'GRT', 'ALGO', 'POL', 'FET',
    'WLFI', 'HBAR', 'TRUMP', 'COMP', 'APT', 'SEI', 'ASTER', 'PUMP', 'ONDO', 'ENA',
    'ADA', 'STRK', 'ARB', 'WIF', 'AVAX', 'DOT', 'NEAR', 'RENDER', 'SUI', 'CRV',
    'FIL', 'QNT', 'XRP', 'LDO', 'AERO', 'AVNT', 'CHZ', 'DASH', 'DOGE', 'FARTCOIN',
    'JASMY', 'KAITO', 'LRC', 'MANA', 'MON', 'MORPHO', 'OP', 'PAXG', 'POPCAT', 'PYTH',
    'TAO', 'VIRTUAL', 'VET', 'ZEC', 'SPX', 'CAKE', 'HYPE', 'FLR', 'KAS', 'TRX',
    'STX', 'XMR', 'XTZ', 'FLOKI'
]

# Exchanges à tester
EXCHANGES = {
    'binance': ccxt.binance(),
    'coinbase': ccxt.coinbase(),
    'kucoin': ccxt.kucoin(),
    'okx': ccxt.okx(),
    'bybit': ccxt.bybit(),
    'bitfinex': ccxt.bitfinex(),
    'bitstamp': ccxt.bitstamp()
}

def test_exchange_coverage(exchange_name, exchange_obj, bases, timeframe='1h', limit=100):
    """
    Teste combien de paires sont disponibles sur un exchange
    """
    print(f"\n🔍 Test de {exchange_name}...")
    
    available = []
    unavailable = []
    
    try:
        # Charger les marchés
        markets = exchange_obj.load_markets()
        
        for base in bases:
            symbol = f"{base}/USDT"
            
            # Vérifier si le symbole existe
            if symbol in markets:
                try:
                    # Essayer de fetcher quelques barres pour confirmer
                    ohlcv = exchange_obj.fetch_ohlcv(symbol, timeframe, limit=limit)
                    if len(ohlcv) > 0:
                        available.append(base)
                        print(f"  ✅ {base}: {len(ohlcv)} barres")
                    else:
                        unavailable.append(base)
                        print(f"  ⚠️  {base}: 0 barres")
                except Exception as e:
                    unavailable.append(base)
                    print(f"  ❌ {base}: Erreur fetch - {str(e)[:50]}")
            else:
                unavailable.append(base)
                print(f"  ❌ {base}: Marché non disponible")
                
    except Exception as e:
        print(f"  ❌ ERREUR EXCHANGE: {e}")
        return {'available': [], 'unavailable': bases, 'error': str(e)}
    
    return {
        'available': available,
        'unavailable': unavailable,
        'count': len(available),
        'percentage': len(available) / len(bases) * 100
    }

def main():
    print("=" * 70)
    print("🔎 TEST DE COUVERTURE DES EXCHANGES POUR 84 PAIRES CRYPTO")
    print("=" * 70)
    print(f"Période de test: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Nombre de paires à tester: {len(CRYPTO_LIST)}")
    print(f"Exchanges à tester: {', '.join(EXCHANGES.keys())}")
    
    results = {}
    
    # Tester chaque exchange
    for exchange_name, exchange_obj in EXCHANGES.items():
        results[exchange_name] = test_exchange_coverage(
            exchange_name, 
            exchange_obj, 
            CRYPTO_LIST
        )
    
    # Résumé
    print("\n" + "=" * 70)
    print("📊 RÉSUMÉ DE LA COUVERTURE")
    print("=" * 70)
    
    # Trier par nombre de paires disponibles
    sorted_results = sorted(
        results.items(), 
        key=lambda x: x[1].get('count', 0), 
        reverse=True
    )
    
    print(f"\n{'Exchange':<15} {'Disponibles':<15} {'Pourcentage':<15} {'Manquantes'}")
    print("-" * 70)
    
    for exchange_name, result in sorted_results:
        if 'error' in result:
            print(f"{exchange_name:<15} {'ERREUR':<15} {'N/A':<15} {result['error'][:30]}")
        else:
            count = result['count']
            percentage = result['percentage']
            missing = len(result['unavailable'])
            print(f"{exchange_name:<15} {count:<15} {percentage:>6.2f}%       {missing}")
    
    # Meilleur exchange
    best_exchange = sorted_results[0]
    print("\n" + "=" * 70)
    print(f"🏆 MEILLEUR EXCHANGE: {best_exchange[0].upper()}")
    print(f"   Couverture: {best_exchange[1]['count']}/{len(CRYPTO_LIST)} paires ({best_exchange[1]['percentage']:.2f}%)")
    print("=" * 70)
    
    # Paires manquantes sur le meilleur exchange
    if best_exchange[1]['unavailable']:
        print(f"\n⚠️  Paires manquantes sur {best_exchange[0]}:")
        print(f"   {', '.join(best_exchange[1]['unavailable'])}")
    
    # Sauvegarder les résultats
    df = pd.DataFrame([
        {
            'Exchange': name,
            'Disponibles': result.get('count', 0),
            'Pourcentage': result.get('percentage', 0),
            'Manquantes': len(result.get('unavailable', []))
        }
        for name, result in sorted_results
    ])
    
    df.to_csv('exchange_coverage_report.csv', index=False)
    print(f"\n💾 Rapport sauvegardé: exchange_coverage_report.csv")

if __name__ == '__main__':
    main()
