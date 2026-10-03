#!/usr/bin/env python3
"""Backtester portefeuille SmartBot V2 - version rapide (numba) + optimiseur de paramètres.

La logique de trading par asset est IDENTIQUE à ``backtester_exact.backtest_smartbot_v2`` (mono-asset,
reproduction du Pine Script) : déclencheurs de Safety Order (ATR / dernier SO / Base Order,
``deviation_scale``, signal requis hors "From Base Order"), TP sur la mèche (High) exécuté au prix du TP,
``tp_type``, Stop Loss (``strategy_mode == "stop_loss"``), sortie par durée max, horaires de marché US,
frais prélevés à la clôture, pas de réentrée sur la barre de clôture, 1re barre ignorée.

Ce qui est propre au portefeuille :
* capital partagé entre tous les assets ;
* ``max_active_trades`` positions simultanées ;
* à chaque barre : 1) TP/SL/durée/SO des positions ouvertes (dans l'ordre d'ouverture), 2) nouvelles
  entrées dans l'ordre des assets tant qu'il reste des slots et du capital.

Architecture : ``PreparedPortfolio`` aligne les assets sur une timeline commune (tableaux numpy 2D) et met
les indicateurs en cache ; ``_portfolio_kernel`` (numba, sans GIL) fait la boucle ; ``optimize_portfolio``
teste des milliers de combinaisons en parallèle.
"""
from __future__ import annotations

import itertools
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import pandas_ta as ta
from numba import njit

from backtester_exact import ParametresDCA_SmartBotV2

# ═══════════════════════════════════════════════════════════════════════════
# Indicateurs (mêmes appels pandas_ta et mêmes valeurs de repli que le backtester mono-asset)
# ═══════════════════════════════════════════════════════════════════════════


def _ind_rsi(df: pd.DataFrame, length: int) -> np.ndarray:
    n = len(df)
    try:
        rsi = ta.rsi(df["Close"], length=length)
        return rsi.fillna(50.0).to_numpy() if rsi is not None else np.full(n, 50.0)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Erreur RSI: {e}")
        return np.full(n, 50.0)


def _ind_bb(df: pd.DataFrame, length: int, mult: float) -> np.ndarray:
    n = len(df)
    close = df["Close"].to_numpy()
    try:
        bb = ta.bbands(df["Close"], length=length, std=mult)
        if bb is not None and not bb.empty:
            lower_col = [c for c in bb.columns if "BBL" in c][0]
            upper_col = [c for c in bb.columns if "BBU" in c][0]
            bb_lower = bb[lower_col].to_numpy()
            bb_upper = bb[upper_col].to_numpy()
            bb_range = bb_upper - bb_lower
            bb_range[bb_range == 0] = 1.0
            return np.nan_to_num((close - bb_lower) / bb_range, nan=0.5)
        return np.full(n, 0.5)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Erreur BB%: {e}")
        return np.full(n, 0.5)


def _ind_mfi(df: pd.DataFrame, length: int) -> np.ndarray:
    n = len(df)
    try:
        mfi = ta.mfi(high=df["High"], low=df["Low"], close=df["Close"], volume=df["Volume"], length=length)
        return mfi.fillna(50.0).to_numpy() if mfi is not None else np.full(n, 50.0)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Erreur MFI: {e}")
        return np.full(n, 50.0)


def _ind_atr(df: pd.DataFrame, length: int) -> np.ndarray:
    n = len(df)
    try:
        atr = ta.atr(high=df["High"], low=df["Low"], close=df["Close"], length=length)
        return atr.fillna(0.0).to_numpy() if atr is not None else np.zeros(n)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Erreur ATR: {e}")
        return np.zeros(n)


_INDICATORS: Dict[str, Tuple[Callable[..., np.ndarray], float]] = {
    "rsi": (_ind_rsi, 50.0),
    "bb": (_ind_bb, 0.5),
    "mfi": (_ind_mfi, 50.0),
    "atr": (_ind_atr, 0.0),
}

# Composantes de chaque Deal Start Condition (dsc inconnue -> jamais de signal, comme le mono-asset)
_DSC_PARTS: Dict[str, Tuple[str, ...]] = {
    "RSI": ("rsi",),
    "MFI": ("mfi",),
    "Bollinger Band %": ("bb",),
    "RSI + MFI": ("rsi", "mfi"),
    "RSI + BB": ("rsi", "bb"),
    "BB + MFI": ("bb", "mfi"),
    "All Three": ("rsi", "bb", "mfi"),
}
_DSC2_PART = {"RSI": "rsi", "Bollinger Band %": "bb", "MFI": "mfi"}  # autre valeur -> condition toujours vraie

_MODE_ATR, _MODE_LAST_SO, _MODE_BASE, _MODE_NONE = 0, 1, 2, 3
_MODES = {"ATR": _MODE_ATR, "From Last Safety Order": _MODE_LAST_SO, "From Base Order": _MODE_BASE}

# Codes de sortie
_R_TP, _R_END, _R_SL, _R_TIME, _R_OPEN = 0, 1, 2, 3, 4
_REASON_LABELS = np.array(["TP", "END", "SL", "TIME", "OPEN"], dtype=object)


def _market_mask(timeline: pd.Index, timeframe: str) -> np.ndarray:
    """Version vectorisée de ``backtester_exact.est_dans_session_marche_us`` sur toute la timeline."""
    ts = timeline
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    ny = ts.tz_convert("America/New_York")
    ok = np.asarray(ny.weekday) < 5
    if timeframe != "1d":
        sod = ((np.asarray(ny.hour, dtype=np.int64) * 3600 + np.asarray(ny.minute, dtype=np.int64) * 60
                + np.asarray(ny.second, dtype=np.int64)) * 1_000_000 + np.asarray(ny.microsecond, dtype=np.int64))
        ok = ok & (sod >= 34_200_000_000) & (sod <= 57_600_000_000)  # 09:30:00 <= t <= 16:00:00
    return np.ascontiguousarray(ok)


# ═══════════════════════════════════════════════════════════════════════════
# Données préparées (alignement + cache d'indicateurs)
# ═══════════════════════════════════════════════════════════════════════════


