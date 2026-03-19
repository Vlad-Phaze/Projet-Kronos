"""
Gather intersection of base symbols present on Bybit, Binance, Kraken, Coinbase (via CoinGecko),
then query each exchange public API for open interest (when available) and pair volume.
Fetch market cap & coin volume from CoinGecko and output CSV ready for Google Sheets.

Outputs:
 - datafeed_tester/common_pairs_exchanges_open_interest.csv

Notes:
 - Some exchanges may not expose open interest publicly; script will put N/A in that case.
 - Respects basic rate limits by sleeping between requests.
"""

import requests
import pandas as pd
import time
import os
from collections import defaultdict

CG_BASE = "https://api.coingecko.com/api/v3"
EX_IDS = { 'bybit': 'bybit', 'binance': 'binance', 'kraken': 'kraken', 'coinbase': 'gdax' }
OUT_FILE = "common_pairs_exchanges_open_interest.csv"

session = requests.Session()
session.headers.update({ 'User-Agent': 'Projet-Kronos/1.0' })

# --- CoinGecko helpers ---

def cg_get_exchange_tickers(exchange_id, page=1):
    url = f"{CG_BASE}/exchanges/{exchange_id}/tickers"
    params = { 'page': page }
    r = session.get(url, params=params, timeout=30)
    if r.status_code != 200:
        print('CoinGecko error', exchange_id, r.status_code)
        return None
    return r.json()

# fetch all tickers (paginated) for an exchange
def fetch_all_tickers_for_exchange(exchange_id):
    tickers = []
    page = 1
    while True:
        res = cg_get_exchange_tickers(exchange_id, page)
        if not res or 'tickers' not in res:
            break
        page_t = res['tickers']
        if not page_t:
            break
        tickers.extend(page_t)
        print(f"{exchange_id}: fetched {len(page_t)} tickers (page {page})")
        if len(page_t) < 100:
            break
        page += 1
        time.sleep(1.1)
    print(f"{exchange_id}: total tickers {len(tickers)}")
    return tickers

# normalize base symbol (strip things like .d or digits) - keep uppercase

def normalize_symbol(s):
    if not s:
        return None
    s = s.strip().upper()
    # common alias
    if s == 'XBT':
        return 'BTC'
    return s


def normalize_quote(q):
    if not q:
        return None
    q = q.strip().upper()
    if q in ('USDT', 'USDC', 'USD', 'USD.T'):
        return 'USD'
    return q

def normalized_pair(base, quote):
    b = normalize_symbol(base)
    q = normalize_quote(quote)
    if not b or not q:
        return None
    return f"{b}/{q}"

# --- Exchange-specific open interest fetchers ---
# Each function returns tuple (open_interest_float_or_None, volume_quote_float_or_None)

# Binance futures
BINANCE_FAPI_EXCHANGE_INFO = None

def binance_find_symbol(base):
    global BINANCE_FAPI_EXCHANGE_INFO
    if BINANCE_FAPI_EXCHANGE_INFO is None:
        try:
            r = session.get('https://fapi.binance.com/fapi/v1/exchangeInfo', timeout=20)
            BINANCE_FAPI_EXCHANGE_INFO = r.json().get('symbols', [])
        except Exception as e:
            print('binance exchangeInfo error', e)
            BINANCE_FAPI_EXCHANGE_INFO = []
    wants = [base + 'USDT', base + 'USD', base + 'BUSD']
    for sym in BINANCE_FAPI_EXCHANGE_INFO:
        s = sym.get('symbol')
        if s in wants:
            return s
    # fallback: find any symbol that startswith base
    for sym in BINANCE_FAPI_EXCHANGE_INFO:
        s = sym.get('symbol')
        if s and s.startswith(base):
            return s
    return None

