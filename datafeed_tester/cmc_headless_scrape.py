"""
Use Playwright to render CoinMarketCap exchange markets pages and extract market rows.
Find normalized pairs from `common_pairs_exchanges_open_interest.csv` and enrich with CMC volumes/open_interest when available.

Output: common_pairs_exchanges_open_interest_cmc_headless.csv
"""
from playwright.sync_api import sync_playwright
import pandas as pd
import os
import time

IN_FILE = 'common_pairs_exchanges_open_interest.csv'
OUT_FILE = 'common_pairs_exchanges_open_interest_cmc_headless.csv'

BASE = os.path.dirname(__file__)
IN_PATH = os.path.join(BASE, IN_FILE)
OUT_PATH = os.path.join(BASE, OUT_FILE)

if not os.path.exists(IN_PATH):
    print('Input CSV not found:', IN_PATH)
    raise SystemExit(1)

df = pd.read_csv(IN_PATH)
if 'pair' not in df.columns:
    df['pair'] = df['base'].astype(str).str.upper() + '/' + df['quote'].astype(str).str.upper()
pairs_set = set(df['pair'].astype(str).str.upper().tolist())

# target exchanges to search
TARGETS = ['binance','bybit','kraken','coinbase']

results = { p: {} for p in pairs_set }

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    # fetch exchanges index to resolve slugs
    page.goto('https://coinmarketcap.com/rankings/exchanges/', timeout=60000)
    page.wait_for_timeout(2000)
    # extract exchange links
    ex_links = page.evaluate('''() => Array.from(document.querySelectorAll('a.cmc-link')).map(a => ({href:a.href, text:a.textContent}))''')
    slug_map = {}
    for e in ex_links:
        href = e.get('href') or ''
        text = (e.get('text') or '').lower()
        for t in TARGETS:
            if t in text and t not in slug_map:
                # href like https://coinmarketcap.com/exchanges/binance/
                parts = href.rstrip('/').split('/')
                if 'exchanges' in parts:
                    slug = parts[-1]
                    slug_map[t] = slug
    # fallback: default slugs
    for t in TARGETS:
        if t not in slug_map:
            slug_map[t] = t

    print('Resolved slugs:', slug_map)

    for ex_key, slug in slug_map.items():
        print('Processing exchange', ex_key, '->', slug)
        url = f'https://coinmarketcap.com/exchanges/{slug}/markets/'
        page.goto(url, timeout=60000)
        page.wait_for_timeout(3000)
        # attempt to load more until no new rows or until we've found all pairs
        seen = set()
        found_count = 0
        for _ in range(20):
            # collect rows
            rows = page.query_selector_all('table tbody tr')
            for r in rows:
                try:
                    cols = r.query_selector_all('td')
                    # pair is in a cell with symbol text, try to find something like 'BTC/USDT'
                    text = r.inner_text()
                    # naive extract: find first occurrence of pattern X/Y
                    import re
                    m = re.search(r"([A-Z0-9\-\.]+)\s*/\s*([A-Z0-9\-\.]+)", text)
                    if not m:
                        continue
                    base = m.group(1).upper()
                    quote = m.group(2).upper()
                    if quote in ('USDT','USDC'):
                        quote = 'USD'
                    pair = f"{base}/{quote}"
                    if pair in pairs_set:
                        # extract volume and open interest if present
                        # volume often in a column like '$1,234,567'
                        cols_text = [c.inner_text() for c in cols]
                        vol = None
                        oi = None
                        for ct in cols_text:
                            if '$' in ct and (',' in ct or ct.strip().endswith('K') or ct.strip().endswith('M')):
                                # crude pick for volume
                                vol = ct.strip()
                                break
                        # open interest may be present as 'Open Interest' column or not
                        for ct in cols_text:
                            if 'Open Interest' in ct or 'Open interest' in ct or 'Open Interest' in r.inner_text():
                                oi = ct
                        results[pair].setdefault(ex_key, [])
                        results[pair][ex_key].append({'vol_text': vol, 'oi_text': oi, 'row_text': text})
                except Exception:
                    continue
            # try click load more
            try:
                btn = page.query_selector('button:has-text("Load More")')
                if btn and btn.is_enabled():
                    btn.click()
                    page.wait_for_timeout(1500)
                    continue
            except Exception:
                pass
            break

    browser.close()

# merge results back into df
for idx, row in df.iterrows():
    p = row['pair'].upper()
    exdata = results.get(p, {})
    for ex in TARGETS:
        entries = exdata.get(ex)
        if entries:
            # take first
            e = entries[0]
            df.at[idx, f'cmc_{ex}_vol_text'] = e.get('vol_text')
            df.at[idx, f'cmc_{ex}_oi_text'] = e.get('oi_text')
            df.at[idx, f'cmc_{ex}_row'] = e.get('row_text')

# save
df.to_csv(OUT_PATH, index=False)
print('Saved to', OUT_PATH)
