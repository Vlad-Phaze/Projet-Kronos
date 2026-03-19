# Pour rendre l'import explicite
__all__ = [
    "compare_exchanges_on_bases",
    "expand_coin_inputs",
    "fetch_top_markets",
    "EXCHANGES",
]

from typing import List, Dict, Optional, Tuple
import math
import threading

# Compteur global pour tracer les appels API
_api_call_counter = 0
_api_call_lock = threading.Lock()
import time
from datetime import datetime, timedelta, timezone
import difflib
import requests
import re

import ccxt
import numpy as np
import pandas as pd

# =========================
# CONFIG PAR DÉFAUT
# =========================
EXCHANGES = [
    "binance", "coinbase", "kraken", "kucoin", "okx",
    "bybit", "gate", "bitfinex", "bitstamp"
    # "huobi", "htx" parfois sources d'erreurs SSL/CA selon l'environnement
]
TIMEFRAME = "1h"
LOOKBACK_DAYS = 30
RATE_LIMIT_SLEEP = 0.5

# Devises préférées pour choisir la meilleure paire
PREFERRED_QUOTES = ("USDT", "USD", "USDC", "EUR", "BTC")

# Score “parfait”
PERFECT_SCORE = 1.000

# Seuil Large Cap (par rang CoinGecko) pour l’expansion "Large Cap"
LARGE_CAP_RANK_MAX = 20

# Pondérations (somme = 1)
WEIGHTS = {
    "completeness": 0.35,
    "continuity": 0.20,
    "price_dev": 0.20,
    "timestamp_drift": 0.15,
    "volume_quality": 0.10,  # (1 - excès de volume)
}

# Tolérances pour transformer des métriques en scores [0..1]
PRICE_DEV_TOL = 0.0025       # 0.25% de déviation moyenne (médiane) ≈ score 0
DRIFT_TOL_FRAC = 0.10        # 10% de la durée de bougie ≈ score 0
VOL_OUTLIER_Z = 5.0          # seuil z-robuste pour volume “excessif”

# =========================
# OUTILS DE TEMPS
# =========================
_TIMEFRAME_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
    "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000, "1w": 604_800_000
}
def timeframe_to_ms(tf: str) -> int:
    if tf not in _TIMEFRAME_MS:
        raise ValueError(f"Timeframe non supporté: {tf}")
    return _TIMEFRAME_MS[tf]

# =========================
# COLLECTEUR D'ERREURS
# =========================
def log_error(errors: Optional[List[Dict]], where: str, message: str,
              code: Optional[str] = None, details: Optional[Exception] = None, context: Optional[Dict] = None):
    if errors is None:
        return
    # Ajoute un message court selon le code d'erreur
    short_message = message
    if code and "502" in str(code):
        short_message = "Erreur temporaire côté exchange (ex: 502 Bad Gateway). Réessaie plus tard."
    elif code and "429" in str(code):
        short_message = "Limite de requêtes atteinte. Attends avant de réessayer."
    elif code == "SYMBOL_NOT_LISTED":
        short_message = "Paire non disponible sur cet exchange."
    elif code == "NO_PAIR":
        short_message = "Aucune paire trouvée pour cette crypto sur cet exchange."
    elif code == "EMPTY_OHLCV":
        short_message = "Aucune donnée historique disponible pour cette paire."
    elif code == "BASE_NOT_FOUND":
        short_message = "Crypto introuvable. Corrige l’orthographe ou essaie le nom complet."
    errors.append({
        "where": where,
        "code": code,
        "message": message,
        "short_message": short_message,
        "details": (str(details)[:500] if details is not None else None),
        "context": (context or {})
    })
# =========================
# Fetch CoinGecko Top N (groupes dynamiques) + expansion
# =========================
def fetch_top_markets(vs_currency: str = "usd", per_page: int = 200, errors: Optional[List[Dict]] = None) -> pd.DataFrame:
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": vs_currency,
        "order": "market_cap_desc",
        "per_page": per_page,
        "page": 1,
        "price_change_percentage": "24h"
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        df = pd.DataFrame(r.json())
        if df.empty:
            log_error(errors, "fetch_top_markets", "Réponse vide (/coins/markets).",
                      code="EMPTY_RESPONSE", context={"vs_currency": vs_currency, "per_page": per_page})
            return pd.DataFrame(columns=["id","symbol","name","market_cap_rank","current_price","market_cap","total_volume","symbol_up"])
        df["symbol_up"] = df["symbol"].str.upper()
        df["name"] = df["name"].astype(str)
        return df
    except requests.exceptions.HTTPError as e:
        code = f"HTTP_{getattr(e.response,'status_code',None)}"
        msg = "Erreur HTTP CoinGecko."
        if getattr(e.response, "status_code", None) == 429:
            msg = "Limite de taux CoinGecko atteinte (HTTP 429). Réessaie plus tard."
        log_error(errors, "fetch_top_markets", msg, code=code, details=e)
    except requests.exceptions.Timeout as e:
        log_error(errors, "fetch_top_markets", "Timeout CoinGecko.", code="TIMEOUT", details=e)
    except Exception as e:
        log_error(errors, "fetch_top_markets", "Erreur inconnue CoinGecko.", code="UNKNOWN", details=e)
    return pd.DataFrame(columns=["id","symbol","name","market_cap_rank","current_price","market_cap","total_volume","symbol_up"])