class PreparedPortfolio:
    """Assets alignés sur une timeline unique + cache d'indicateurs.

    À construire UNE fois puis à réutiliser pour tous les backtests / essais d'optimisation.
    Les indicateurs sont calculés sur la série PROPRE de chaque asset (comme le mono-asset), puis alignés.
    """

    def __init__(self, assets_data: Dict[str, pd.DataFrame]):
        if not assets_data:
            raise ValueError("assets_data est vide")

        self.assets: List[str] = list(assets_data.keys())
        self._dfs: Dict[str, pd.DataFrame] = {}
        for a, df in assets_data.items():
            df = df[~df.index.duplicated(keep="first")]
            if not df.index.is_monotonic_increasing:
                df = df.sort_index()
            self._dfs[a] = df

        timeline: Optional[pd.Index] = None
        for df in self._dfs.values():
            timeline = df.index if timeline is None else timeline.union(df.index)
        self.timeline: pd.Index = timeline.sort_values()

        shape = (len(self.timeline), len(self.assets))
        self.close = np.full(shape, np.nan)
        self.high = np.full(shape, np.nan)
        self.low = np.full(shape, np.nan)
        self.prev_close = np.full(shape, np.nan)  # close de la barre précédente DE L'ASSET
        self.present = np.zeros(shape, dtype=np.bool_)
        self.valid = np.zeros(shape, dtype=np.bool_)  # présent ET pas la 1re barre de l'asset
        self.own_idx = np.full(shape, -1, dtype=np.int64)  # numéro de barre dans la série propre de l'asset
        self.last_close = np.zeros(len(self.assets))
        self.last_bar = np.zeros(len(self.assets), dtype=np.int64)
        self._pos: Dict[str, np.ndarray] = {}

        for j, asset in enumerate(self.assets):
            df = self._dfs[asset]
            pos = self.timeline.get_indexer(df.index)
            self._pos[asset] = pos
            closes = df["Close"].to_numpy(dtype=float)
            self.close[pos, j] = closes
            self.high[pos, j] = df["High"].to_numpy(dtype=float)
            self.low[pos, j] = df["Low"].to_numpy(dtype=float)
            self.present[pos, j] = True
            self.own_idx[pos, j] = np.arange(len(pos))
            if len(pos) > 1:
                self.prev_close[pos[1:], j] = closes[:-1]
                self.valid[pos[1:], j] = True
            self.last_close[j] = closes[-1] if len(closes) else np.nan
            self.last_bar[j] = pos[-1] if len(pos) else 0

        self._cache: Dict[Tuple, np.ndarray] = {}
        self._lock = threading.Lock()

    # -- indicateurs -------------------------------------------------------
    def indicator(self, name: str, *key: Any) -> np.ndarray:
        """Indicateur aligné [barres x assets], mis en cache par (nom, paramètres)."""
        cache_key = (name, *key)
        arr = self._cache.get(cache_key)
        if arr is not None:
            return arr
        with self._lock:
            arr = self._cache.get(cache_key)
            if arr is None:
                func, fill = _INDICATORS[name]
                arr = np.full(self.close.shape, fill)
                for j, asset in enumerate(self.assets):
                    arr[self._pos[asset], j] = func(self._dfs[asset], *key)
                self._cache[cache_key] = arr
        return arr

    def warm(self, p: ParametresDCA_SmartBotV2) -> None:
        """Pré-calcule les indicateurs utiles à ``p`` (à appeler avant le multi-threading)."""
        self.atr_for(p)
        self.entry_signals(p)
        self.allowed(p)

    def atr_for(self, p: ParametresDCA_SmartBotV2) -> np.ndarray:
        if _MODES.get(p.pricedevbase, _MODE_NONE) == _MODE_ATR:
            return self.indicator("atr", p.atr_length)
        return _EMPTY_2D

    def allowed(self, p: ParametresDCA_SmartBotV2) -> np.ndarray:
        """Masque [barres] des barres où le trading est autorisé (horaires de marché US si activé)."""
        if not p.restrict_trading_to_us_market_hours:
            key: Tuple = ("allowed", None)
        else:
            key = ("allowed", p.trading_timeframe)
        arr = self._cache.get(key)
        if arr is None:
            with self._lock:
                arr = self._cache.get(key)
                if arr is None:
                    if key[1] is None:
                        arr = np.ones(len(self.timeline), dtype=np.bool_)
                    else:
                        arr = _market_mask(self.timeline, p.trading_timeframe)
                    self._cache[key] = arr
        return arr

    def _part(self, name: str, p: ParametresDCA_SmartBotV2) -> np.ndarray:
        if name == "rsi":
            return self.indicator("rsi", p.rsi_length) < p.dsc_rsi_threshold_low
        if name == "mfi":
            return self.indicator("mfi", p.mfi_length) < p.mfi_threshold_low
        return self.indicator("bb", p.bb_length, p.bb_mult) < p.bb_threshold_low

    def entry_signals(self, p: ParametresDCA_SmartBotV2) -> np.ndarray:
        """Signal d'entrée [barres x assets] - équivalent de ``evaluer_entry_signal`` (DSC + DSC2)."""
        parts = _DSC_PARTS.get(p.dsc)
        if parts is None:
            return np.zeros(self.close.shape, dtype=np.bool_)
        sig = self._part(parts[0], p)
        for name in parts[1:]:
            sig = sig & self._part(name, p)
        if p.dsc2_enabled:
            sec = _DSC2_PART.get(p.dsc2)
            if sec is not None:
                sig = sig & self._part(sec, p)
        return np.ascontiguousarray(sig & self.valid)


_EMPTY_2D = np.zeros((1, 1))


# ═══════════════════════════════════════════════════════════════════════════
# Noyau numba
# ═══════════════════════════════════════════════════════════════════════════


@njit(cache=True, nogil=True)
def _grow2(a):
    b = np.empty((a.shape[0] * 2, a.shape[1]), a.dtype)
    b[: a.shape[0], :] = a
    return b


@njit(cache=True, nogil=True)
def _write_trade(tr_i, tr_f, tr_sb, tr_sp, k, a, entry_bar, exit_bar, reason, exit_price, pnl, pnl_pct,
                 so_cnt, base_price, avg, invested, qty, so_bar_buf, so_px_buf):
    tr_i[k, 0] = a
    tr_i[k, 1] = entry_bar
    tr_i[k, 2] = exit_bar
    tr_i[k, 3] = so_cnt[a]
    tr_i[k, 4] = reason
    tr_f[k, 0] = base_price[a]
    tr_f[k, 1] = avg[a]
    tr_f[k, 2] = exit_price
    tr_f[k, 3] = invested[a]
    tr_f[k, 4] = qty[a]
    tr_f[k, 5] = pnl
    tr_f[k, 6] = pnl_pct
    for s in range(so_cnt[a]):
        tr_sb[k, s] = so_bar_buf[a, s]
        tr_sp[k, s] = so_px_buf[a, s]