def binance_get_oi_and_vol(symbol):
    if not symbol:
        return (None, None)
    try:
        r = session.get('https://fapi.binance.com/fapi/v1/openInterest', params={'symbol': symbol}, timeout=10)
        if r.status_code == 200:
            oi = float(r.json().get('openInterest', 0))
        else:
            oi = None
        r2 = session.get('https://fapi.binance.com/fapi/v1/ticker/24hr', params={'symbol': symbol}, timeout=10)
        vol = None
        if r2.status_code == 200:
            j = r2.json()
            # quoteVolume is quoted in quote asset (e.g., USDT)
            vol = float(j.get('quoteVolume') or j.get('volume') or 0)
        return (oi, vol)
    except Exception as e:
        print('binance oi error', e)
        return (None, None)

# Bybit v2 open interest
def bybit_find_symbol(base):
    # common perp suffix USDT
    tries = [base + 'USDT', base + 'USD']
    for t in tries:
        # check tickers
        try:
            r = session.get('https://api.bybit.com/v2/public/tickers', params={'symbol': t}, timeout=10)
            if r.status_code == 200:
                data = r.json().get('result')
                if data:
                    return t
        except Exception:
            pass
    return None

def bybit_get_oi_and_vol(symbol):
    if not symbol:
        return (None, None)
    oi = None
    vol = None
    try:
        r = session.get('https://api.bybit.com/v2/public/open_interest', params={'symbol': symbol}, timeout=10)
        if r.status_code == 200:
            oi = float(r.json().get('result', {}).get('open_interest') or 0)
    except Exception as e:
        # try v5 as fallback
        try:
            r = session.get('https://api.bybit.com/v5/market/open-interest?symbol=' + symbol, timeout=10)
            if r.status_code == 200:
                oi = float(r.json().get('result', {}).get('open_interest') or 0)
        except Exception:
            pass
    try:
        r2 = session.get('https://api.bybit.com/v2/public/tickers', params={'symbol': symbol}, timeout=10)
        if r2.status_code == 200:
            res = r2.json().get('result')
            if res and isinstance(res, list):
                vol = float(res[0].get('volume') or 0)
    except Exception:
        pass
    return (oi, vol)

# Kraken Futures (futures.kraken.com) - attempt
def kraken_find_symbol(base):
    try:
        r = session.get('https://futures.kraken.com/derivatives/api/v3/instruments', timeout=10)
        if r.status_code != 200:
            return None
        for inst in r.json().get('instruments', []):
            # inst has "symbol" like "PI_XBTUSD" and "base" or "underlying"
            sym = inst.get('symbol') or inst.get('instrument')
            # underlying asset maybe 'XBT' or 'BTC'
            underlying = inst.get('underlying') or inst.get('base') or inst.get('baseCurrency')
            if underlying:
                u = underlying.upper()
                if u == 'XBT': u = 'BTC'
                if u == base:
                    return sym
    except Exception as e:
        print('kraken instruments error', e)
    return None

def kraken_get_oi_and_vol(symbol):
    if not symbol:
        return (None, None)
    try:
        r = session.get('https://futures.kraken.com/derivatives/api/v3/tickers', params={'symbol': symbol}, timeout=10)
        if r.status_code == 200:
            data = r.json().get('tickers') or []
            if data:
                t = data[0]
                oi = t.get('openInterest') or t.get('open_interest') or None
                vol = t.get('volume24h') or t.get('volume') or None
                try:
                    oi = float(oi) if oi is not None else None
                except:
                    oi = None
                try:
                    vol = float(vol) if vol is not None else None
                except:
                    vol = None
                return (oi, vol)
    except Exception as e:
        print('kraken oi error', e)
    return (None, None)

# Coinbase: likely no derivatives open interest - return None
def coinbase_get_oi_and_vol(base):
    return (None, None)

# --- Main flow ---

