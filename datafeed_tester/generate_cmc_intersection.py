import requests
import pandas as pd
import time
import os

API_KEY = "5098e2ddfd02478e8adc6d2e06b570a5"
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE = "https://pro-api.coinmarketcap.com"

EXCHANGE_SEARCH = ["bybit", "binance", "kraken", "coinbase"]

OUT_FILE = "cmc_common_pairs.csv"

# helper
def cmc_get(path, params=None):
    url = BASE + path
    for attempt in range(3):
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            print("Rate limited by CMC, sleeping 60s...")
            time.sleep(60)
            continue
        else:
            print("CMC API error", r.status_code, r.text[:200])
            time.sleep(5)
    return None

# 1) get exchange ids
print("Retrieving exchange map from CMC...")
ex_map = cmc_get("/v1/exchange/map")
if not ex_map or "data" not in ex_map:
    raise SystemExit("Failed to fetch exchange map")

id_map = {}
for e in ex_map["data"]:
    slug = str(e.get("slug", "")).lower()
    name = str(e.get("name", "")).lower()
    id_map[slug] = e
    id_map[name] = e

# find best matches
exchanges = {}
for wanted in EXCHANGE_SEARCH:
    found = None
    # try slug
    for key in id_map:
        if wanted in key:
            found = id_map[key]
            break
    if not found:
        print("Warning: exchange not found in map:", wanted)
    else:
        exchanges[wanted] = found["id"]
        print(f"Mapped {wanted} -> id {found['id']} ({found.get('name')})")

# 2) fetch market-pairs for each exchange (paginated)
exchange_pairs = {}
for ex_name, ex_id in exchanges.items():
    print(f"\nFetching pairs for {ex_name} (id {ex_id})")
    pairs = []
    start = 1
    limit = 100
    while True:
        params = {"exchange_id": ex_id, "start": start, "limit": limit}
        res = cmc_get("/v1/exchange/market-pairs/latest", params=params)
        if not res or "data" not in res:
            break
        data = res["data"]
        if not data:
            break
        pairs.extend(data)
        print(f"  got {len(data)} pairs (start {start})")
        if len(data) < limit:
            break
        start += limit
        time.sleep(2)
    print(f"  total pairs fetched: {len(pairs)}")
    exchange_pairs[ex_name] = pairs

# 3) normalize base symbols and collect info: symbol, pair string, volume, open_interest
print('\nProcessing pairs and extracting base symbols...')
ex_bases = {}
ex_pair_info = {}
for ex_name, pairs in exchange_pairs.items():
    bases = set()
    info = {}
    for p in pairs:
        # p structure: has 'market_pair' or 'marketPair'? coinmarketcap structure varies
        # Try to extract base/quote
        base = None
        quote = None
        volume = 0.0
        open_interest = 0.0
        pair_str = None
        try:
            pair_str = p.get('market_pair') or p.get('marketPair') or p.get('pair') or p.get('symbol')
            if pair_str and '/' in pair_str:
                b,q = pair_str.split('/')[:2]
                base = b.upper(); quote = q.upper()
            else:
                # fallback to baseCurrency/quoteCurrency
                base = p.get('base_currency_symbol') or p.get('base_symbol') or p.get('baseCurrency')
                quote = p.get('quote_currency_symbol') or p.get('quote_symbol') or p.get('quoteCurrency')
                if base: base = base.upper()
                if quote: quote = quote.upper()
            # volume: 'quote' info or 'volume_24h'
            volume = p.get('volume_24h') or p.get('quote', {}).get('volume_24h') or p.get('volume') or 0
            # open interest may be 'open_interest' or inside 'open_interest' key
            open_interest = p.get('open_interest') or p.get('openInterest') or 0
        except Exception:
            continue
        if not base:
            continue
        bases.add(base)
        key = base
        # store representative pair string and numbers (accumulate if multiple pairs for same base)
        if key not in info:
            info[key] = { 'pairs': set(), 'volume': 0.0, 'open_interest': 0.0 }
        if pair_str:
            info[key]['pairs'].add(str(pair_str))
        try:
            info[key]['volume'] += float(volume or 0)
        except:
            pass
        try:
            info[key]['open_interest'] += float(open_interest or 0)
        except:
            pass
    ex_bases[ex_name] = bases
    ex_pair_info[ex_name] = info
    print(f"{ex_name}: {len(bases)} unique base symbols")

# 4) intersection of bases across all 4 exchanges
common_bases = set.intersection(*(s for s in ex_bases.values()))
print(f"\nCommon bases across all exchanges: {len(common_bases)}")

# 5) get market cap and total volume per coin from CMC quotes endpoint in batches
print('\nFetching market cap and coin volume info from CMC...')
cmc_symbols = list(common_bases)
symbol_to_mcap = {}
symbol_to_volume = {}
# CMC quotes endpoint expects comma separated symbols
# do in batches of 50
for i in range(0, len(cmc_symbols), 50):
    batch = cmc_symbols[i:i+50]
    symbols_param = ','.join(batch)
    params = { 'symbol': symbols_param }
    res = cmc_get('/v1/cryptocurrency/quotes/latest', params=params)
    if not res or 'data' not in res:
        time.sleep(2); continue
    for sym, obj in res['data'].items():
        q = obj.get('quote', {}).get('USD', {})
        mcap = q.get('market_cap') or 0
        vol = q.get('volume_24h') or 0
        symbol_to_mcap[sym.upper()] = mcap
        symbol_to_volume[sym.upper()] = vol
    time.sleep(2)

# 6) build final table for common bases
rows = []
for base in sorted(common_bases):
    row = {'symbol': base}
    total_open_interest = 0.0
    total_volume_pairs = 0.0
    # per exchange details
    for ex in exchanges.keys():
        info = ex_pair_info.get(ex, {}).get(base, {})
        pairs_join = ','.join(sorted(info.get('pairs', []))[:5]) if info else ''
        oi = info.get('open_interest', 0.0) if info else 0.0
        vol = info.get('volume', 0.0) if info else 0.0
        row[f'{ex}_pairs'] = pairs_join
        row[f'{ex}_open_interest'] = oi
        row[f'{ex}_volume_pairs'] = vol
        total_open_interest += oi
        total_volume_pairs += vol
    row['total_open_interest'] = total_open_interest
    # market cap & volume from CMC
    row['market_cap_usd'] = symbol_to_mcap.get(base, '')
    row['coin_volume_24h_usd'] = symbol_to_volume.get(base, '')
    # volume per market cap
    try:
        row['volume_over_mcap'] = float(total_volume_pairs) / float(row['market_cap_usd']) if row['market_cap_usd'] else None
    except Exception:
        row['volume_over_mcap'] = None
    row['total_volume_pairs'] = total_volume_pairs
    rows.append(row)

# create dataframe and save CSV
df = pd.DataFrame(rows)
# reorder columns
cols = ['symbol']
for ex in exchanges.keys():
    cols += [f'{ex}_pairs', f'{ex}_open_interest', f'{ex}_volume_pairs']
cols += ['total_open_interest','total_volume_pairs','market_cap_usd','coin_volume_24h_usd','volume_over_mcap']

df = df[cols]

outpath = os.path.join(os.path.dirname(__file__), OUT_FILE)
df.to_csv(outpath, index=False)
print(f"\nSaved to {outpath}")
print(df.head(20).to_string(index=False))