def expand_coin_inputs(coin_inputs: List[str], errors: Optional[List[Dict]] = None) -> List[str]:
    """
    Remplace 'Large Cap' / 'Stable coins' / 'Meme coins' / 'Alt coins' par des listes de tickers (top 200).
    """
    df = fetch_top_markets(errors=errors)
    if df.empty:
        log_error(errors, "expand_coin_inputs", "Impossible d'étendre les groupes: top market vide.", code="NO_MARKET_DATA")
        return coin_inputs

    expanded = []
    for c in coin_inputs:
        c_strip = str(c).strip().lower()
        try:
            if c_strip == "large cap":
                expanded += df[df["market_cap_rank"] <= LARGE_CAP_RANK_MAX]["symbol_up"].tolist()
            elif c_strip == "stable coins":
                stable_syms = {"USDT","USDC","BUSD","DAI","TUSD","FDUSD","FRAX","LUSD","USDP","GUSD","EURS","EURT","USDD","PYUSD","XUSD","USDE","USDX","USDK","USDJ","UXD","CUSD","SUSD","VAI","RSV","MIM"}
                expanded += [sym for sym in df["symbol_up"] if sym in stable_syms]
            elif c_strip == "meme coins":
                meme_syms = {"DOGE","SHIB","PEPE","FLOKI","BONK","WIF","BABYDOGE","ELON","BOME","SHIBAINU","PORK","KITTY","POPCAT"}
                expanded += [sym for sym in df["symbol_up"] if sym in meme_syms]
            elif c_strip == "alt coins":
                stable_syms = {"USDT","USDC","BUSD","DAI","TUSD","FDUSD","FRAX","LUSD","USDP","GUSD","EURS","EURT","USDD","PYUSD","XUSD","USDE","USDX","USDK","USDJ","UXD","CUSD","SUSD","VAI","RSV","MIM"}
                meme_syms = {"DOGE","SHIB","PEPE","FLOKI","BONK","WIF","BABYDOGE","ELON","BOME","SHIBAINU","PORK","KITTY","POPCAT"}
                large_syms = set(df[df["market_cap_rank"] <= LARGE_CAP_RANK_MAX]["symbol_up"])
                expanded += [sym for sym in df["symbol_up"] if sym not in stable_syms and sym not in meme_syms and sym not in large_syms]
            else:
                expanded.append(c)
        except Exception as e:
            log_error(errors, "expand_coin_inputs", "Échec d'expansion pour un élément de groupe.",
                      code="EXPAND_ITEM_FAIL", details=e, context={"input": c})
            expanded.append(c)

    seen, result = set(), []
    for x in expanded:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result

# =========================
# RÉSOLVEUR COINGECKO + PAIRE CCXT (avec erreurs)
# =========================
_COINGECKO_CACHE = None

def load_coingecko_coins(force: bool = False, errors: Optional[List[Dict]] = None) -> pd.DataFrame:
    global _COINGECKO_CACHE
    if _COINGECKO_CACHE is not None and not force:
        return _COINGECKO_CACHE
    url = "https://api.coingecko.com/api/v3/coins/list"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            log_error(errors, "load_coingecko_coins", "Réponse vide (/coins/list).", code="EMPTY_RESPONSE")
            _COINGECKO_CACHE = pd.DataFrame(columns=["id","symbol","name"])
            return _COINGECKO_CACHE
        df = pd.DataFrame(data)
        df["symbol"] = df["symbol"].str.upper()
        _COINGECKO_CACHE = df
        return df
    except Exception as e:
        log_error(errors, "load_coingecko_coins", "Impossible de charger la liste CoinGecko.",
                  code="LOAD_FAIL", details=e)
        return pd.DataFrame(columns=["id","symbol","name"])