def main():
    # 1) fetch pairs directly from exchanges (spot + derivatives when available)
    exchange_pairs = { 'binance': {}, 'bybit': {}, 'kraken': {}, 'coinbase': {} }

    # BINANCE: spot + futures
    try:
        print('Fetching Binance spot symbols...')
        r = session.get('https://api.binance.com/api/v3/exchangeInfo', timeout=20)
        if r.status_code == 200:
            for s in r.json().get('symbols', []):
                base = s.get('baseAsset')
                quote = s.get('quoteAsset')
                norm = normalized_pair(base, quote)
                if norm:
                    # symbol for spot queries is like 'BTCUSDT'
                    exchange_pairs['binance'][norm] = exchange_pairs['binance'].get(norm, set()) | { s.get('symbol') }
    except Exception as e:
        print('Binance spot fetch error', e)
    try:
        print('Fetching Binance futures symbols...')
        r = session.get('https://fapi.binance.com/fapi/v1/exchangeInfo', timeout=20)
        if r.status_code == 200:
            for s in r.json().get('symbols', []):
                base = s.get('baseAsset')
                quote = s.get('quoteAsset')
                norm = normalized_pair(base, quote)
                if norm:
                    exchange_pairs['binance'][norm] = exchange_pairs['binance'].get(norm, set()) | { s.get('symbol') }
    except Exception as e:
        print('Binance futures fetch error', e)

    # BYBIT: try v5 instruments (linear, inverse, option) and v2/v3 fallbacks
    try:
        print('Fetching Bybit instruments...')
        for cat in ('linear', 'inverse'):
            r = session.get('https://api.bybit.com/v5/market/instruments-info', params={'category': cat}, timeout=20)
            if r.status_code == 200:
                for it in r.json().get('result', {}).get('list', []):
                    base = it.get('baseCoin') or it.get('base')
                    quote = it.get('quoteCoin') or it.get('quote')
                    sym = it.get('symbol')
                    norm = normalized_pair(base, quote)
                    if norm and sym:
                        exchange_pairs['bybit'][norm] = exchange_pairs['bybit'].get(norm, set()) | { sym }
    except Exception as e:
        print('Bybit fetch error', e)

    # KRAKEN: spot asset pairs from Kraken REST, futures from futures.kraken.com
    try:
        print('Fetching Kraken spot asset pairs...')
        r = session.get('https://api.kraken.com/0/public/AssetPairs', timeout=20)
        if r.status_code == 200:
            for k, v in (r.json().get('result') or {}).items():
                base = v.get('base')
                quote = v.get('quote')
                # base/quote might be like 'XXBT' -> strip leading X/Z
                def strip_pref(x):
                    if not x: return x
                    return x.lstrip('XZ')
                base_s = strip_pref(base)
                quote_s = strip_pref(quote)
                norm = normalized_pair(base_s, quote_s)
                if norm:
                    exchange_pairs['kraken'][norm] = exchange_pairs['kraken'].get(norm, set()) | { k }
    except Exception as e:
        print('Kraken spot fetch error', e)
    try:
        print('Fetching Kraken futures instruments...')
        r = session.get('https://futures.kraken.com/derivatives/api/v3/instruments', timeout=20)
        if r.status_code == 200:
            for it in r.json().get('instruments', []):
                base = it.get('underlying') or it.get('base')
                # symbol like 'PI_XBTUSD'
                sym = it.get('symbol')
                # quotes often USD
                quote = 'USD'
                norm = normalized_pair(base, quote)
                if norm:
                    exchange_pairs['kraken'][norm] = exchange_pairs['kraken'].get(norm, set()) | { sym }
    except Exception as e:
        print('Kraken futures fetch error', e)

    # COINBASE: products
    try:
        print('Fetching Coinbase products...')
        r = session.get('https://api.exchange.coinbase.com/products', timeout=20)
        if r.status_code == 200:
            for it in r.json():
                base = it.get('base_currency')
                quote = it.get('quote_currency')
                norm = normalized_pair(base, quote)
                if norm:
                    # coinbase symbol like 'BTC-USD'
                    exchange_pairs['coinbase'][norm] = exchange_pairs['coinbase'].get(norm, set()) | { it.get('id') }
    except Exception as e:
        print('Coinbase fetch error', e)

    # compute intersection across exchanges
    sets = [ set(exchange_pairs[ex].keys()) for ex in exchange_pairs ]
    common_pairs = set.intersection(*sets) if all(sets) else set()
    print(f'Found {len(common_pairs)} common normalized pairs across exchanges')
    if not common_pairs:
        print('No common pairs found. Exiting.')
        return

    # fetch coin list mapping symbol->id for CoinGecko market data
    print('Fetching CoinGecko coin list to map symbols -> ids...')
    r = session.get(f"{CG_BASE}/coins/list", timeout=30)
    coin_list = r.json() if r.status_code == 200 else []
    sym_to_id = {}
    for c in coin_list:
        if c.get('symbol'):
            sym_to_id[c['symbol'].upper()] = c['id']

    # for market data we'll map by base symbol
    symbols_list = sorted({ p.split('/')[0] for p in common_pairs })
    market_data = {}
    for i in range(0, len(symbols_list), 100):
        batch = symbols_list[i:i+100]
        ids = [sym_to_id.get(s) for s in batch if sym_to_id.get(s)]
        if not ids:
            continue
        params = { 'vs_currency': 'usd', 'ids': ','.join(ids), 'per_page': len(ids) }
        r = session.get(f"{CG_BASE}/coins/markets", params=params, timeout=30)
        if r.status_code == 200:
            for item in r.json():
                market_data[item['symbol'].upper()] = { 'market_cap': item.get('market_cap'), 'coin_volume_24h': item.get('total_volume') }
        time.sleep(1.2)

    # 3) for each common normalized pair, query exchanges for open interest and volume using the exchange-specific symbol
    rows = []
    for pair in sorted(common_pairs):
        base, quote = pair.split('/')
        row = { 'pair': pair, 'base': base, 'quote': quote }
        total_oi = 0.0
        total_vol = 0.0
        for ex in ('binance','bybit','kraken','coinbase'):
            symbols = exchange_pairs[ex].get(pair, set())
            ex_sym = next(iter(symbols)) if symbols else None
            row[f'{ex}_symbol'] = ex_sym
            oi = None
            vol = None
            if ex == 'binance':
                oi, vol = binance_get_oi_and_vol(ex_sym)
            elif ex == 'bybit':
                oi, vol = bybit_get_oi_and_vol(ex_sym)
            elif ex == 'kraken':
                oi, vol = kraken_get_oi_and_vol(ex_sym)
            elif ex == 'coinbase':
                # Coinbase has no derivs open interest, try product ticker for volume
                try:
                    if ex_sym:
                        r = session.get(f'https://api.exchange.coinbase.com/products/{ex_sym}/stats', timeout=10)
                        if r.status_code == 200:
                            vol = float(r.json().get('volume') or 0)
                except Exception:
                    vol = None
                oi = None
            row[f'{ex}_open_interest'] = oi
            row[f'{ex}_volume'] = vol
            if oi:
                total_oi += oi
            if vol:
                total_vol += vol
            time.sleep(0.15)

        row['total_open_interest'] = total_oi if total_oi else None
        row['total_volume_pairs'] = total_vol if total_vol else None
        md = market_data.get(base, {})
        row['market_cap_usd'] = md.get('market_cap') if md else None
        row['coin_volume_24h_usd'] = md.get('coin_volume_24h') if md else None
        try:
            row['volume_over_mcap'] = (total_vol / row['market_cap_usd']) if row['market_cap_usd'] else None
        except Exception:
            row['volume_over_mcap'] = None
        rows.append(row)

    df = pd.DataFrame(rows)
    outpath = os.path.join(os.path.dirname(__file__), OUT_FILE)
    df.to_csv(outpath, index=False)
    print('\nSaved CSV to', outpath)
    print(df.head(30).to_string(index=False))

if __name__ == '__main__':
    main()
