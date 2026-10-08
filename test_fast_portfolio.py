#!/usr/bin/env python3
"""Vérifie que le backtester portefeuille rapide applique EXACTEMENT la logique du mono-asset de main.

1. Indépendance : avec capital illimité et assez de slots, chaque asset du portefeuille doit donner
   exactement les mêmes trades (et positions individuelles, trade ouvert final) que
   ``backtest_smartbot_v2`` lancé seul. Couvre SO ATR / dernier SO / Base Order, TP depuis moyenne ou BO,
   Stop Loss, durée max, horaires de marché US, clôture forcée ou trade ouvert en fin de période.
2. 1 asset / 1 slot : trades, equity, stats (drawdown, capital final, PnL) identiques au mono-asset,
   y compris avec un capital serré (entrées et SO refusés).
3. Interactions (capital partagé + slots + assets désalignés) : comparaison à une référence Python pure,
   écrite à part, qui réutilise les fonctions du mono-asset.
4. Masque d'horaires de marché vectorisé == fonction scalaire ``barre_autorisee``.
5. Cohérence de ``evaluate_portfolio`` et du format de sortie (compatible front / app.py).

Usage : python test_fast_portfolio.py
"""
import contextlib
import io
import itertools
import time

import numpy as np
import pandas as pd

import backtester_exact as bx
from backtester_exact import ParametresDCA_SmartBotV2 as P
from backtester_fast import PreparedPortfolio, _market_mask, backtest_portfolio_fast, evaluate_portfolio

TRADE_COLS = ["entry_time", "exit_time", "entry_price", "avg_entry_price", "exit_price", "reason",
              "so_count", "so_times", "so_prices", "total_invested", "total_position_size", "pnl", "pnl_pct"]

BASE = dict(dsc_rsi_threshold_low=30, mfi_threshold_low=45, bb_threshold_low=0.15, take_profit=2.0,
            price_deviation=3.0, deviation_scale=1.2, atr_mult=1.5, max_safe_order=6, commission=0.001,
            trading_timeframe="1h")
MODES = ["ATR", "From Last Safety Order", "From Base Order"]


def make_asset(n, seed, freq="1h", drop_frac=0.0, start="2022-01-01"):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.012, n)))
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    df = pd.DataFrame({
        "Open": c, "High": c * (1 + r.uniform(0, 0.01, n)), "Low": c * (1 - r.uniform(0, 0.01, n)),
        "Close": c, "Volume": r.uniform(1, 100, n),
    }, index=idx)
    if drop_frac:
        df = df.iloc[np.sort(r.choice(n, int(n * (1 - drop_frac)), replace=False))]
    return df


def mono(df, p):
    return bx.backtest_smartbot_v2(df, p, verbose=False)


def same_trades(a, b, label):
    if a.empty or b.empty:
        assert a.empty and b.empty, f"{label}: un seul des deux est vide ({len(a)} vs {len(b)})"
        return
    pd.testing.assert_frame_equal(a[TRADE_COLS].reset_index(drop=True), b[TRADE_COLS].reset_index(drop=True),
                                  check_exact=True, obj=label)


def check_positions(m_trades, f_closed, label):
    """Positions individuelles du mono-asset == celles du rapide (numérique, formules identiques)."""
    assert len(m_trades) == len(f_closed), label
    for (_, m_row), (_, f_row) in zip(m_trades.iterrows(), f_closed.iterrows()):
        mp, fp = m_row["individual_positions"], f_row["individual_positions"]
        assert len(mp) == len(fp), f"{label}: nb positions {len(mp)} != {len(fp)}"
        for x, y in zip(mp, fp):
            assert x["type"].split("_")[0] == y["type"].split("_")[0], (x["type"], y["type"])
            if x["type"].startswith("SO"):
                assert x["type"] == y["type"], (x["type"], y["type"])
            for k in ("entry_price", "size_usd", "qty", "exit_price", "pnl", "pnl_pct", "is_win"):
                if k == "is_win" and k not in x:  # le mono n'ecrit pas is_win a la cloture forcee (END)
                    continue
                assert x[k] == y[k], f"{label}: {k} {x[k]} != {y[k]}"
            assert pd.Timestamp(y["entry_time"], tz="UTC") == x["entry_time"]