@njit(cache=True, nogil=True)
def _so_step(a, t, price, prev, atrv, sig, mode, max_so,
             so_size_tbl, atr_mult_tbl, dev_tbl, cum_tbl,
             qty, invested, avg, base_price, last_so, so_cnt, so_bar_buf, so_px_buf, capital):
    """Logique Safety Order du mono-asset pour l'asset ``a`` à la barre ``t``. Retourne le capital."""
    k = so_cnt[a]
    if k >= max_so:
        return capital

    # calcular_so_trigger_price
    if mode == 2:  # From Base Order
        trig = base_price[a] * (1 - cum_tbl[k] / 100.0)
    elif mode == 1:  # From Last Safety Order
        trig = last_so[a] * (1 - dev_tbl[k] / 100.0)
    elif mode == 0:  # ATR
        if prev > 0:
            atr_pct = (atrv / prev) * 100.0
        else:
            atr_pct = 0.0
        trig = last_so[a] * (1 - (atr_pct * atr_mult_tbl[k]) / 100.0)
    else:
        trig = 0.0

    below = price <= trig
    if mode == 2:
        fire = below
    else:
        fire = below and sig
    if not fire:
        return capital

    so_size = so_size_tbl[k]
    if capital < so_size:  # SO ignoré, le trade continue
        return capital

    invested[a] += so_size
    qty[a] += so_size / price
    avg[a] = invested[a] / qty[a]
    last_so[a] = price
    so_bar_buf[a, k] = t
    so_px_buf[a, k] = price
    so_cnt[a] = k + 1
    return capital - so_size


@njit(cache=True, nogil=True)
def _portfolio_kernel(
    close, high, low, prev_close, present, signal, atr, allowed, own_idx, last_close, last_bar, close_ok,
    mode, tp_mult, tp_from_avg, sl_pct, max_dur, so_enabled, commission, max_so, base_order,
    initial_capital, max_active, so_size_tbl, atr_mult_tbl, dev_tbl, cum_tbl, close_last,
):
    """Boucle portefeuille.

    tr_i = [asset, entry_bar, exit_bar, so_count, reason(0 TP,1 END,2 SL,3 TIME,4 OPEN)]
    tr_f = [base_price, avg_entry, exit_price, invested, qty, pnl, pnl_pct]
    tr_sb / tr_sp : barre et prix de chaque SO du trade (colonnes 0..so_count-1)
    Les trades clôturés viennent en premier (n_closed), puis les positions encore ouvertes (reason 4,
    exit_price = dernier close, pnl = latent après frais de sortie hypothétiques, comme le mono-asset).
    """
    n_bars, n_assets = close.shape
    capital = initial_capital
    width = max_so + 1

    in_pos = np.zeros(n_assets, np.bool_)
    base_price = np.zeros(n_assets)
    avg = np.zeros(n_assets)
    qty = np.zeros(n_assets)
    invested = np.zeros(n_assets)
    last_so = np.zeros(n_assets)
    lastpx = np.zeros(n_assets)
    so_cnt = np.zeros(n_assets, np.int64)
    entry_bar = np.zeros(n_assets, np.int64)
    entry_own = np.zeros(n_assets, np.int64)
    last_close_bar = np.full(n_assets, -1, np.int64)
    skipped = np.zeros(n_assets, np.int64)
    so_bar_buf = np.zeros((n_assets, width), np.int64)
    so_px_buf = np.zeros((n_assets, width))

    order = np.empty(n_assets, np.int64)  # ordre d'ouverture des positions
    n_open = 0
    equity = np.empty(n_bars)
    open_pos_sum = 0  # somme sur les barres de (BO + SO) ouverts -> moyenne de positions ouvertes
    max_used = 0.0  # capital maximum engagé (fin de barre)

    tr_i = np.empty((1024, 5), np.int64)
    tr_f = np.empty((1024, 7), np.float64)
    tr_sb = np.empty((1024, width), np.int64)
    tr_sp = np.empty((1024, width), np.float64)
    n_tr = 0

    for t in range(n_bars):
        ok_bar = allowed[t]

        # ── Phase 1 : TP / SL / durée puis Safety Orders des positions déjà ouvertes ──
        n0 = n_open
        w = 0
        for r in range(n0):
            a = order[r]
            if not present[t, a]:
                order[w] = a
                w += 1
                continue

            price = close[t, a]
            lastpx[a] = price

            if ok_bar:
                if tp_from_avg:
                    tp_price = avg[a] * tp_mult
                else:
                    tp_price = base_price[a] * tp_mult
                tp_hit = high[t, a] >= tp_price

                sl_hit = False
                sl_price = 0.0
                if sl_pct > 0:
                    sl_price = avg[a] * (1 - sl_pct / 100.0)
                    sl_hit = low[t, a] <= sl_price

                time_hit = max_dur > 0 and (own_idx[t, a] - entry_own[a]) >= max_dur

                if tp_hit or sl_hit or time_hit:
                    # priorité SL > TP > durée max (comme le mono-asset)
                    if sl_hit:
                        exit_price = sl_price
                        reason = 2
                    elif tp_hit:
                        exit_price = tp_price
                        reason = 0
                    else:
                        exit_price = price
                        reason = 3
                    gross = exit_price * qty[a]
                    fees = (invested[a] + gross) * commission
                    pnl = gross - invested[a] - fees
                    pnl_pct = ((exit_price / avg[a]) - 1) * 100.0
                    capital += invested[a] + pnl

                    if n_tr == tr_i.shape[0]:
                        tr_i = _grow2(tr_i)
                        tr_f = _grow2(tr_f)
                        tr_sb = _grow2(tr_sb)
                        tr_sp = _grow2(tr_sp)
                    _write_trade(tr_i, tr_f, tr_sb, tr_sp, n_tr, a, entry_bar[a], t, reason, exit_price,
                                 pnl, pnl_pct, so_cnt, base_price, avg, invested, qty, so_bar_buf, so_px_buf)
                    n_tr += 1
                    in_pos[a] = False
                    last_close_bar[a] = t
                    continue  # position fermée : retirée de `order`

                if so_enabled:
                    capital = _so_step(
                        a, t, price, prev_close[t, a], atr[t, a] if mode == 0 else 0.0, signal[t, a], mode,
                        max_so, so_size_tbl, atr_mult_tbl, dev_tbl, cum_tbl,
                        qty, invested, avg, base_price, last_so, so_cnt, so_bar_buf, so_px_buf, capital)
            order[w] = a
            w += 1
        n_open = w

        # ── Phase 2 : nouvelles entrées (Base Order) ─────────────────────────
        slots = max_active - n_open
        if slots > 0 and ok_bar:
            for a in range(n_assets):
                if slots <= 0:
                    break
                if in_pos[a] or last_close_bar[a] == t or not signal[t, a]:
                    continue
                if capital < base_order:
                    skipped[a] += 1
                    continue
                price = close[t, a]
                capital -= base_order
                in_pos[a] = True
                base_price[a] = price
                avg[a] = price
                last_so[a] = price
                lastpx[a] = price
                qty[a] = base_order / price
                invested[a] = base_order
                so_cnt[a] = 0
                entry_bar[a] = t
                entry_own[a] = own_idx[t, a]
                order[n_open] = a
                n_open += 1
                slots -= 1
                # le mono-asset évalue aussi les SO sur la barre d'entrée
                if so_enabled:
                    capital = _so_step(
                        a, t, price, prev_close[t, a], atr[t, a] if mode == 0 else 0.0, True, mode, max_so,
                        so_size_tbl, atr_mult_tbl, dev_tbl, cum_tbl,
                        qty, invested, avg, base_price, last_so, so_cnt, so_bar_buf, so_px_buf, capital)

        # ── Equity : cash + valeur de marché (dernier prix connu si barre absente) ──
        tot = capital
        for r in range(n_open):
            a = order[r]
            tot += qty[a] * lastpx[a]
            open_pos_sum += 1 + so_cnt[a]
        equity[t] = tot
        used = initial_capital - capital
        if used > max_used:
            max_used = used

    # ── Clôture forcée en fin de test (optionnelle, uniquement si la dernière barre est autorisée) ──
    w = 0
    n_forced = 0
    for r in range(n_open):
        a = order[r]
        if close_last and close_ok[a]:
            exit_price = last_close[a]
            gross = exit_price * qty[a]
            fees = (invested[a] + gross) * commission
            pnl = gross - invested[a] - fees
            pnl_pct = ((exit_price / avg[a]) - 1) * 100.0
            capital += invested[a] + pnl
            if n_tr == tr_i.shape[0]:
                tr_i = _grow2(tr_i)
                tr_f = _grow2(tr_f)
                tr_sb = _grow2(tr_sb)
                tr_sp = _grow2(tr_sp)
            _write_trade(tr_i, tr_f, tr_sb, tr_sp, n_tr, a, entry_bar[a], last_bar[a], 1, exit_price,
                         pnl, pnl_pct, so_cnt, base_price, avg, invested, qty, so_bar_buf, so_px_buf)
            n_tr += 1
            n_forced += 1
        else:
            order[w] = a
            w += 1
    n_open_end = w
    n_closed = n_tr

    if n_forced > 0:
        tot = capital
        for r in range(n_open_end):
            a = order[r]
            tot += qty[a] * lastpx[a]
        equity[n_bars - 1] = tot

    # ── Positions restant ouvertes : résultat latent (pas de mouvement de capital) ──
    for r in range(n_open_end):
        a = order[r]
        exit_price = last_close[a]
        gross = exit_price * qty[a]
        fees = (invested[a] + gross) * commission
        pnl = gross - invested[a] - fees
        pnl_pct = ((exit_price / avg[a]) - 1) * 100.0
        if n_tr == tr_i.shape[0]:
            tr_i = _grow2(tr_i)
            tr_f = _grow2(tr_f)
            tr_sb = _grow2(tr_sb)
            tr_sp = _grow2(tr_sp)
        _write_trade(tr_i, tr_f, tr_sb, tr_sp, n_tr, a, entry_bar[a], last_bar[a], 4, exit_price,
                     pnl, pnl_pct, so_cnt, base_price, avg, invested, qty, so_bar_buf, so_px_buf)
        n_tr += 1

    return (capital, n_open_end, equity, n_closed,
            tr_i[:n_tr], tr_f[:n_tr], tr_sb[:n_tr], tr_sp[:n_tr], skipped, open_pos_sum, max_used)


