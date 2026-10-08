"""Compare le backtester aux exports TradingView (bougies chart-data + liste de trades).

Les heures des trades sont celles du graphique (Europe/Paris). Les bougies sont en timestamp UNIX UTC.
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from backtester_exact import ParametresDCA_SmartBotV2
from backtester_fast import backtest_mono_fast

CHART_DIR = r"C:\Users\mathi\Documents\SP500backtest\chart-data"
TRADE_DIR = r"C:\Users\mathi\Documents\SP500backtest\trades"

PINE = ParametresDCA_SmartBotV2(
    dsc="RSI + BB",
    rsi_trigger_mode="Crossover",
    bb_trigger_mode="Level",
    mfi_trigger_mode="Level",
    rsi_length=2,
    dsc_rsi_threshold_low=3,
    bb_length=50,
    bb_mult=2.0,
    bb_threshold_low=0.0,
    pricedevbase="ATR",
    atr_length=14,
    atr_mult=5.0,
    atr_mult_step_scale=1.0,
    price_deviation=1.5,
    deviation_scale=1.0,
    max_safe_order=5,
    safe_order_volume_scale=1.5,
    base_order=5000.0,
    safe_order=7500.0,
    take_profit=2.0,
    tp_type="From Average Entry",
    initial_capital=100000.0,
    commission=0.001,
    close_last_trade=False,
    strategy_mode="dca",
    price_tick=0.01,
    check_cash=False,
)


def load_chart(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time").sort_index()
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
    df["Volume"] = 1.0
    return df[["Open", "High", "Low", "Close", "Volume"]]


def load_tv_deals(path: str):
    tv = pd.read_csv(path)
    tv["ts"] = (
        pd.to_datetime(tv["Date and time"], errors="coerce")
        .dt.tz_localize("Europe/Paris")
        .dt.tz_convert("UTC")
    )
    entries = tv[tv["Type"].astype(str).str.startswith("Entry")].copy()
    exits = tv[tv["Type"].astype(str).str.startswith("Exit")][["Trade number", "ts", "Price USD"]]
    exits = exits.rename(columns={"ts": "exit_ts", "Price USD": "exit_px"})
    entries = entries.merge(exits, on="Trade number", how="left")
    deals = []
    cur = None
    for _, row in entries.iterrows():
        sig = str(row["Signal"])
        if sig.startswith("BO"):
            if cur is not None:
                deals.append(cur)
            # Dernier deal encore ouvert dans le testeur : pas de date de sortie.
            if pd.isna(row["exit_ts"]):
                cur = None
                continue
            cur = {"entry": row["ts"], "exit": row["exit_ts"], "sos": [], "so_sig": []}
        elif cur is not None and sig.startswith("SO"):
            # Une seule strategy.entry peut apparaître en deux lignes au même horodatage
            # (même signal). Ce n'est pas un safety order de plus.
            if cur["sos"] and cur["so_sig"][-1] == sig and cur["sos"][-1] == row["ts"]:
                continue
            cur["sos"].append(row["ts"])
            cur["so_sig"].append(sig)
    if cur is not None:
        deals.append(cur)
    return deals


def compare_symbol(symbol_file: str):
    chart_path = os.path.join(CHART_DIR, symbol_file)
    trade_path = os.path.join(TRADE_DIR, symbol_file)
    if not (os.path.exists(chart_path) and os.path.exists(trade_path)):
        return None
    df = load_chart(chart_path)
    tv = load_tv_deals(trade_path)
    trades, _eq, stats = backtest_mono_fast(df, PINE, verbose=False)
    sim = []
    if not trades.empty:
        closed = trades[trades["reason"] != "OPEN"] if "reason" in trades.columns else trades
        for _, row in closed.iterrows():
            so = list(row["so_times"]) if isinstance(row["so_times"], list) else []
            sim.append({"entry": pd.Timestamp(row["entry_time"]), "exit": pd.Timestamp(row["exit_time"]), "sos": so})
    n = min(len(sim), len(tv))
    same_entry = same_exit = same_so = 0
    first = None
    for i in range(n):
        ok_e = sim[i]["entry"] == tv[i]["entry"]
        ok_x = sim[i]["exit"] == tv[i]["exit"]
        ok_s = [pd.Timestamp(t) for t in sim[i]["sos"]] == list(tv[i]["sos"])
        same_entry += int(ok_e)
        same_exit += int(ok_x)
        same_so += int(ok_s)
        if first is None and not (ok_e and ok_x and ok_s):
            first = (i + 1, sim[i], tv[i])
    return {
        "symbol": symbol_file,
        "tv": len(tv),
        "sim": len(sim),
        "aligned": n,
        "entry": same_entry,
        "exit": same_exit,
        "so": same_so,
        "pnl": stats.get("total_pnl"),
        "first": first,
    }


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else "NASDAQ_AAPL.csv"
    if only != "ALL":
        r = compare_symbol(only if only.endswith(".csv") else only + ".csv")
        print(r["symbol"], "tv", r["tv"], "sim", r["sim"], "entry", r["entry"], "exit", r["exit"], "so", r["so"])
        if r["first"]:
            i, sim, tv = r["first"]
            print("premier ecart deal", i)
            print(" sim", sim["entry"], sim["exit"], "so", sim["sos"])
            print(" tv ", tv["entry"], tv["exit"], "so", tv["sos"])
        return
    files = sorted(f for f in os.listdir(TRADE_DIR) if f.endswith(".csv") and f != "index.csv")
    rows = []
    missing = 0
    for i, name in enumerate(files, 1):
        r = compare_symbol(name)
        if r is None:
            missing += 1
            continue
        rows.append(r)
        if i % 50 == 0:
            print(f"... {i}/{len(files)}", flush=True)
    ok = [r for r in rows if r["tv"] == r["sim"] and r["entry"] == r["tv"] and r["exit"] == r["tv"] and r["so"] == r["tv"]]
    print(f"symboles compares {len(rows)} sans bougies {missing} identiques {len(ok)}")
    partial = sorted(rows, key=lambda r: (r["entry"] / r["tv"] if r["tv"] else 1))
    print("pires echantillons:")
    for r in partial[:15]:
        print(f"  {r['symbol']} tv={r['tv']} sim={r['sim']} entry={r['entry']} exit={r['exit']} so={r['so']}")


if __name__ == "__main__":
    main()