def check_open(m_stats, f_df, label):
    """Trade resté ouvert en fin de période : mono ``open_trade`` == ligne is_open du rapide."""
    f_open = f_df[f_df["is_open"]] if not f_df.empty else f_df
    m_open = m_stats.get("open_trade")
    if m_open is None:
        assert len(f_open) == 0, f"{label}: ouvert côté rapide uniquement"
        return 1 if False else 0
    assert len(f_open) == 1, f"{label}: ouvert côté mono uniquement"
    r = f_open.iloc[0]
    for mk, fk in (("entry_time", "entry_time"), ("entry_price", "entry_price"),
                   ("avg_entry_price", "avg_entry_price"), ("so_count", "so_count"),
                   ("total_invested", "total_invested"), ("total_position_size", "total_position_size"),
                   ("unrealized_pnl", "pnl"), ("unrealized_pnl_pct", "pnl_pct"), ("so_times", "so_times"),
                   ("so_prices", "so_prices")):
        assert m_open[mk] == r[fk], f"{label}: open {mk} {m_open[mk]} != {r[fk]}"
    assert r["exit_price"] == m_open["current_price"] and r["exit_time"] == m_open["current_time"]
    for x, y in zip(m_open["individual_positions"], r["individual_positions"]):
        for k in ("entry_price", "size_usd", "qty", "pnl", "pnl_pct", "is_win"):
            assert x[k] == y[k], f"{label}: open position {k}"
        assert y["current_price"] == m_open["current_price"] and y["is_open"] is True
    return 1


# ───────────────────────────── 1. indépendance ─────────────────────────────
def independence_configs():
    cfgs = []
    for mode, dsc, tp_type, close_last in itertools.product(
            MODES, ["RSI", "RSI + MFI", "All Three"], ["From Average Entry", "From Base Order"], [False, True]):
        cfgs.append(dict(pricedevbase=mode, dsc=dsc, tp_type=tp_type, close_last_trade=close_last))
    for mode, cl in itertools.product(MODES, [False, True]):
        cfgs.append(dict(pricedevbase=mode, dsc="RSI", close_last_trade=cl, strategy_mode="stop_loss",
                         stop_loss=4.0))
        cfgs.append(dict(pricedevbase=mode, dsc="RSI", close_last_trade=cl, max_trade_duration_bars=30))
        cfgs.append(dict(pricedevbase=mode, dsc="RSI", close_last_trade=cl,
                         restrict_trading_to_us_market_hours=True))
        cfgs.append(dict(pricedevbase=mode, dsc="RSI + MFI", close_last_trade=cl, strategy_mode="stop_loss",
                         stop_loss=3.0, max_trade_duration_bars=40, restrict_trading_to_us_market_hours=True))
    cfgs.append(dict(pricedevbase="ATR", dsc="RSI", restrict_trading_to_us_market_hours=True,
                     trading_timeframe="1d", close_last_trade=True))
    cfgs.append(dict(pricedevbase="ATR", dsc="RSI", strategy_mode="stop_loss", stop_loss=2.0,
                     tp_type="From Base Order", max_trade_duration_bars=10))
    return cfgs