def _tables(p: ParametresDCA_SmartBotV2):
    n_levels = max(int(p.max_safe_order), 0) + 1
    # Tables calculées avec les mêmes expressions Python que le mono-asset (résultats identiques au bit près)
    so_size_tbl = np.array([p.safe_order * (p.safe_order_volume_scale ** k) for k in range(n_levels)])
    atr_mult_tbl = np.array([p.atr_mult * (p.atr_mult_step_scale ** k) for k in range(n_levels)])
    devs = [p.price_deviation * (p.deviation_scale ** k) for k in range(n_levels)]
    dev_tbl = np.array(devs)
    cum, running = [], 0.0
    for d in devs:  # déviation cumulée "From Base Order" : même suite d'additions que le mono-asset
        running += d
        cum.append(running)
    return so_size_tbl, atr_mult_tbl, dev_tbl, np.array(cum)


def _run(prep: PreparedPortfolio, p: ParametresDCA_SmartBotV2, max_active_trades: int):
    """Prépare les tableaux dépendant des paramètres puis appelle le noyau numba."""
    so_size_tbl, atr_mult_tbl, dev_tbl, cum_tbl = _tables(p)
    allowed = prep.allowed(p)
    close_ok = np.ascontiguousarray(allowed[prep.last_bar]) if p.close_last_trade \
        else np.zeros(len(prep.assets), dtype=np.bool_)
    effective_stop_loss = float(p.stop_loss) if p.strategy_mode == "stop_loss" else 0.0

    return _portfolio_kernel(
        prep.close, prep.high, prep.low, prep.prev_close, prep.present, prep.entry_signals(p), prep.atr_for(p),
        allowed, prep.own_idx, prep.last_close, prep.last_bar, close_ok,
        _MODES.get(p.pricedevbase, _MODE_NONE),
        1 + p.take_profit / 100.0,
        p.tp_type == "From Average Entry",
        effective_stop_loss,
        int(p.max_trade_duration_bars),
        p.strategy_mode == "dca",
        float(p.commission),
        int(p.max_safe_order),
        float(p.base_order),
        float(p.initial_capital),
        int(max_active_trades),
        so_size_tbl, atr_mult_tbl, dev_tbl, cum_tbl,
        bool(p.close_last_trade),
    )


# ═══════════════════════════════════════════════════════════════════════════
# API compatible avec backtest_smartbot_v2_multi_portfolio
# ═══════════════════════════════════════════════════════════════════════════

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _individual_positions(p: ParametresDCA_SmartBotV2, so_sizes: np.ndarray, trade_id: str, base: float,
                          exit_price: float, entry_str: str, exit_str: Optional[str], reason: str,
                          so_prices: List[float], so_strs: List[str], is_open: bool) -> List[Dict[str, Any]]:
    """Positions individuelles (BO + chaque SO) d'un trade, avec les mêmes formules que le mono-asset."""
    out: List[Dict[str, Any]] = []
    legs = [("BO_1", entry_str, base, float(p.base_order))]
    legs += [(f"SO_{k}", so_strs[k - 1], so_prices[k - 1], float(so_sizes[k - 1]))
             for k in range(1, len(so_prices) + 1)]
    for typ, e_str, e_price, size in legs:
        q = size / e_price
        proceeds = exit_price * q
        fees = (size + proceeds) * p.commission
        pnl = proceeds - size - fees
        pos: Dict[str, Any] = {
            "type": typ,
            "entry_time": e_str,
            "entry_price": float(e_price),
            "size_usd": float(size),
            "qty": float(q),
        }
        if is_open:
            pos["current_price"] = float(exit_price)
        else:
            pos["exit_time"] = exit_str
            pos["exit_price"] = float(exit_price)
        pos["pnl"] = float(pnl)
        pos["pnl_pct"] = float(((exit_price / e_price) - 1) * 100.0)
        if is_open:
            pos["is_open"] = True
        pos["is_win"] = bool(pnl > 0)
        if not is_open:
            pos["signal"] = reason
        pos["trade_id"] = trade_id
        out.append(pos)
    return out


