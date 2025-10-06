# core/io.py
from __future__ import annotations
import os
import re
from datetime import datetime
from typing import Iterable, Dict, Any, List, Optional

import pandas as pd

def _slug(s: str) -> str:
    s = str(s)
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "unnamed"

def make_run_id() -> str:
    # exemple: 2025-09-14_12-03-22 (UTC)
    return datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _save_single(df: pd.DataFrame, path_no_ext: str, fmt: str, index: bool = False) -> Optional[str]:
    fmt = fmt.lower()
    if df is None or df.empty:
        return None
    if fmt == "csv":
        path = f"{path_no_ext}.csv"
        df.to_csv(path, index=index)
        return path
    elif fmt in ("parquet", "pq"):
        path = f"{path_no_ext}.parquet"
        try:
            df.to_parquet(path, index=index)
        except Exception:
            # fallback si pyarrow/fastparquet non installés
            path = f"{path_no_ext}.csv"
            df.to_csv(path, index=index)
        return path
    else:
        return None

def save_equity_and_trades(
    base_symbol: str,
    strategy_name: str,
    equity_df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame],
    output_dir: str,
    run_id: Optional[str] = None,
    formats: Iterable[str] = ("csv", "parquet"),
) -> Dict[str, List[str]]:
    """
    Sauvegarde equity & trades dans:
      {output_dir}/{run_id}/{base}/{strategy}/equity.* et trades.*
    Retourne les chemins écrits: {"equity": [...], "trades": [...]}
    """
    run_id = run_id or make_run_id()
    base_slug = _slug(base_symbol)
    strat_slug = _slug(strategy_name)
    root = os.path.join(output_dir, run_id, base_slug, strat_slug)
    ensure_dir(root)

    paths: Dict[str, List[str]] = {"equity": [], "trades": []}

    # equity
    if equity_df is not None and not equity_df.empty:
        path_no_ext = os.path.join(root, "equity")
        for fmt in formats:
            p = _save_single(equity_df, path_no_ext, fmt, index=False)
            if p:
                paths["equity"].append(p)

    # trades
    if trades_df is not None and not trades_df.empty:
        path_no_ext = os.path.join(root, "trades")
        for fmt in formats:
            p = _save_single(trades_df, path_no_ext, fmt, index=False)
            if p:
                paths["trades"].append(p)

    return paths