def test_independence(asset_sets):
    total = n_open = 0
    n_kinds = {"TP": 0, "SL": 0, "TIME": 0, "END": 0}
    for kw in independence_configs():
        p = P(**{**BASE, **kw, "initial_capital": 1e12})
        for label, assets in asset_sets.items():
            trades, _, _, equity, comb = backtest_portfolio_fast(assets, p, len(assets))
            for a, df in assets.items():
                m_trades, _, m_stats = mono(df, p)
                f_df = trades[a]
                f_closed = f_df[~f_df["is_open"]] if not f_df.empty else f_df
                lab = f"indep/{kw}/{label}/{a}"
                same_trades(m_trades, f_closed, lab)
                if not m_trades.empty:
                    check_positions(m_trades, f_closed, lab)
                    for k in n_kinds:
                        n_kinds[k] += int((m_trades["reason"] == k).sum())
                n_open += check_open(m_stats, f_df, lab)
                total += len(m_trades)
    assert n_kinds["SL"] > 0 and n_kinds["TIME"] > 0 and n_kinds["TP"] > 0, n_kinds
    print(f"OK  1. independance vs mono-asset ({total} deals {n_kinds}, {n_open} trades ouverts)")
    return total


# ───────────────────────────── 2. un seul asset ─────────────────────────────
def test_single_asset():
    total = 0
    df = make_asset(4000, 7)
    cfgs = []
    for mode, dsc, close_last, capital in itertools.product(MODES, ["RSI", "RSI + MFI"], [False, True],
                                                            [100_000.0, 4_000.0]):
        cfgs.append(dict(pricedevbase=mode, dsc=dsc, close_last_trade=close_last, initial_capital=capital))
        cfgs.append(dict(pricedevbase=mode, dsc=dsc, close_last_trade=close_last, initial_capital=capital,
                         strategy_mode="stop_loss", stop_loss=3.0, max_trade_duration_bars=50,
                         restrict_trading_to_us_market_hours=True))
    for kw in cfgs:
        p = P(**{**BASE, **kw})
        m_trades, m_eq, m_stats = mono(df, p)
        trades, _, stats, eq, comb = backtest_portfolio_fast({"X": df}, p, 1)
        f_df = trades["X"]
        f_closed = f_df[~f_df["is_open"]] if not f_df.empty else f_df
        lab = f"single/{kw}"
        same_trades(m_trades, f_closed, lab)
        pd.testing.assert_series_equal(m_eq, eq, check_exact=True, check_names=False, check_freq=False)
        check_open(m_stats, f_df, lab)
        assert m_stats.get("max_drawdown", 0.0) == comb["max_drawdown"], lab
        assert m_stats.get("max_drawdown_pct", 0.0) == comb["max_drawdown_pct"], lab
        if m_stats:
            assert m_stats["final_capital"] == comb["final_capital"], (m_stats["final_capital"], comb)
            assert m_stats.get("open_trades_at_end", 0) == comb["open_positions"], lab
            assert abs(m_stats["total_pnl"] - comb["total_pnl"]) < 1e-6, (m_stats["total_pnl"], comb["total_pnl"])
        total += len(m_trades)
    print(f"OK  2. 1 asset / 1 slot identique au mono-asset, equity et stats comprises ({total} deals)")
    return total