def backtest_portfolio_fast(
    assets_data: Union[Dict[str, pd.DataFrame], PreparedPortfolio],
    parametres: ParametresDCA_SmartBotV2,
    max_active_trades: int = 3,
    verbose: bool = False,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.Series], Dict[str, Dict], pd.Series, Dict]:
    """Retourne (trades_par_asset, {}, stats_par_asset, equity_combinée, stats_combinées).

    Même structure de retour que l'ancien ``backtest_smartbot_v2_multi_portfolio`` : DataFrames de trades
    (colonnes du mono-asset + ``quantity``, ``invested``, ``is_open``, ``individual_positions``), stats par
    asset avec ``individual_positions`` (``trade_id`` = f"{asset}_{n}") et ``open_trades``.
    Les trades encore ouverts en fin de période sont inclus (``is_open=True``, PnL latent).
    L'equity combinée est cash + valeur de marché des positions (dernier prix connu si une barre manque).
    """
    prep = assets_data if isinstance(assets_data, PreparedPortfolio) else PreparedPortfolio(assets_data)
    p = parametres
    capital, n_open_end, equity, n_closed, tr_i, tr_f, tr_sb, tr_sp, skipped, _, _ = _run(prep, p, max_active_trades)
    so_sizes = _tables(p)[0]
    tl = prep.timeline

    # Libellés de dates (calculés une seule fois pour les barres utilisées)
    bars = np.unique(np.concatenate([tr_i[:, 1], tr_i[:, 2]] + [
        tr_sb[i, : tr_i[i, 3]] for i in range(len(tr_i))])) if len(tr_i) else np.array([], dtype=np.int64)
    str_of = dict(zip(bars.tolist(), tl.take(bars).strftime(_TS_FMT))) if len(bars) else {}

    per_asset_trades: Dict[str, pd.DataFrame] = {}
    per_asset_stats: Dict[str, Dict] = {}

    for j, asset in enumerate(prep.assets):
        sel = np.flatnonzero(tr_i[:, 0] == j)
        if sel.size == 0:
            per_asset_trades[asset] = pd.DataFrame()
            per_asset_stats[asset] = {
                "total_trades": 0, "total_orders_placed": 0, "total_deals": 0, "total_so_placed": 0,
                "winning_trades": 0, "losing_trades": 0, "total_events": 0, "win_rate": 0.0,
                "win_rate_tradingview": 0.0, "total_positions": 0, "total_pnl": 0.0,
                "avg_pnl_per_trade": 0.0, "avg_so_per_trade": 0.0, "max_so_used": 0,
                "individual_positions": [], "open_trades": [], "skipped_trades": int(skipped[j]),
            }
            continue

        so_counts = tr_i[sel, 3]
        reasons = tr_i[sel, 4]
        is_open = reasons == _R_OPEN
        so_times = [list(tl.take(tr_sb[s, :c])) for s, c in zip(sel, so_counts)]
        so_prices = [tr_sp[s, :c].tolist() for s, c in zip(sel, so_counts)]

        positions_per_trade: List[List[Dict[str, Any]]] = []
        for n, s in enumerate(sel):
            c = int(tr_i[s, 3])
            positions_per_trade.append(_individual_positions(
                p, so_sizes, f"{asset}_{n + 1}", float(tr_f[s, 0]), float(tr_f[s, 2]),
                str_of[int(tr_i[s, 1])], None if is_open[n] else str_of[int(tr_i[s, 2])],
                str(_REASON_LABELS[reasons[n]]), so_prices[n],
                [str_of[int(b)] for b in tr_sb[s, :c]], bool(is_open[n])))

        df_trades = pd.DataFrame({
            "entry_time": tl.take(tr_i[sel, 1]),
            "exit_time": tl.take(tr_i[sel, 2]),
            "entry_price": tr_f[sel, 0],
            "avg_entry_price": tr_f[sel, 1],
            "exit_price": tr_f[sel, 2],
            "reason": _REASON_LABELS[reasons],
            "so_count": so_counts,
            "so_times": so_times,
            "so_prices": so_prices,
            "total_invested": tr_f[sel, 3],
            "total_position_size": tr_f[sel, 4],
            "pnl": tr_f[sel, 5],
            "pnl_pct": tr_f[sel, 6],
            "individual_positions": positions_per_trade,
            "quantity": tr_f[sel, 4],
            "invested": tr_f[sel, 3],
            "is_open": is_open,
        })
        per_asset_trades[asset] = df_trades

        closed = df_trades[~is_open]
        winning = closed[closed["pnl"] > 0]
        total_so = int(df_trades["so_count"].sum())
        total_deals = len(df_trades)
        total_trades = total_deals + total_so  # BO + SO

        all_positions = [pos for plist in positions_per_trade for pos in plist]
        winning_positions = sum(1 for pos in all_positions if pos["pnl"] > 0)
        win_rate_tv = (winning_positions / len(all_positions) * 100) if all_positions else 0

        per_asset_stats[asset] = {
            "total_trades": total_trades,
            "total_orders_placed": int(total_trades),
            "total_deals": int(total_deals),
            "total_so_placed": total_so,
            "winning_trades": len(winning),
            "losing_trades": len(closed) - len(winning),
            "total_events": total_trades,
            "win_rate": (len(winning) / total_trades * 100) if total_trades > 0 else 0,
            "win_rate_tradingview": float(win_rate_tv),
            "total_positions": len(all_positions),
            "total_pnl": float(df_trades["pnl"].sum()),
            "avg_pnl_per_trade": float(df_trades["pnl"].mean()),
            "avg_so_per_trade": float(df_trades["so_count"].mean()),
            "max_so_used": int(df_trades["so_count"].max()),
            "individual_positions": all_positions,
            "open_trades": df_trades[is_open].to_dict("records"),
            "skipped_trades": int(skipped[j]),
        }

    # Drawdown latent basé sur l'equity (même méthode que le mono-asset)
    init = float(p.initial_capital)
    if len(equity):
        peak_equity = np.maximum.accumulate(equity)
        drawdowns = equity - peak_equity
        max_drawdown = float(np.min(drawdowns))
        dd_pct = np.where(peak_equity > 0, (drawdowns / peak_equity) * 100, 0.0)
        max_drawdown_pct = float(np.min(dd_pct))
        final_equity = float(equity[-1])
    else:
        max_drawdown, max_drawdown_pct, final_equity = 0.0, 0.0, init

    combined_equity = pd.Series(equity, index=tl.rename("timestamp"), name="equity")

    stats_values = list(per_asset_stats.values())
    total_trades_c = sum(s.get("total_trades", 0) for s in stats_values)
    total_so_c = sum(s.get("total_so_placed", 0) for s in stats_values)
    winning_c = sum(s.get("winning_trades", 0) for s in stats_values)
    total_pnl_c = sum(s.get("total_pnl", 0) for s in stats_values)

    combined_stats = {
        "initial_capital": init,
        "final_capital": float(capital),
        "total_return_pct": float((total_pnl_c / init) * 100) if init > 0 else 0.0,
        "total_trades": total_trades_c,
        "total_orders_placed": sum(s.get("total_orders_placed", 0) for s in stats_values),
        "total_so_placed": total_so_c,
        "winning_trades": winning_c,
        "losing_trades": sum(s.get("losing_trades", 0) for s in stats_values),
        "total_pnl": total_pnl_c,
        "avg_pnl_per_trade": float(total_pnl_c / total_trades_c) if total_trades_c > 0 else 0.0,
        "avg_so_per_trade": float(total_so_c / total_trades_c) if total_trades_c > 0 else 0.0,
        "max_so_used": int(max((s.get("max_so_used", 0) for s in stats_values), default=0)),
        "win_rate_tradingview": float(winning_c / total_trades_c * 100) if total_trades_c > 0 else 0.0,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown_pct,
        "open_positions": int(n_open_end),
        "max_active_trades": max_active_trades,
        "skipped_trades": int(skipped.sum()),
        "final_equity": final_equity,
        "return_equity_pct": float((final_equity - init) / init * 100) if init > 0 else 0.0,
    }

    if verbose:
        print(f"{'=' * 80}\n📈 RÉSULTATS PORTFOLIO (rapide)\n{'=' * 80}")
        print(f"Capital Initial:    ${init:,.2f}")
        print(f"Capital Final:      ${capital:,.2f}  (cash, hors positions ouvertes)")
        print(f"Equity Finale:      ${final_equity:,.2f}")
        print(f"Max Drawdown:       ${max_drawdown:,.2f} ({max_drawdown_pct:.2f}%)")
        print(f"Positions ouvertes: {n_open_end}\n{'=' * 80}")

    return per_asset_trades, {}, per_asset_stats, combined_equity, combined_stats