def resolve_symbol_via_coingecko(user_input: str, top_k: int = 5, errors: Optional[List[Dict]] = None):
    df = load_coingecko_coins(errors=errors)
    if df.empty:
        log_error(errors, "resolve_symbol_via_coingecko",
                  "Dictionnaire CoinGecko vide: impossible de résoudre le symbole.",
                  code="DICT_EMPTY", context={"input": user_input})
        return {"resolved_symbol": None, "resolved_id": None,
                "matches": pd.DataFrame(columns=["symbol","id","name","score"])}

    s = str(user_input).strip().upper()
    try:
        exact = df[df["symbol"] == s]
        if not exact.empty:
            exact = exact.copy()
            exact["score"] = 1.0
            row = exact.iloc[0]
            return {"resolved_symbol": s, "resolved_id": row["id"],
                    "matches": exact[["symbol","id","name","score"]].head(top_k)}

        names = df["name"].tolist()
        ids = df["id"].tolist()
        close_names = difflib.get_close_matches(user_input, names, n=top_k, cutoff=0.6)
        close_ids = difflib.get_close_matches(user_input.lower(), ids, n=top_k, cutoff=0.6)

        rows = []
        name_map = df.drop_duplicates(subset=["name"]).set_index("name").to_dict("index")
        for nm in close_names:
            rows.append({"symbol": name_map[nm]["symbol"], "id": name_map[nm]["id"], "name": nm,
                         "score": difflib.SequenceMatcher(None, user_input.lower(), nm.lower()).ratio()})
        id_map = df.drop_duplicates(subset=["id"]).set_index("id").to_dict("index")
        for cid in close_ids:
            rows.append({"symbol": id_map[cid]["symbol"], "id": cid, "name": id_map[cid]["name"],
                         "score": difflib.SequenceMatcher(None, user_input.lower(), cid.lower()).ratio()})
        if not rows:
            log_error(errors, "resolve_symbol_via_coingecko",
                      "Aucun symbole proche trouvé. Corrige l’orthographe ou essaie le nom complet.",
                      code="NO_MATCH", context={"input": user_input})
            return {"resolved_symbol": None, "resolved_id": None,
                    "matches": pd.DataFrame(columns=["symbol","id","name","score"])}

        cand = (pd.DataFrame(rows)
                .drop_duplicates(subset=["symbol","id"])
                .sort_values("score", ascending=False)
                .head(top_k).reset_index(drop=True))
        return {"resolved_symbol": cand.iloc[0]["symbol"], "resolved_id": cand.iloc[0]["id"], "matches": cand}
    except Exception as e:
        log_error(errors, "resolve_symbol_via_coingecko",
                  "Erreur lors de la résolution du symbole.", code="RESOLVE_FAIL",
                  details=e, context={"input": user_input})
        return {"resolved_symbol": None, "resolved_id": None,
                "matches": pd.DataFrame(columns=["symbol","id","name","score"])}

def pick_tradable_pair_on_exchange(exchange_id: str,
                                   base_symbol: str,
                                   preferred_quotes=PREFERRED_QUOTES,
                                   include_derivatives: bool = False,
                                   errors: Optional[List[Dict]] = None):
    try:
        ex_cls = getattr(ccxt, exchange_id)
        ex = ex_cls({"enableRateLimit": True})
        markets = ex.load_markets()
    except Exception as e:
        log_error(errors, "pick_tradable_pair_on_exchange",
                  "Impossible de charger les marchés de l'exchange.",
                  code="LOAD_MARKETS_FAIL", details=e, context={"exchange": exchange_id})
        return {"pair": None, "alternatives": []}

    try:
        candidates = []
        for m, info in markets.items():
            if not include_derivatives and (info.get("spot") is False and info.get("type") != "spot"):
                continue
            if info.get("base") == base_symbol:
                candidates.append(m)
        if not candidates:
            log_error(errors, "pick_tradable_pair_on_exchange",
                      "Aucune paire trouvée pour la base sur cet exchange.",
                      code="NO_PAIR", context={"exchange": exchange_id, "base": base_symbol})
            return {"pair": None, "alternatives": []}

        def quote_of(pair: str) -> str:
            try:
                return pair.split("/")[1]
            except Exception:
                return ""
        
        # BITSTAMP: Forcer USDT au lieu de USD pour correspondre aux autres exchanges
        quotes_to_use = preferred_quotes
        if exchange_id.lower() == "bitstamp":
            quotes_to_use = ("USDT", "USDC", "USD", "EUR", "BTC")
        
        sorted_cands = sorted(candidates, key=lambda p: (quotes_to_use.index(quote_of(p))
                                                         if quote_of(p) in quotes_to_use else len(quotes_to_use)))
        return {"pair": sorted_cands[0], "alternatives": sorted_cands[1:]}
    except Exception as e:
        log_error(errors, "pick_tradable_pair_on_exchange",
                  "Erreur lors de la sélection de la paire.", code="PICK_FAIL",
                  details=e, context={"exchange": exchange_id, "base": base_symbol})
        return {"pair": None, "alternatives": []}