# ──────────────── 3. référence Python pure pour les interactions ────────────────
def ref_portfolio(assets, p, max_active):
    names = list(assets)
    ind = {a: bx.calculer_indicateurs_smartbot(df, p) for a, df in assets.items()}
    idx = {a: {ts: i for i, ts in enumerate(df.index)} for a, df in assets.items()}
    arrs = {a: {c: df[c].to_numpy(dtype=float) for c in ("Open", "Close", "High", "Low")} for a, df in assets.items()}
    timeline = None
    for df in assets.values():
        timeline = df.index if timeline is None else timeline.union(df.index)
    timeline = timeline.sort_values()
    sl_eff = p.stop_loss if p.strategy_mode == "stop_loss" else 0.0

    cap = float(p.initial_capital)
    S = {}  # états des positions ouvertes, dans l'ordre d'ouverture
    last_close_ts = {a: None for a in names}
    trades = {a: [] for a in names}
    skipped = 0
    equity = []
    lastpx = {}

    def so_check(a, i, st, price, ts):
        nonlocal cap
        sig = bx.evaluer_entry_signal(ind[a], i, p)
        if st["n"] >= p.max_safe_order:
            return
        trig = bx.calcular_so_trigger_price(p, st["base"], st["last_so"], st["n"],
                                           arrs[a]["Close"][i - 1], ind[a]["atr"][i])
        below = price <= trig
        fire = below if p.pricedevbase == "From Base Order" else (below and sig)
        if not fire:
            return
        size = bx.calcular_so_size(p, st["n"])
        so_qty, so_cost = bx.order_fill(size, price)
        if cap < so_cost:
            return
        st["inv"] += so_cost
        st["qty"] += so_qty
        st["avg"] = st["inv"] / st["qty"]
        st["last_so"] = price
        st["n"] += 1
        st["so_t"].append(ts)
        st["so_p"].append(price)
        cap -= so_cost

    def record(a, st, exit_price, ts_exit, reason, realize):
        nonlocal cap
        gross = exit_price * st["qty"]
        fees = (st["inv"] + gross) * p.commission
        pnl = gross - st["inv"] - fees
        pct = ((exit_price / st["avg"]) - 1) * 100.0
        if realize:
            cap += st["inv"] + pnl
        trades[a].append((st["entry_ts"], ts_exit, st["base"], st["avg"], exit_price, reason, st["n"],
                          list(st["so_t"]), list(st["so_p"]), st["inv"], st["qty"], pnl, pct))

    for ts in timeline:
        ok_bar = bx.barre_autorisee(ts, p)
        for a in list(S):
            i = idx[a].get(ts)
            if i is None:
                continue
            st = S[a]
            price = arrs[a]["Close"][i]
            lastpx[a] = price
            if not ok_bar:
                continue
            tp = st["avg"] * (1 + p.take_profit / 100.0) if p.tp_type == "From Average Entry" \
                else st["base"] * (1 + p.take_profit / 100.0)
            touch = arrs[a]["High"][i] if st["tp_live"] else price
            if p.price_tick > 0:
                touch = np.floor(touch / p.price_tick + 0.5) * p.price_tick
                tp_hit = touch + 1e-6 >= tp
            else:
                tp_hit = touch >= tp
            sl_price = st["avg"] * (1 - sl_eff / 100.0)
            sl_hit = sl_eff > 0 and arrs[a]["Low"][i] <= sl_price
            time_hit = p.max_trade_duration_bars > 0 and (i - st["entry_i"]) >= p.max_trade_duration_bars
            if sl_hit or tp_hit or time_hit:
                if sl_hit:
                    bar_open = arrs[a]["Open"][i]
                    exit_px = bar_open if bar_open <= sl_price else sl_price
                    record(a, st, exit_px, ts, "SL", True)
                elif tp_hit:
                    record(a, st, tp, ts, "TP", True)
                else:
                    record(a, st, price, ts, "TIME", True)
                del S[a]
                last_close_ts[a] = ts
            else:
                if p.strategy_mode == "dca":
                    so_check(a, i, st, price, ts)
                st["tp_live"] = True
        slots = max_active - len(S)
        for a in names:
            if slots <= 0 or not ok_bar:
                break
            i = idx[a].get(ts)
            if i is None or i < 1 or a in S or last_close_ts[a] == ts:
                continue
            if not bx.evaluer_entry_signal(ind[a], i, p):
                continue
            price = arrs[a]["Close"][i]
            order_qty, order_cost = bx.order_fill(p.base_order, price)
            if cap < order_cost:
                skipped += 1
                continue
            cap -= order_cost
            S[a] = dict(base=price, avg=price, last_so=price, n=0, inv=order_cost, qty=order_qty,
                        tp_live=False,
                        entry_ts=ts, entry_i=i, so_t=[], so_p=[])
            lastpx[a] = price
            slots -= 1
            if p.strategy_mode == "dca":
                so_check(a, i, S[a], price, ts)
        tot = cap
        for a, st in S.items():
            tot += st["qty"] * lastpx[a]
        equity.append(tot)

    forced = 0
    for a, st in list(S.items()):
        if p.close_last_trade and bx.barre_autorisee(assets[a].index[-1], p):
            record(a, st, assets[a]["Close"].iloc[-1], assets[a].index[-1], "END", True)
            del S[a]
            forced += 1
    if forced:
        tot = cap
        for a, st in S.items():
            tot += st["qty"] * lastpx[a]
        equity[-1] = tot
    for a, st in S.items():
        record(a, st, assets[a]["Close"].iloc[-1], assets[a].index[-1], "OPEN", False)
    return trades, pd.Series(equity, index=timeline), cap, skipped, len(S)