# ═══════════════════════════════════════════════════════════════════════════
# Mono-asset rapide : même signature et même format que backtester_exact.backtest_smartbot_v2
# ═══════════════════════════════════════════════════════════════════════════


def backtest_mono_fast(
    prix: pd.DataFrame, parametres: ParametresDCA_SmartBotV2, verbose: bool = False
) -> Tuple[pd.DataFrame, pd.Series, Dict]:
    """Équivalent rapide de ``backtest_smartbot_v2`` (mêmes trades, equity, stats, positions individuelles).

    Utilise le noyau numba avec 1 asset et 1 slot. Retombe sur le mono-asset d'origine si ``verbose=True``
    (logs détaillés demandés) ou si l'index n'est pas unique / trié.
    """
    from backtester_exact import backtest_smartbot_v2

    for c in ("Open", "High", "Low", "Close"):
        assert c in prix.columns, f"❌ Colonne manquante: {c}"
    idx = prix.index
    if verbose or len(prix) < 2 or not idx.is_unique or not idx.is_monotonic_increasing:
        return backtest_smartbot_v2(prix, parametres, verbose=verbose)

    p = parametres
    n = len(prix)
    prep = PreparedPortfolio({"X": prix})
    (capital, n_open_end, equity, n_closed, tr_i, tr_f, tr_sb, tr_sp, _skipped,
     open_pos_sum, max_used) = _run(prep, p, 1)
    class _Ts:  # accès indexé mémoïsé (l'indexation d'un DatetimeIndex pandas est lente)
        def __init__(self, index):
            self._index, self._memo = index, {}

        def __getitem__(self, i):
            t = self._memo.get(i)
            if t is None:
                t = self._memo[i] = self._index[i]
            return t

    tl = _Ts(prep.timeline)
    so_sizes = _tables(p)[0]
    effective_stop_loss = p.stop_loss if p.strategy_mode == "stop_loss" else 0.0
    n_all = len(tr_i)

    def so_list(k):
        c = int(tr_i[k, 3])
        return [(tl[int(tr_sb[k, s])], float(tr_sp[k, s]), so_sizes[s], s + 1) for s in range(c)]

    def closed_positions(k, exit_price, label):
        base = float(tr_f[k, 0])
        legs = [("BO_0", tl[int(tr_i[k, 1])], base, p.base_order)]
        legs += [(f"SO_{num}", t_, pr, sz) for (t_, pr, sz, num) in so_list(k)]
        out = []
        for typ, e_time, e_price, size in legs:
            q = size / e_price
            proceeds = exit_price * q
            fees = (size + proceeds) * p.commission
            pnl = proceeds - size - fees
            pos = {"type": typ, "entry_time": e_time, "entry_price": e_price, "size_usd": size, "qty": q,
                   "exit_price": exit_price, "pnl": pnl, "pnl_pct": ((exit_price / e_price) - 1) * 100.0}
            if label is not None:
                pos["is_win"] = pnl > 0
                pos["signal"] = label
            out.append(pos)
        return out

    transactions = []
    for k in range(n_closed):
        code = int(tr_i[k, 4])
        exit_price = float(tr_f[k, 2])
        reason = str(_REASON_LABELS[code])
        if code == _R_SL:
            label = f"SL @ {effective_stop_loss}%"
        elif code == _R_TP:
            label = f"TP @ {p.take_profit}%"
        elif code == _R_TIME:
            label = f"TIME @ {p.max_trade_duration_bars} bars"
        else:  # END : clôture forcée, positions sans is_win/signal comme le mono-asset
            label = None
        sl_ = so_list(k)
        transactions.append({
            "entry_time": tl[int(tr_i[k, 1])],
            "exit_time": tl[int(tr_i[k, 2])],
            "entry_price": float(tr_f[k, 0]),
            "avg_entry_price": float(tr_f[k, 1]),
            "exit_price": exit_price,
            "reason": reason,
            "so_count": int(tr_i[k, 3]),
            "so_times": [x[0] for x in sl_],
            "so_prices": [x[1] for x in sl_],
            "total_invested": float(tr_f[k, 3]),
            "total_position_size": float(tr_f[k, 4]),
            "pnl": float(tr_f[k, 5]),
            "pnl_pct": float(tr_f[k, 6]),
            "individual_positions": closed_positions(k, exit_price, label),
        })

    open_trades_at_end = 0
    open_trade_details = None
    if n_open_end > 0:  # 1 seul slot : au plus une position ouverte
        open_trades_at_end = 1
        k = n_all - 1
        cur = float(tr_f[k, 2])
        base = float(tr_f[k, 0])
        sl_ = so_list(k)
        legs = [("BO_0", tl[int(tr_i[k, 1])], base, p.base_order)]
        legs += [(f"SO_{num}", t_, pr, sz) for (t_, pr, sz, num) in sl_]
        open_pos = []
        for typ, e_time, e_price, size in legs:
            q = size / e_price
            proceeds = cur * q
            fees = (size + proceeds) * p.commission
            pnl = proceeds - size - fees
            open_pos.append({"type": typ, "entry_time": e_time, "entry_price": e_price, "size_usd": size,
                             "qty": q, "current_price": cur, "pnl": pnl,
                             "pnl_pct": ((cur / e_price) - 1) * 100.0, "is_open": True, "is_win": pnl > 0})
        open_trade_details = {
            "entry_time": tl[int(tr_i[k, 1])],
            "current_time": tl[-1],
            "entry_price": base,
            "avg_entry_price": float(tr_f[k, 1]),
            "current_price": cur,
            "so_count": int(tr_i[k, 3]),
            "so_times": [x[0] for x in sl_],
            "so_prices": [x[1] for x in sl_],
            "total_invested": float(tr_f[k, 3]),
            "total_position_size": float(tr_f[k, 4]),
            "unrealized_pnl": float(tr_f[k, 5]),
            "unrealized_pnl_pct": float(tr_f[k, 6]),
            "individual_positions": open_pos,
        }

    df_trades = pd.DataFrame(transactions)
    courbe_equite = pd.Series(equity, index=prix.index)

    peak_equity = np.maximum.accumulate(equity)
    drawdowns = equity - peak_equity
    max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
    drawdown_pct_array = np.where(peak_equity > 0, (drawdowns / peak_equity) * 100, 0.0)
    max_drawdown_pct = float(np.min(drawdown_pct_array)) if len(drawdown_pct_array) > 0 else 0.0

    total_days = max((prix.index[-1] - prix.index[0]).days, 1)
    avg_open_positions = float(open_pos_sum / n)
    max_capital_used = float(max_used)
    max_capital_used_pct = (max_capital_used / p.initial_capital * 100) if p.initial_capital > 0 else 0.0

    n_open_positions = len(open_trade_details["individual_positions"]) if open_trade_details else 0
    unrealized = float(open_trade_details["unrealized_pnl"]) if open_trade_details else 0.0

    if not df_trades.empty:
        winning_trades = df_trades[df_trades["pnl"] > 0]
        losing_trades = df_trades[df_trades["pnl"] <= 0]
        time_closed_deals = int((df_trades["reason"] == "TIME").sum())
        total_so_placed = int(df_trades["so_count"].sum())
        total_individual_positions = 0
        winning_individual_positions = 0
        for plist in df_trades["individual_positions"]:
            for pos in plist:
                total_individual_positions += 1
                if pos["pnl"] > 0:
                    winning_individual_positions += 1
        win_rate_tv = float(winning_individual_positions / total_individual_positions * 100) \
            if total_individual_positions > 0 else 0.0
        total_positions_including_open = int(total_individual_positions + n_open_positions)
        total_pnl_value = float(df_trades["pnl"].sum()) + (unrealized if open_trade_details else 0.0)
        ret_pct = float(total_pnl_value / p.initial_capital * 100) if p.initial_capital > 0 else 0.0
        statistiques = {
            "total_trades": total_positions_including_open,
            "total_orders_placed": total_positions_including_open,
            "total_deals": len(df_trades) + open_trades_at_end,
            "total_so_placed": total_so_placed,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "total_individual_positions": total_individual_positions,
            "winning_individual_positions": winning_individual_positions,
            "win_rate_tradingview": win_rate_tv,
            "win_rate_deals": float(len(winning_trades) / len(df_trades) * 100),
            "total_pnl": total_pnl_value,
            "avg_pnl_per_trade": float(df_trades["pnl"].mean()),
            "avg_win": float(winning_trades["pnl"].mean()) if len(winning_trades) > 0 else 0.0,
            "avg_loss": float(losing_trades["pnl"].mean()) if len(losing_trades) > 0 else 0.0,
            "largest_win": float(df_trades["pnl"].max()),
            "largest_loss": float(df_trades["pnl"].min()),
            "avg_so_per_trade": float(df_trades["so_count"].mean()),
            "max_so_used": int(df_trades["so_count"].max()),
            "total_invested_avg": float(df_trades["total_invested"].mean()),
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "initial_capital": float(p.initial_capital),
            "final_capital": float(capital),
            "capital_return_pct": ret_pct,
            "open_trades_at_end": open_trades_at_end,
            "time_closed_deals": time_closed_deals,
            "open_trade": open_trade_details,
            "trades_per_day": float(len(df_trades) / total_days),
            "avg_open_positions_per_day": avg_open_positions,
            "max_capital_used": max_capital_used,
            "max_capital_used_pct": max_capital_used_pct,
            "total_days": total_days,
        }
    else:
        open_so_count = int(open_trade_details["so_count"]) if open_trade_details else 0
        ret_pct = float(unrealized / p.initial_capital * 100) if p.initial_capital > 0 else 0.0
        statistiques = {
            "total_trades": int(n_open_positions),
            "total_orders_placed": int(n_open_positions),
            "total_deals": int(open_trades_at_end),
            "total_so_placed": open_so_count,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_individual_positions": int(n_open_positions),
            "winning_individual_positions": 0,
            "win_rate_tradingview": 0.0,
            "win_rate_deals": 0.0,
            "total_pnl": unrealized,
            "avg_pnl_per_trade": 0.0,
            "avg_so_per_trade": float(open_so_count) if n_open_positions > 0 else 0.0,
            "max_so_used": open_so_count,
            "total_invested_avg": float(open_trade_details["total_invested"]) if open_trade_details else 0.0,
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "initial_capital": float(p.initial_capital),
            "final_capital": float(capital),
            "capital_return_pct": ret_pct,
            "open_trades_at_end": open_trades_at_end,
            "time_closed_deals": 0,
            "open_trade": open_trade_details,
            "trades_per_day": 0.0,
            "avg_open_positions_per_day": avg_open_positions,
            "max_capital_used": max_capital_used,
            "max_capital_used_pct": max_capital_used_pct,
            "total_days": total_days,
        }

    return df_trades, courbe_equite, statistiques