# =========================
# FETCH OHLCV CCXT (paginé, avec erreurs)
# =========================
def fetch_ohlcv_ccxt(exchange_id: str, symbol: str, timeframe: str,
                     since_ms: int, until_ms: int, limit: int = 1000,
                     errors: Optional[List[Dict]] = None) -> pd.DataFrame:
    global _api_call_counter
    try:
        cls = getattr(ccxt, exchange_id)
        ex = cls({"enableRateLimit": True})
        markets = ex.load_markets()
        if symbol not in markets:
            alt = None
            if symbol.endswith("/USDT") and (symbol[:-4] + "USD") in markets:
                alt = symbol[:-4] + "USD"
            elif symbol.endswith("/USD") and (symbol[:-3] + "USDT") in markets:
                alt = symbol[:-3] + "USDT"
            if alt is None:
                log_error(errors, "fetch_ohlcv_ccxt", "Symbole non listé sur cet exchange.",
                          code="SYMBOL_NOT_LISTED", context={"exchange": exchange_id, "symbol": symbol})
                return pd.DataFrame(columns=["timestamp","date","open","high","low","close","volume","exchange","pair"])
            symbol = alt

        tf_ms = timeframe_to_ms(timeframe)
        data = []
        cursor = since_ms
        while cursor < until_ms:
            with _api_call_lock:
                _api_call_counter += 1
                print(f'      🌐 API Call #{_api_call_counter}: {exchange_id} - {symbol}', flush=True)
            batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit)
            if not batch:
                break
            data.extend(batch)
            last_ts = batch[-1][0]
            next_ts = last_ts + tf_ms
            if next_ts <= cursor:
                break
            cursor = next_ts
            time.sleep(max(RATE_LIMIT_SLEEP, ex.rateLimit / 1000.0))
            if last_ts >= until_ms:
                break

        if not data:
            log_error(errors, "fetch_ohlcv_ccxt", "Aucune donnée OHLCV retournée.",
                      code="EMPTY_OHLCV", context={"exchange": exchange_id, "pair": symbol, "timeframe": timeframe})
            return pd.DataFrame(columns=["timestamp","date","open","high","low","close","volume","exchange","pair"])

        df = pd.DataFrame(data, columns=["timestamp","open","high","low","close","volume"])
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["exchange"] = exchange_id
        df["pair"] = symbol
        df = df[(df["timestamp"] >= since_ms) & (df["timestamp"] <= until_ms)]
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df[["timestamp","date","open","high","low","close","volume","exchange","pair"]]
    except Exception as e:
        log_error(errors, "fetch_ohlcv_ccxt", "Erreur pendant le téléchargement OHLCV.",
                  code="FETCH_FAIL", details=e, context={"exchange": exchange_id, "pair": symbol, "timeframe": timeframe})
        return pd.DataFrame(columns=["timestamp","date","open","high","low","close","volume","exchange","pair"])

# =========================
# OUTILS NUMÉRIQUES
# =========================
def zscore_series(x: np.ndarray) -> np.ndarray:
    mu = np.nanmean(x)
    sigma = np.nanstd(x)
    if sigma == 0 or np.isnan(sigma):
        return np.zeros_like(x)
    return (x - mu) / sigma

def robust_zscores_mad(x: np.ndarray) -> np.ndarray:
    x = x.astype(float)
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    if mad == 0 or np.isnan(mad):
        return np.zeros_like(x)
    return 0.6745 * (x - med) / mad