def test_interactions(asset_sets):
    total = n_open = 0
    cases = []
    for mode, dsc, close_last, tp_type in itertools.product(MODES, ["RSI", "RSI + MFI"], [False, True],
                                                            ["From Average Entry", "From Base Order"]):
        cases.append(dict(pricedevbase=mode, dsc=dsc, close_last_trade=close_last, tp_type=tp_type,
                          initial_capital=100_000.0))
    cases += [  # capital serré : refus d'entrées / de SO, slots saturés
        dict(pricedevbase="ATR", dsc="RSI", initial_capital=4_000.0),
        dict(pricedevbase="From Last Safety Order", dsc="RSI", initial_capital=3_000.0, close_last_trade=True),
        dict(pricedevbase="From Base Order", dsc="RSI + MFI", initial_capital=2_500.0),
        dict(pricedevbase="ATR", dsc="RSI", dsc2_enabled=True, dsc2="MFI", initial_capital=6_000.0),
        # stop loss / durée / horaires / mode sans SO
        dict(pricedevbase="ATR", dsc="RSI", strategy_mode="stop_loss", stop_loss=3.0, initial_capital=100_000.0),
        dict(pricedevbase="From Base Order", dsc="RSI", strategy_mode="stop_loss", stop_loss=5.0,
             max_trade_duration_bars=25, initial_capital=3_000.0, close_last_trade=True),
        dict(pricedevbase="From Last Safety Order", dsc="RSI + MFI", max_trade_duration_bars=40,
             initial_capital=5_000.0),
        dict(pricedevbase="ATR", dsc="RSI", restrict_trading_to_us_market_hours=True, initial_capital=6_000.0),
        dict(pricedevbase="From Base Order", dsc="RSI", restrict_trading_to_us_market_hours=True,
             close_last_trade=True, strategy_mode="stop_loss", stop_loss=4.0, max_trade_duration_bars=30,
             initial_capital=4_000.0),
        dict(pricedevbase="ATR", dsc="RSI", restrict_trading_to_us_market_hours=True, trading_timeframe="1d",
             initial_capital=100_000.0),
    ]
    for kw in cases:
        p = P(**{**BASE, **kw})
        for label, assets in asset_sets.items():
            for k in (1, 2, 3):
                r_trades, r_eq, r_cap, r_skipped, r_open = ref_portfolio(assets, p, k)
                trades, _, _, eq, comb = backtest_portfolio_fast(assets, p, k)
                for a in assets:
                    ref_df = pd.DataFrame(r_trades[a], columns=TRADE_COLS)
                    same_trades(ref_df, trades[a], f"inter/{kw}/{label}/k={k}/{a}")
                pd.testing.assert_series_equal(r_eq, eq, check_exact=True, check_names=False, check_freq=False,
                                               obj=f"inter equity {kw}/{label}/k={k}")
                assert r_cap == comb["final_capital"], (kw, r_cap, comb["final_capital"])
                assert r_skipped == comb["skipped_trades"], (r_skipped, comb["skipped_trades"])
                assert r_open == comb["open_positions"], (r_open, comb["open_positions"])
                total += sum(len(v) for v in r_trades.values())
                n_open += r_open
    print(f"OK  3. interactions capital/slots vs reference independante ({total} deals, {n_open} ouverts en fin)")
    return total


