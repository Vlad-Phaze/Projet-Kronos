"""
For each pair in common_pairs_exchanges_open_interest_filtered.csv, fetch market cap from CoinGecko and
sum 24h trading volume from CoinGecko tickers for that pair (quote USD normalized from USDT/USDC/USD).
Output CSV: pair_vol_mcap_coingecko.csv with columns:
 pair, market_cap_usd, pair_volume_24h_usd, vol_over_mcap_pct
"""
import requests, time, os, csv
from math import isfinite

CG_BASE = 'https://api.coingecko.com/api/v3'
IN_FILE = 'common_pairs_exchanges_open_interest_filtered.csv'
OUT_FILE = 'pair_vol_mcap_coingecko.csv'

session = requests.Session()
session.headers.update({'User-Agent':'Projet-Kronos/1.0'})


def normalize_symbol(s):
    if not s:
        return None
    s = str(s).strip().upper()
    if s == 'XBT': return 'BTC'
    return s

def normalize_quote(q):
    if not q:
        return None
    q = str(q).strip().upper()
    if q in ('USDT','USDC','USD','USD.T'):
        return 'USD'
    return q

def normalized_pair(base, quote):
    b = normalize_symbol(base)
    q = normalize_quote(quote)
    if not b or not q:
        return None
    return f"{b}/{q}"

# load pairs
base_path = os.path.dirname(__file__)
inpath = os.path.join(base_path, IN_FILE)
outpath = os.path.join(base_path, OUT_FILE)
if not os.path.exists(inpath):
    print('Input file not found:', inpath)
    raise SystemExit(1)

pairs = []
with open(inpath, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for r in reader:
        p = r.get('pair')
        if not p:
            b = r.get('base')
            q = 'USD'
            p = normalized_pair(b,q)
        pairs.append(p.upper())

pairs = sorted(set(pairs))
print('Pairs to process:', len(pairs))

# map base symbols to coin ids via /coins/list
print('Fetching CoinGecko coin list...')
try:
    r = session.get(CG_BASE + '/coins/list', timeout=30)
    r.raise_for_status()
    coin_list = r.json()
except Exception as e:
    print('Failed to fetch coin list', e)
    coin_list = []

sym_to_id = {}
for c in coin_list:
    sym = c.get('symbol')
    cid = c.get('id')
    if sym and cid:
        sym_to_id[sym.upper()] = cid

# prepare list of unique bases
bases = sorted({p.split('/')[0] for p in pairs})
print('Unique bases:', len(bases))

# fetch market caps in batches via /coins/markets
market_data = {}
batch = []
for b in bases:
    cid = sym_to_id.get(b)
    if cid:
        batch.append(cid)
    else:
        market_data[b] = {'market_cap': None, 'coin_volume_24h': None}

# batch in chunks of 100
for i in range(0, len(batch), 100):
    ids = batch[i:i+100]
    params = {'vs_currency':'usd','ids':','.join(ids),'per_page':len(ids)}
    try:
        r = session.get(CG_BASE + '/coins/markets', params=params, timeout=30)
        r.raise_for_status()
        for item in r.json():
            sym = item.get('symbol','').upper()
            market_data[sym] = {'market_cap': item.get('market_cap'), 'coin_volume_24h': item.get('total_volume')}
    except Exception as e:
        print('Error fetching markets batch', e)
    time.sleep(1.2)

# for each coin, fetch tickers and sum volumes for tickers matching normalized pair (target USD)
pair_results = {}
for p in pairs:
    pair_results[p] = {'market_cap_usd': None, 'pair_volume_24h_usd': 0.0}

# We'll fetch tickers per coin id
for b in bases:
    cid = sym_to_id.get(b)
    if not cid:
        # no coin id
        continue
    # map coin market cap
    mc = market_data.get(b, {}).get('market_cap') or None
    # iterate tickers pages
    page = 1
    per_page = 100
    total_volume_by_pair = {}
    while True:
        url = f"{CG_BASE}/coins/{cid}/tickers?page={page}"
        try:
            r = session.get(url, timeout=30)
            if r.status_code != 200:
                # break on errors
                break
            data = r.json()
            tickers = data.get('tickers', [])
            if not tickers:
                break
            for t in tickers:
                base_symbol = t.get('base') or t.get('coin_id') or ''
                target_symbol = t.get('target') or t.get('converted_last',{}).get('usd')
                if not base_symbol or not target_symbol:
                    continue
                bnorm = normalize_symbol(base_symbol)
                qnorm = normalize_quote(target_symbol)
                pnorm = f"{bnorm}/{qnorm}"
                vol = t.get('volume') or 0
                try:
                    volf = float(vol)
                except:
                    volf = 0.0
                if qnorm == 'USD':
                    total_volume_by_pair[pnorm] = total_volume_by_pair.get(pnorm, 0.0) + volf
            # paginate
            if len(tickers) < per_page:
                break
            page += 1
            time.sleep(1.1)
        except Exception as e:
            print('Tickers fetch error', cid, e)
            break
    # write results into pair_results for pairs that match this base
    for p in pairs:
        if p.startswith(b + '/'):
            pair_results[p]['market_cap_usd'] = mc
            pair_results[p]['pair_volume_24h_usd'] = total_volume_by_pair.get(p.upper(), 0.0)

# write output CSV
with open(outpath, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['pair','market_cap_usd','pair_volume_24h_usd','vol_over_mcap_pct'])
    for p in pairs:
        mc = pair_results[p]['market_cap_usd']
        vol = pair_results[p]['pair_volume_24h_usd']
        if mc and mc != 0:
            pct = (vol / mc) * 100
        else:
            pct = ''
        writer.writerow([p, mc if mc is not None else '', vol if vol is not None else 0, pct])

print('Saved', outpath)