# =========================
# COMPOSITE (médiane multi-sources)
# =========================
def fuse_ohlcv(dfs: List[pd.DataFrame]) -> pd.DataFrame:
    if not dfs:
        return pd.DataFrame(columns=["timestamp","date","open","high","low","close","volume"])
    work = []
    for i, d in enumerate(dfs):
        di = d[["timestamp","open","high","low","close","volume"]].copy()
        di = di.add_suffix(f"__e{i}")
        di = di.rename(columns={f"timestamp__e{i}": "timestamp"})
        work.append(di)

    merged = work[0]
    for w in work[1:]:
        merged = pd.merge(merged, w, on="timestamp", how="outer")
    merged = merged.sort_values("timestamp").reset_index(drop=True)

    def med(cols_like):
        return np.nanmedian(merged[cols_like].to_numpy(), axis=1)

    opens  = [c for c in merged.columns if c.startswith("open__e")]
    highs  = [c for c in merged.columns if c.startswith("high__e")]
    lows   = [c for c in merged.columns if c.startswith("low__e")]
    closes = [c for c in merged.columns if c.startswith("close__e")]
    vols   = [c for c in merged.columns if c.startswith("volume__e")]

    out = pd.DataFrame({
        "timestamp": merged["timestamp"],
        "open":  med(opens)  if opens  else np.nan,
        "high":  med(highs)  if highs  else np.nan,
        "low":   med(lows)   if lows   else np.nan,
        "close": med(closes) if closes else np.nan,
        "volume": med(vols)  if vols   else np.nan,
    })
    out["date"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True)
    out = out[["timestamp","date","open","high","low","close","volume"]]
    out = out.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return out