# ═══════════════════════════════════════════════════════════════════════════
# Évaluation légère + optimiseur
# ═══════════════════════════════════════════════════════════════════════════


def evaluate_portfolio(
    prep: PreparedPortfolio, params: ParametresDCA_SmartBotV2, max_active_trades: int = 3
) -> Dict[str, float]:
    """Métriques essentielles d'un jeu de paramètres, sans construire de DataFrame.

    Le rendement et le drawdown sont calculés sur l'EQUITY (cash + valeur de marché des positions
    ouvertes), mesure pertinente pour une stratégie DCA qui peut terminer avec des positions ouvertes.
    ``n_trades`` ne compte que les deals clôturés.
    """
    capital, n_open_end, equity, n_closed, tr_i, tr_f, _, _, skipped, _, _ = _run(prep, params, max_active_trades)
    init = float(params.initial_capital)
    if len(equity):
        peak = np.maximum.accumulate(equity)
        dd_pct = float(-np.min((equity - peak) / peak) * 100)
        final_equity = float(equity[-1])
    else:
        dd_pct, final_equity = 0.0, init

    pnl = tr_f[:n_closed, 5]
    ret = (final_equity - init) / init * 100
    return {
        "return_pct": float(ret),
        "max_dd_pct": dd_pct,
        "calmar": float(ret / max(dd_pct, 1.0)),
        "final_equity": final_equity,
        "final_cash": float(capital),
        "realized_pnl": float(pnl.sum()) if n_closed else 0.0,
        "n_trades": int(n_closed),
        "n_so": int(tr_i[:n_closed, 3].sum()) if n_closed else 0,
        "win_rate_deals": float((pnl > 0).sum() / n_closed * 100) if n_closed else 0.0,
        "open_positions": int(n_open_end),
        "skipped_trades": int(skipped.sum()),
    }


