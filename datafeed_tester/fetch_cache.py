"""Cache disque des bougies OHLCV finales (parquet + méta JSON), par (base, timeframe, période, exchanges).

Évite de retélécharger / re-scorer les mêmes données à chaque backtest ou optimisation.
- Période terminée il y a plus de 2 jours : cache sans expiration.
- Période récente (se termine "maintenant") : expire après ``RECENT_TTL_S`` secondes.
Vider le cache : supprimer le dossier ``datafeed_tester/.cache/ohlcv`` (ou ``clear_cache()``).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "ohlcv")
RECENT_TTL_S = 3600
_RECENT_WINDOW_MS = 2 * 24 * 3600 * 1000


def _key(base: str, timeframe: str, since_ms: int, until_ms: int, exchanges: List[str]) -> str:
    raw = f"{base}|{timeframe}|{since_ms}|{until_ms}|{','.join(exchanges)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _expired(path: str, until_ms: int) -> bool:
    if until_ms < time.time() * 1000 - _RECENT_WINDOW_MS:
        return False
    return time.time() - os.path.getmtime(path) > RECENT_TTL_S


def _json_default(o: Any):
    return o.item() if hasattr(o, "item") else str(o)


def _read(key: str, until_ms: int):
    pq = os.path.join(CACHE_DIR, f"{key}.parquet")
    meta_path = os.path.join(CACHE_DIR, f"{key}.json")
    if not (os.path.exists(pq) and os.path.exists(meta_path)) or _expired(pq, until_ms):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return pd.read_parquet(pq), meta
    except Exception as e:  # cache corrompu -> on ignore et on retélécharge
        print(f"⚠️ Cache illisible ({key}): {e}")
        return None


def _write(key: str, df: pd.DataFrame, meta: Dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    for ext, writer in (("parquet", lambda p: df.to_parquet(p)),
                        ("json", lambda p: open(p, "w", encoding="utf-8").write(
                            json.dumps(meta, default=_json_default)))):
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
        os.close(fd)
        try:
            writer(tmp)
            os.replace(tmp, os.path.join(CACHE_DIR, f"{key}.{ext}"))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def fetch_final_cached(
    fetch_fn: Callable[..., Any],
    exchanges: List[str],
    bases: List[str],
    timeframe: str,
    since_ms: int,
    until_ms: int,
    selection: str = "best",
    use_cache: bool = True,
) -> Dict[str, Dict]:
    """Retourne ``{"__FINAL__": {base: df}, "__FINAL_META__": {base: meta}}`` (même forme que fetch_data).

    Seules les bases absentes du cache sont téléchargées (via ``fetch_fn`` = compare_exchanges_on_bases).
    """
    final: Dict[str, pd.DataFrame] = {}
    metas: Dict[str, Dict] = {}
    missing: List[str] = []

    for base in bases:
        hit = _read(_key(base, timeframe, since_ms, until_ms, exchanges), until_ms) if use_cache else None
        if hit is None:
            missing.append(base)
        else:
            final[base], metas[base] = hit

    if missing:
        _, _, fetch_data = fetch_fn(
            exchanges=exchanges, bases=missing, timeframe=timeframe, lookback_days=365,
            since_ms=since_ms, until_ms=until_ms, selection=selection,
        )
        for base, df in fetch_data.get("__FINAL__", {}).items():
            meta = fetch_data.get("__FINAL_META__", {}).get(base, {})
            final[base], metas[base] = df, meta
            if use_cache and base in missing and not df.empty:
                try:
                    _write(_key(base, timeframe, since_ms, until_ms, exchanges), df, meta)
                except Exception as e:  # le cache ne doit jamais casser un backtest
                    print(f"⚠️ Écriture cache impossible ({base}): {e}")
    else:
        print(f"⚡ Données OHLCV servies depuis le cache ({len(bases)} assets)")

    return {"__FINAL__": final, "__FINAL_META__": metas}


def clear_cache() -> None:
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