# =========================
# MÉTRIQUES AVANCÉES + SCORE
# =========================
def expected_count(since_ms: int, until_ms: int, tf_ms: int) -> int:
    if until_ms < since_ms:
        return 0
    # Aligne le début sur la grille d'epoch pour éviter un biais
    start = (since_ms // tf_ms) * tf_ms
    end = (until_ms // tf_ms) * tf_ms
    return (end - start) // tf_ms + 1

def longest_contiguous_ratio(ts: np.ndarray, tf_ms: int, exp_cnt: int) -> float:
    if ts.size == 0 or exp_cnt <= 0:
        return 0.0
    ts = np.sort(np.unique(ts))
    longest = 1
    cur = 1
    diffs = np.diff(ts)
    for d in diffs:
        if d == tf_ms:
            cur += 1
            if cur > longest:
                longest = cur
        else:
            cur = 1
    return min(1.0, longest / exp_cnt)

def timestamp_drift_score(ts: np.ndarray, tf_ms: int) -> Tuple[float, float]:
    """
    Retourne (score, drift_median_frac) ; drift en fraction de tf (0..0.5)
    """
    if ts.size == 0:
        return 0.0, np.nan
    nearest = np.rint(ts / tf_ms) * tf_ms
    drift_abs = np.abs(ts - nearest)  # en ms
    drift_frac = drift_abs / tf_ms
    med = float(np.nanmedian(drift_frac))
    score = 1.0 - min(1.0, med / DRIFT_TOL_FRAC)
    return max(0.0, score), med

def volume_quality_score(vol: np.ndarray) -> Tuple[float, float]:
    """
    Score = 1 - fraction de volumes outliers (z-MAD > VOL_OUTLIER_Z) sur log(volume)
    Retourne (score, outlier_frac)
    """
    v = vol.astype(float)
    v = v[v > 0]
    if v.size == 0:
        return 1.0, 0.0
    lv = np.log(v)
    z = np.abs(robust_zscores_mad(lv))
    outlier_frac = float(np.mean(z > VOL_OUTLIER_Z))
    return max(0.0, 1.0 - outlier_frac), outlier_frac

def price_dev_score(df: pd.DataFrame, composite: pd.DataFrame) -> Tuple[float, float]:
    """
    Calcule la déviation médiane relative |close - close_comp| / close_comp sur l'intersection des timestamps.
    Score = 1 - min(1, median_dev / PRICE_DEV_TOL).
    Retourne (score, median_dev).
    """
    if df.empty or composite.empty:
        return 0.0, np.nan
    a = df[["timestamp","close"]].copy()
    b = composite[["timestamp","close"]].copy()
    merged = pd.merge(a, b, on="timestamp", how="inner", suffixes=("", "_comp"))
    merged = merged.replace([np.inf, -np.inf], np.nan).dropna(subset=["close","close_comp"])
    merged = merged[merged["close_comp"] != 0]
    if merged.empty:
        return 0.0, np.nan
    rel = np.abs(merged["close"] - merged["close_comp"]) / merged["close_comp"]
    med = float(np.nanmedian(rel))
    score = 1.0 - min(1.0, med / PRICE_DEV_TOL)
    return max(0.0, score), med

def completeness_ratio(ts: np.ndarray, since_ms: int, until_ms: int, tf_ms: int) -> float:
    exp_cnt = expected_count(since_ms, until_ms, tf_ms)
    if exp_cnt <= 0:
        return 0.0
    got = len(np.unique(ts))
    return min(1.0, got / exp_cnt)

def compute_advanced_metrics(df: pd.DataFrame,
                             timeframe: str,
                             since_ms: int,
                             until_ms: int,
                             composite: Optional[pd.DataFrame]) -> Dict[str, float]:
    """
    Calcule toutes les métriques + sous-scores [0..1] pour agrégation pondérée.
    """
    tf_ms = timeframe_to_ms(timeframe)
    out = {
        "rows": len(df),
        "completeness": np.nan,         # ratio
        "continuity": np.nan,           # ratio
        "price_dev_median": np.nan,     # valeur
        "price_dev_score": np.nan,      # [0..1]
        "timestamp_drift_median": np.nan,  # fraction de tf
        "timestamp_drift_score": np.nan,   # [0..1]
        "volume_outlier_frac": np.nan,
        "volume_quality": np.nan,       # [0..1] = 1 - outlier_frac
    }
    if df.empty:
        return out

    ts = df["timestamp"].to_numpy(dtype=np.int64)
    out["completeness"] = completeness_ratio(ts, since_ms, until_ms, tf_ms)
    exp_cnt = expected_count(since_ms, until_ms, tf_ms)
    out["continuity"] = longest_contiguous_ratio(ts, tf_ms, exp_cnt)

    pscore, pmed = price_dev_score(df, composite if composite is not None else pd.DataFrame())
    out["price_dev_score"] = pscore
    out["price_dev_median"] = pmed

    tscore, tmed = timestamp_drift_score(ts, tf_ms)
    out["timestamp_drift_score"] = tscore
    out["timestamp_drift_median"] = tmed

    vscore, vfrac = volume_quality_score(df["volume"].to_numpy(dtype=float))
    out["volume_quality"] = vscore
    out["volume_outlier_frac"] = vfrac

    return out

def overall_quality_score(m: Dict[str, float]) -> float:
    """
    Agrège les sous-scores avec pondérations WEIGHTS.
    Les keys attendues: completeness, continuity, price_dev_score, timestamp_drift_score, volume_quality
    """
    parts = {
        "completeness": m.get("completeness", 0.0),
        "continuity": m.get("continuity", 0.0),
        "price_dev": m.get("price_dev_score", 0.0),
        "timestamp_drift": m.get("timestamp_drift_score", 0.0),
        "volume_quality": m.get("volume_quality", 0.0),
    }
    score = 0.0
    for k, w in WEIGHTS.items():
        score += w * max(0.0, min(1.0, parts.get(k, 0.0)))
    return float(score)

# =========================
# ORCHESTRATION (sélection des sources, scoring, provenance)
# =========================
def compare_exchanges_on_bases(exchanges: List[str],
                               bases: List[str],
                               timeframe: str,
                               lookback_days: int,
                               preferred_quotes=PREFERRED_QUOTES,
                               allowed_exchanges: Optional[List[str]] = None,
                               selection: str = "best",                # "best" ou "fixed"
                               fixed_exchange: Optional[str] = None,   # si selection="fixed"
                               include_derivatives: bool = False,
                               since_ms: Optional[int] = None,
                               until_ms: Optional[int] = None):
    """
    - allowed_exchanges: filtre (ex: ["kraken","coinbase"])
    - selection:
        - "best": score toutes les sources autorisées, tente early-stop si score=1, sinon fusion.
        - "fixed": n’utilise que 'fixed_exchange' (pas de fusion/scoring multi-sources).
    - fixed_exchange: id ccxt (ex: "kraken") si selection="fixed".
    - Retourne (agg, detail, data); provenance lisible dans data["__FINAL_META__"][base]["provenance"].
    """
    global _api_call_counter
    with _api_call_lock:
        _api_call_counter = 0  # Reset du compteur
    
    print(f'   🌐 FETCHER CALLED: {len(bases)} bases x {len(exchanges)} exchanges = {len(bases) * len(exchanges)} potential API calls')
    errors: List[Dict] = []

    # 0) Fenêtre: allow caller to pass explicit since_ms/until_ms (ms). Otherwise fall back to now - lookback_days
    if since_ms is not None and until_ms is not None:
        # use provided ms values
        since_dt = datetime.fromtimestamp(since_ms / 1000.0, tz=timezone.utc)
        until_dt = datetime.fromtimestamp(until_ms / 1000.0, tz=timezone.utc)
        since = since_dt
        until = until_dt
    else:
        until = datetime.now(timezone.utc)
        since = until - timedelta(days=lookback_days)
        since_ms = int(since.timestamp() * 1000)
        until_ms = int(until.timestamp() * 1000)
    # ensure since_ms/until_ms are available for downstream calls
    if since_ms is None:
        since_ms = int(since.timestamp() * 1000)
    if until_ms is None:
        until_ms = int(until.timestamp() * 1000)
    tf_ms = timeframe_to_ms(timeframe)

    # 1) Résolution des bases
    resolved_rows = []
    for b in bases:
        r = resolve_symbol_via_coingecko(b, errors=errors)
        if r["resolved_symbol"] is None:
            log_error(errors, "compare_exchanges_on_bases",
                      "Crypto introuvable. Corrige l’orthographe ou essaie le nom complet.",
                      code="BASE_NOT_FOUND", context={"input": b})
        else:
            resolved_rows.append({
                "base_input": b,
                "resolved_symbol": r["resolved_symbol"],
                "resolved_id": r["resolved_id"]
            })

    # 2) Prépare containers résultats
    rows = []  # détail score par source
    data: Dict[str, Dict] = {ex: {} for ex in exchanges}
    data["__FINAL__"] = {}
    data["__FINAL_META__"] = {}
    data["__ERRORS__"] = errors

    # 3) Filtre des exchanges autorisés
    if allowed_exchanges:
        ex_list = [e for e in exchanges if e in set(allowed_exchanges)]
        if not ex_list:
            log_error(errors, "compare_exchanges_on_bases", "Aucun exchange autorisé après filtrage.",
                      code="NO_ALLOWED_EXCHANGES", context={"allowed_exchanges": allowed_exchanges})
            ex_list = []
    else:
        ex_list = exchanges

    # 4) Boucle par base
    for row_base in resolved_rows:
        base_input = row_base["base_input"]
        base = row_base["resolved_symbol"]
        print(f"\n=== Base '{base_input}' → '{base}' ===")

        if selection == "fixed":
            # -> mode “le client choisit la source”
            if not fixed_exchange:
                log_error(errors, "compare_exchanges_on_bases",
                          "Mode 'fixed' sans 'fixed_exchange'.", code="FIXED_MISSING")
                continue
            if fixed_exchange not in ex_list:
                log_error(errors, "compare_exchanges_on_bases",
                          "Exchange fixe non autorisé par allowed_exchanges.",
                          code="FIXED_NOT_ALLOWED", context={"fixed_exchange": fixed_exchange})
                continue

            pick = pick_tradable_pair_on_exchange(fixed_exchange, base, preferred_quotes,
                                                  include_derivatives=include_derivatives, errors=errors)
            pair = pick["pair"]
            if pair is None:
                continue
            df = fetch_ohlcv_ccxt(fixed_exchange, pair, timeframe, since_ms, until_ms, errors=errors)
            if df.empty:
                continue

            # Composite = la source elle-même → déviation = 0
            composite = df[["timestamp","close"]].copy()
            m = compute_advanced_metrics(df, timeframe, since_ms, until_ms, composite)
            s = overall_quality_score(m)

            rows.append({
                "exchange": fixed_exchange, "base_input": base_input, "base": base, "pair": df["pair"].iloc[0],
                "score": s, **m
            })
            data[fixed_exchange][base] = df

            data["__FINAL__"][base] = df[["timestamp","date","open","high","low","close","volume"]].copy()
            data["__FINAL_META__"][base] = {
                "mode": "fixed_source",
                "exchange": fixed_exchange,
                "pair": df["pair"].iloc[0],
                "score": s,
                "provenance": f"Données issues de {fixed_exchange} (source imposée par l’utilisateur)."
            }
            print(f"  {base} @ {fixed_exchange} → {df['pair'].iloc[0]} | score={s:.3f} | rows={len(df)}")
            continue  # prochaine base

        # === selection == "best" ===
        # 1) Collecte de toutes les sources autorisées (df non vides)
        source_dfs = []
        source_meta = []  # (exchange, pair)
        for ex_id in ex_list:
            pick = pick_tradable_pair_on_exchange(ex_id, base, preferred_quotes,
                                                  include_derivatives=include_derivatives, errors=errors)
            pair = pick["pair"]
            if pair is None:
                continue
            df = fetch_ohlcv_ccxt(ex_id, pair, timeframe, since_ms, until_ms, errors=errors)
            if df.empty:
                continue
            source_dfs.append(df)
            source_meta.append((ex_id, pair))
            data[ex_id][base] = df

        if not source_dfs:
            log_error(errors, "compare_exchanges_on_bases",
                      "Aucune source de données valide pour cette base (après filtrage).",
                      code="NO_SOURCES", context={"base": base, "input": base_input})
            # on laisse final vide
            continue

        # 2) Composite multi-sources (médiane) pour prix de référence
        composite = fuse_ohlcv(source_dfs)

        # 3) Scoring avancé pour chaque source vs composite
        per_scores = []
        for df, (ex_id, pair) in zip(source_dfs, source_meta):
            m = compute_advanced_metrics(df, timeframe, since_ms, until_ms, composite)
            s = overall_quality_score(m)
            per_scores.append((s, ex_id, pair, m, df))
            rows.append({
                "exchange": ex_id, "base_input": base_input, "base": base, "pair": pair, "score": s, **m
            })
            print(f"  {base} @ {ex_id} → {pair} | score={s:.3f} | rows={len(df)}")

        # 4) Choix final
        per_scores.sort(key=lambda x: x[0], reverse=True)
        best_score, best_ex, best_pair, best_m, best_df = per_scores[0]

        if best_score >= PERFECT_SCORE:
            # early stop: on garde la meilleure source
            final_df = best_df[["timestamp","date","open","high","low","close","volume"]].copy()
            final_meta = {
                "mode": "early_stop",
                "exchange": best_ex,
                "pair": best_pair,
                "score": best_score,
                "provenance": f"Données issues de {best_ex} (score parfait)."
            }
        else:
            # compilation multi-sources (médiane)
            final_df = composite[["timestamp","date","open","high","low","close","volume"]].copy()
            used_names = [ex for ex, _ in [(e, p) for (e, p) in source_meta]]
            final_meta = {
                "mode": "fused_median",
                "sources": [{"exchange": ex, "pair": p} for ex, p in source_meta],
                "metrics_on_fused": compute_advanced_metrics(final_df.assign(exchange="__FUSED__", pair="__FUSED__"),
                                                             timeframe, since_ms, until_ms, final_df),
                "provenance": "Données issues d’une compilation : " + ", ".join(sorted(set(used_names)))
            }

        data["__FINAL__"][base] = final_df
        data["__FINAL_META__"][base] = final_meta

    # 5) Agrégation par exchange (score moyen observé)
    detail = pd.DataFrame(rows)
    if not detail.empty:
        agg = (detail.groupby("exchange", as_index=False)["score"].mean()
               .rename(columns={"score": "mean_score"})
               .sort_values("mean_score", ascending=False)
               .reset_index(drop=True))
    else:
        agg = pd.DataFrame(columns=["exchange","mean_score"])

    print(f'   ✅ FETCHER COMPLETE: Total API calls made = {_api_call_counter}', flush=True)
    
    return agg, detail, data

# =========================
# EXEMPLE D’USAGE
# =========================
if __name__ == "__main__":
    # 1) Exemple avec groupes dynamiques + “best”
    raw_inputs = ["Large Cap", "ETH", "pepe", "etherum"]
    errors_front = []
    bases = expand_coin_inputs(raw_inputs, errors=errors_front)

    agg, detail, data = compare_exchanges_on_bases(
        EXCHANGES,
        bases,
        TIMEFRAME,
        LOOKBACK_DAYS,
        preferred_quotes=PREFERRED_QUOTES,
        allowed_exchanges=None,       # ex: ["kraken","coinbase"] pour filtrer
        selection="best",             # "best" (par défaut)
        fixed_exchange=None,          # ignoré si "best"
        include_derivatives=False
    )
    data["__ERRORS__"].extend(errors_front)

    print("\n=== Classement (score moyen par exchange) ===")
    print(agg[["exchange","mean_score"]] if not agg.empty else "No data")

    print("\n=== FINAL meta / provenance ===")
    for base, meta in data["__FINAL_META__"].items():
        print(base, "->", meta.get("provenance"))

    print("\n=== Erreurs collectées ===")
    for err in data.get("__ERRORS__"):
        print(f"[{err['where']}] {err.get('short_message', err['message'])} (code={err['code']})")

    # 2) Exemple “fixed” (client choisit uniquement Kraken)
    agg2, detail2, data2 = compare_exchanges_on_bases(
        EXCHANGES,
        ["BTC","ETH"],
        TIMEFRAME,
        LOOKBACK_DAYS,
        selection="fixed",
        fixed_exchange="kraken"
    )
    print("\n=== Provenance (fixed) ===")
    for base, meta in data2["__FINAL_META__"].items():
        print(base, "->", meta.get("provenance"))