Objective = Union[str, Callable[[Dict[str, float]], float]]
Space = Dict[str, Union[List[Any], Tuple[float, float]]]


def _score(metrics: Dict[str, float], objective: Objective, max_dd_limit: Optional[float], min_trades: int) -> float:
    if metrics["n_trades"] < min_trades:
        return float("-inf")
    if max_dd_limit is not None and metrics["max_dd_pct"] > max_dd_limit:
        return float("-inf")
    if callable(objective):
        return float(objective(metrics))
    return float(metrics[objective])


def _sample_trials(space: Space, n_trials: int, grid: bool, seed: int) -> List[Dict[str, Any]]:
    rng = np.random.default_rng(seed)
    names = list(space.keys())

    if grid:
        for k, v in space.items():
            if not isinstance(v, list):
                raise ValueError(f"grid=True: '{k}' doit être une liste de valeurs")
        combos = [dict(zip(names, c)) for c in itertools.product(*(space[k] for k in names))]
        if len(combos) > n_trials:
            keep = rng.choice(len(combos), size=n_trials, replace=False)
            combos = [combos[i] for i in sorted(keep)]
        return combos

    trials: List[Dict[str, Any]] = []
    seen = set()
    attempts = 0
    while len(trials) < n_trials and attempts < n_trials * 20:
        attempts += 1
        trial = {}
        for k, v in space.items():
            if isinstance(v, list):
                trial[k] = v[int(rng.integers(len(v)))]
            elif isinstance(v, tuple) and len(v) == 2:
                lo, hi = v
                if isinstance(lo, int) and isinstance(hi, int):
                    trial[k] = int(rng.integers(lo, hi + 1))
                else:
                    trial[k] = round(float(rng.uniform(lo, hi)), 6)
            else:
                raise ValueError(f"'{k}': attendu une liste de choix ou un tuple (min, max)")
        key = tuple(sorted(trial.items()))
        if key not in seen:
            seen.add(key)
            trials.append(trial)
    return trials


def optimize_portfolio(
    assets_data: Union[Dict[str, pd.DataFrame], PreparedPortfolio],
    space: Space,
    n_trials: int = 500,
    base_params: Optional[ParametresDCA_SmartBotV2] = None,
    max_active_trades: int = 3,
    objective: Objective = "calmar",
    max_dd_limit: Optional[float] = None,
    min_trades: int = 1,
    n_jobs: Optional[int] = None,
    seed: int = 0,
    grid: bool = False,
    progress: bool = True,
) -> pd.DataFrame:
    """Recherche de paramètres sur un portefeuille complet.

    Args:
        space: {nom_param: [choix...]} ou {nom_param: (min, max)} (int si bornes int, sinon float).
               Noms valides : champs de ``ParametresDCA_SmartBotV2`` + ``max_active_trades``.
        objective: "calmar" (rendement / drawdown, défaut), "return_pct", "final_equity", "realized_pnl"
                   ou une fonction ``f(metrics) -> float``.
        max_dd_limit: drawdown equity max accepté (en %) ; au-delà le score est -inf.
        min_trades: nombre minimal de deals clôturés pour être éligible.
        grid: True = produit cartésien des listes (échantillonné à n_trials si trop grand).

    Returns:
        DataFrame trié par score décroissant (paramètres testés + métriques).

    Attention : plus on teste de combinaisons, plus on risque le sur-apprentissage. Valider les
    meilleurs jeux sur une période non utilisée pour l'optimisation.
    """
    prep = assets_data if isinstance(assets_data, PreparedPortfolio) else PreparedPortfolio(assets_data)
    base = base_params or ParametresDCA_SmartBotV2()
    valid = {f.name for f in fields(ParametresDCA_SmartBotV2)} | {"max_active_trades"}
    unknown = set(space) - valid
    if unknown:
        raise ValueError(f"Paramètres inconnus: {sorted(unknown)}")

    trials = _sample_trials(space, n_trials, grid, seed)
    if not trials:
        raise ValueError("Aucun essai généré")

    def build(trial: Dict[str, Any]) -> Tuple[ParametresDCA_SmartBotV2, int]:
        overrides = dict(trial)
        slots = int(overrides.pop("max_active_trades", max_active_trades))
        return replace(base, **overrides), slots

    built = [build(t) for t in trials]
    for p, _ in built:  # indicateurs calculés en série (pandas_ta ne libère pas le GIL)
        prep.warm(p)

    def run_one(i: int) -> Dict[str, Any]:
        p, slots = built[i]
        m = evaluate_portfolio(prep, p, slots)
        row = dict(trials[i])
        row.update(m)
        row["score"] = _score(m, objective, max_dd_limit, min_trades)
        return row

    rows: List[Dict[str, Any]] = [run_one(0)]  # 1er essai en série : compile le noyau numba une seule fois
    workers = n_jobs or os.cpu_count() or 1
    step = max(len(trials) // 10, 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for k, row in enumerate(pool.map(run_one, range(1, len(trials))), start=2):
            rows.append(row)
            if progress and k % step == 0:
                print(f"   optimisation: {k}/{len(trials)}")

    out = pd.DataFrame(rows).sort_values("score", ascending=False, kind="stable").reset_index(drop=True)
    return out