# ──────────────── 4. masque horaires de marché ────────────────
def test_market_mask():
    rng = np.random.default_rng(3)
    stamps = pd.DatetimeIndex(sorted(pd.Timestamp("2023-03-01", tz="UTC") + pd.to_timedelta(
        rng.integers(0, 400 * 24 * 3600, 3000), unit="s")))
    stamps = stamps.append(pd.DatetimeIndex(["2023-06-05 13:30:00", "2023-06-05 20:00:00", "2023-06-05 13:29:59",
                                             "2023-06-05 20:00:01", "2023-12-05 14:30:00", "2023-12-05 21:00:00",
                                             "2023-12-05 21:00:01"], tz="UTC")).sort_values()
    for tf in ("1h", "15m", "1d"):
        p = P(restrict_trading_to_us_market_hours=True, trading_timeframe=tf)
        vec = _market_mask(stamps, tf)
        scalar = np.array([bx.barre_autorisee(ts, p) for ts in stamps])
        assert (vec == scalar).all(), f"{tf}: {(vec != scalar).sum()} différences"
    naive = stamps.tz_localize(None)
    assert (_market_mask(naive, "1h") == _market_mask(stamps, "1h")).all()
    print("OK  4. masque horaires de marché vectorisé == fonction scalaire")


# ──────────────── 5. cohérence evaluate_portfolio + format de sortie ────────────────
def test_evaluate_and_format(assets):
    prep = PreparedPortfolio(assets)
    p = P(**{**BASE, "pricedevbase": "ATR", "dsc": "RSI + MFI", "close_last_trade": False,
             "strategy_mode": "stop_loss", "stop_loss": 6.0})
    m = evaluate_portfolio(prep, p, 3)
    trades, eq_assets, st, eq, comb = backtest_portfolio_fast(prep, p, 3)
    closed_all = [t[~t["is_open"]] for t in trades.values() if not t.empty]
    n_closed = sum(len(t) for t in closed_all)
    assert m["n_trades"] == n_closed
    assert abs(m["realized_pnl"] - sum(t["pnl"].sum() for t in closed_all)) < 1e-6
    assert m["final_cash"] == comb["final_capital"] and m["final_equity"] == comb["final_equity"]
    assert m["open_positions"] == comb["open_positions"]
    assert abs(m["max_dd_pct"] + comb["max_drawdown_pct"]) < 1e-9

    assert eq_assets == {} and eq.name == "equity" and eq.index.name == "timestamp"
    for key in ("initial_capital", "final_capital", "total_return_pct", "total_trades", "total_orders_placed",
                "total_so_placed", "winning_trades", "losing_trades", "total_pnl", "avg_pnl_per_trade",
                "avg_so_per_trade", "max_so_used", "win_rate_tradingview", "max_drawdown", "max_drawdown_pct",
                "open_positions", "max_active_trades"):
        assert key in comb, key
    n_pos_open = 0
    for a, s in st.items():
        for key in ("total_trades", "total_orders_placed", "total_deals", "total_so_placed", "winning_trades",
                    "losing_trades", "total_events", "win_rate", "win_rate_tradingview", "total_positions",
                    "total_pnl", "avg_pnl_per_trade", "avg_so_per_trade", "max_so_used",
                    "individual_positions", "open_trades"):
            assert key in s, (a, key)
        ids = [x["trade_id"] for x in s["individual_positions"]]
        assert all(i.startswith(a + "_") for i in ids)
        for pos in s["individual_positions"]:
            assert pos["type"][:3] in ("BO_", "SO_")
            if pos.get("is_open"):
                assert "current_price" in pos and "exit_time" not in pos
                n_pos_open += 1
            else:
                assert "exit_time" in pos and "exit_price" in pos
        assert len(s["open_trades"]) == (int(trades[a]["is_open"].sum()) if not trades[a].empty else 0)
    assert n_pos_open >= comb["open_positions"]
    print("OK  5. evaluate_portfolio coherent + format de sortie compatible")


