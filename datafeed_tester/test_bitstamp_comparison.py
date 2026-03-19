"""
Script de test pour comparer les données BITSTAMP avec TradingView
"""
import ccxt
import pandas as pd
from datetime import datetime

def fetch_bitstamp_data(symbol='BTC/USDT', start_date='2025-01-01', end_date='2026-01-01', timeframe='1h'):
    """Fetch data from Bitstamp for comparison"""
    exchange = ccxt.bitstamp()
    
    start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)
    
    all_ohlcv = []
    current_ts = start_ts
    
    print(f"📥 Fetching {symbol} from Bitstamp...")
    print(f"   Period: {start_date} → {end_date}")
    print(f"   Timeframe: {timeframe}")
    
    call_count = 0
    while current_ts < end_ts:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=current_ts, limit=1000)
            if not ohlcv:
                break
            
            all_ohlcv.extend(ohlcv)
            current_ts = ohlcv[-1][0] + 3600000  # +1 hour in ms
            call_count += 1
            
            if call_count % 5 == 0:
                print(f"   📊 Fetched {len(all_ohlcv)} candles so far...")
            
        except Exception as e:
            print(f"   ⚠️  Error: {e}")
            break
    
    # Convert to DataFrame
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    print(f"✅ Total: {len(df)} candles fetched")
    print(f"   First: {df['datetime'].iloc[0]}")
    print(f"   Last: {df['datetime'].iloc[-1]}")
    
    return df

def compare_with_tradingview(df, tv_first_entry='2025-01-07 16:00', tv_price=97915):
    """Compare with TradingView first entry"""
    print(f"\n🔍 Comparing with TradingView first entry:")
    print(f"   TradingView: {tv_first_entry} @ ${tv_price:,.0f}")
    
    # Find same timestamp in our data
    target_time = pd.to_datetime(tv_first_entry)
    close_match = df[df['datetime'] == target_time]
    
    if not close_match.empty:
        our_price = close_match['close'].iloc[0]
        diff = our_price - tv_price
        diff_pct = (diff / tv_price) * 100
        
        print(f"   Python/CCXT: {tv_first_entry} @ ${our_price:,.0f}")
        print(f"   Difference: ${diff:,.2f} ({diff_pct:+.4f}%)")
        
        if abs(diff_pct) < 0.01:
            print("   ✅ EXCELLENT - Prices match!")
        elif abs(diff_pct) < 0.1:
            print("   ✅ GOOD - Small difference")
        else:
            print("   ⚠️  WARNING - Significant difference")
    else:
        print(f"   ❌ Timestamp not found in data")
        # Find closest
        df['time_diff'] = abs(df['datetime'] - target_time)
        closest = df.loc[df['time_diff'].idxmin()]
        print(f"   Closest: {closest['datetime']} @ ${closest['close']:,.0f}")

if __name__ == "__main__":
    # Fetch Bitstamp data
    df = fetch_bitstamp_data()
    
    # Compare with TradingView's first trade
    compare_with_tradingview(df)
    
    # Save to CSV for inspection
    output_file = "bitstamp_btc_usdt_2025.csv"
    df.to_csv(output_file, index=False)
    print(f"\n💾 Data saved to: {output_file}")