def deep_equal(a, b, path="root"):
    """Egalité stricte récursive (dict / list / nombres / Timestamp)."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), f"{path}: clés {sorted(set(a) ^ set(b))}"
        for k in a:
            deep_equal(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), f"{path}: longueur {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            deep_equal(x, y, f"{path}[{i}]")
    else:
        assert (a is None and b is None) or a == b or (a != a and b != b), f"{path}: {a!r} != {b!r}"


def test_mono_fast():
    """backtest_smartbot_v2_fast == backtest_smartbot_v2 : trades, positions, equity et stats complets."""
    total = 0
    dfs = {"1h": make_asset(4000, 7), "ragged": make_asset(3000, 5, drop_frac=0.1),
           "naive": make_asset(2500, 11).tz_localize(None)}
    cfgs = []
    for mode, dsc, cl, cap in itertools.product(MODES, ["RSI", "RSI + MFI"], [False, True], [100_000.0, 3_500.0]):
        cfgs.append(dict(pricedevbase=mode, dsc=dsc, close_last_trade=cl, initial_capital=cap))
        cfgs.append(dict(pricedevbase=mode, dsc=dsc, close_last_trade=cl, initial_capital=cap,
                         strategy_mode="stop_loss", stop_loss=3.0, max_trade_duration_bars=40,
                         restrict_trading_to_us_market_hours=True))
    cfgs.append(dict(pricedevbase="ATR", dsc="RSI", dsc_rsi_threshold_low=1))
    cfgs.append(dict(pricedevbase="ATR", dsc="RSI", dsc_rsi_threshold_low=30, take_profit=500.0))
    for label, df in dfs.items():
        for kw in cfgs:
            p = P(**{**BASE, **kw})
            lab = f"mono_fast/{label}/{kw}"
            m_trades, m_eq, m_stats = mono(df, p)
            f_trades, f_eq, f_stats = bx.backtest_smartbot_v2_fast(df, p)
            assert m_trades.empty == f_trades.empty, lab
            if not m_trades.empty:
                assert list(m_trades.columns) == list(f_trades.columns), lab
                same_trades(m_trades, f_trades, lab)
                deep_equal(m_trades["individual_positions"].tolist(), f_trades["individual_positions"].tolist(),
                           lab + ".positions")
            pd.testing.assert_series_equal(m_eq, f_eq, check_exact=True, check_freq=False, check_names=False,
                                           obj=lab + " equity")
            deep_equal(m_stats, f_stats, lab + ".stats")
            total += len(m_trades)
    assert total > 300, total
    print(f"OK  7. mono rapide == mono d'origine: trades, positions, equity, stats ({total} deals)")
    return total


def test_wrapper(assets):
    p = P(**{**BASE, "pricedevbase": "ATR", "dsc": "RSI"})
    fast = bx.backtest_smartbot_v2_multi_portfolio(assets, p, 3)
    assert len(fast) == 5 and set(fast[0]) == set(assets)
    with contextlib.redirect_stdout(io.StringIO()):
        legacy = bx.backtest_smartbot_v2_multi_portfolio(assets, p, 3, legacy=True)
    assert len(legacy) == 5
    print("OK  6. wrapper multi_portfolio (rapide + legacy)")


def main():
    aligned = {f"A{i}": make_asset(2500, i) for i in range(4)}
    ragged = {f"R{i}": make_asset(2500, 10 + i, drop_frac=0.07 * i, start=f"2022-01-0{1 + i}") for i in range(4)}
    asset_sets = {"aligned": aligned, "ragged": ragged}

    t0 = time.perf_counter()
    test_market_mask()
    n = test_independence(asset_sets)
    n += test_single_asset()
    n += test_interactions(asset_sets)
    n += test_mono_fast()
    test_evaluate_and_format(aligned)
    test_wrapper(aligned)
    assert n > 2000, f"jeu de test trop pauvre ({n} deals)"
    print(f"\nTOUS LES TESTS OK ({n} deals, {time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()
