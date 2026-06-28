"""
SHAHKAR Backtest — Three Baselines, Rigorous Edition
======================================================
Tests whether the bot's scoring system has genuine edge by comparing:
  - "bot"            : full 7-indicator weighted score (replicates core/scorer.py)
  - "momentum_only"   : single indicator (3-candle momentum > 5%)
  - "random"          : random entries at matched frequency

Across 3 cost scenarios (30/50/80 bps round-trip) to bound execution-cost uncertainty,
since we don't have real order-book depth to model slippage precisely.

Fixes applied (per GLM review):
  1. No single dynamic slippage formula — uses 3 fixed cost scenarios instead.
  2. Pagination iterates forward from a fixed start time (no overlaps/gaps).
  3. No look-ahead bias — entry fills at NEXT candle's open, not the signal candle's close.
  4. 90-day window (not 14) for adequate sample size / regime coverage.
  5. Survivorship filter — drops pairs with any single 5m candle >15% range
     (listings/exploits the live bot's 90s scan interval could never catch anyway).

Run this in the Railway console (has Binance API access) or any environment
with network access to api.binance.com.
"""

import time
import random
import json
import requests
import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────
# CONFIG — must match live bot's config.py for an honest "bot" replica
# ──────────────────────────────────────────────────────────────────
INDICATOR_WEIGHTS = {
    "whale_dark_pool": 22,
    "volume_spike":    20,
    "macd":            15,
    "rsi":             12,
    "btc_trend":       13,
    "momentum":        10,
    "simple_pattern":  10,
}
MIN_SCORE        = 63
MIN_VOLUME_SPIKE = 2.0

DAYS_BACK              = 90
MAX_SINGLE_CANDLE_MOVE = 0.15   # survivorship filter threshold
TIMEOUT_CANDLES        = 72     # 6 hours at 5m candles
ATR_SL_MULT            = 1.5
ATR_TP_MULT            = 4.0

COST_SCENARIOS = {
    "Best_Case_30bps":   30,
    "Base_Case_50bps":   50,
    "Stress_Case_80bps": 80,
}

# NOTE: whale_signal and news_boost are NOT replicated here — they require
# live on-chain/news API calls that can't be reconstructed historically.
# The backtest's "bot" strategy uses whale_signal="neutral" (the score-neutral
# default) for every candidate, which is the most honest assumption we can
# make without fabricating historical whale/news data. This means the backtest
# is testing the 5 *technical* indicators (volume, RSI, MACD, BTC trend,
# momentum, pattern) at full strength — whale/news contribution is effectively
# zero-summed out, which is a conservative, defensible simplification.

BASE_URL = "https://api.binance.com/api/v3"


# ──────────────────────────────────────────────────────────────────
# STEP 1: Pick candidate pairs (top N by current volume, as a stand-in
# for "pairs the live bot would actually scan")
# ──────────────────────────────────────────────────────────────────
def get_candidate_pairs(top_n=60):
    print("Fetching current tickers to select candidate pairs...")
    resp = requests.get(f"{BASE_URL}/ticker/24hr", timeout=20)
    resp.raise_for_status()
    tickers = resp.json()
    usdt_pairs = [
        t for t in tickers
        if t["symbol"].endswith("USDT")
        and float(t.get("quoteVolume", 0)) >= 250_000
        and int(t.get("count", 0)) >= 500
        and not any(kw in t["symbol"] for kw in ["UP", "DOWN", "BULL", "BEAR"])
    ]
    usdt_pairs.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    symbols = [t["symbol"] for t in usdt_pairs[:top_n]]
    print(f"Selected {len(symbols)} candidate pairs.")
    return symbols


# ──────────────────────────────────────────────────────────────────
# STEP 2: Download klines — forward pagination, no overlap (Fix #2)
# ──────────────────────────────────────────────────────────────────
def download_klines_safe(symbol, days=DAYS_BACK, interval="5m"):
    all_klines = []
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)

    while start_ms < end_ms:
        params = {"symbol": symbol, "interval": interval, "startTime": start_ms, "limit": 1000}
        try:
            resp = requests.get(f"{BASE_URL}/klines", params=params, timeout=15)
            data = resp.json()
        except Exception as e:
            print(f"  {symbol}: fetch error {e}")
            break

        if not isinstance(data, list) or not data:
            break

        all_klines.extend(data)
        last_close_time = data[-1][6]
        if last_close_time <= start_ms:
            break
        start_ms = last_close_time + 1
        time.sleep(0.25)

    if not all_klines:
        return None

    df = pd.DataFrame(all_klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume", "quote_volume", "trades"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)
    return df


# ──────────────────────────────────────────────────────────────────
# STEP 3: Survivorship filter (Fix #5)
# ──────────────────────────────────────────────────────────────────
def passes_survivorship_filter(df):
    if df is None or len(df) < 50:
        return False
    moves = (df["high"] - df["low"]) / df["open"].replace(0, np.nan)
    max_move = moves.max()
    if pd.isna(max_move):
        return False
    return max_move < MAX_SINGLE_CANDLE_MOVE


# ──────────────────────────────────────────────────────────────────
# Indicator helpers — replicate core/scorer.py exactly
# ──────────────────────────────────────────────────────────────────
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    delta = np.diff(closes)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_g = np.mean(gain[-period:])
    avg_l = np.mean(loss[-period:])
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))


def calc_macd(closes):
    if len(closes) < 26:
        return {"cross_up": False, "hist": 0.0}

    def ema(data, span):
        alpha = 2 / (span + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(result[-1] * (1 - alpha) + v * alpha)
        return np.array(result)

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd = ema12 - ema26
    signal = ema(macd, 9)
    hist = macd - signal
    cross_up = bool(macd[-1] > signal[-1] and macd[-2] <= signal[-2])
    return {"cross_up": cross_up, "hist": float(hist[-1])}


def simple_pattern_strength(opens, highs, lows, closes, volumes):
    if len(closes) < 6:
        return 0.0
    hh = highs[-1] > highs[-2] > highs[-3]
    hl = lows[-1] > lows[-2] > lows[-3]
    higher_highs_lows = hh and hl

    prev_bearish = closes[-2] < opens[-2]
    curr_bullish = closes[-1] > opens[-1]
    curr_engulfs = opens[-1] <= closes[-2] and closes[-1] >= opens[-2]
    engulfing = prev_bearish and curr_bullish and curr_engulfs

    green_vol = all(
        volumes[-i] > volumes[-i - 1]
        for i in range(1, 4)
        if closes[-i] > opens[-i]
    )
    signals = sum([higher_highs_lows, engulfing, green_vol])
    if signals >= 3:
        return 1.0
    elif signals == 2:
        return 0.7
    elif signals == 1:
        return 0.4
    return 0.0


def atr_14(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    tr_values = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_values.append(tr)
    if len(tr_values) < period:
        return None
    atr_abs = np.mean(tr_values[-period:])
    return atr_abs / closes[-1] if closes[-1] > 0 else None


def offline_score(window_df, btc_trend="sideways"):
    """
    window_df: last ~100 rows of klines up to and including the signal candle.
    Replicates core/scorer.py with whale_signal='neutral' (see note above)
    and is_gem=False (gem detection needs cross-market BTC-divergence data
    we aren't reconstructing here — conservative simplification).
    """
    closes = window_df["close"].values
    opens = window_df["open"].values
    highs = window_df["high"].values
    lows = window_df["low"].values
    volumes = window_df["volume"].values

    if len(closes) < 30:
        return 0, {}

    total = 0.0
    breakdown = {}

    # 1. Volume spike
    avg_vol = np.mean(volumes[-21:-1]) if len(volumes) >= 21 else np.mean(volumes[:-1])
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
    if vol_ratio >= 4.0:
        pts = INDICATOR_WEIGHTS["volume_spike"]
    elif vol_ratio >= MIN_VOLUME_SPIKE:
        pts = INDICATOR_WEIGHTS["volume_spike"] * 0.7
    elif vol_ratio >= 1.5:
        pts = INDICATOR_WEIGHTS["volume_spike"] * 0.3
    else:
        pts = 0
    total += pts
    breakdown["volume_spike"] = vol_ratio

    # 2. RSI
    rsi = calc_rsi(closes)
    if 35 <= rsi <= 65:
        pts = INDICATOR_WEIGHTS["rsi"]
    elif 30 <= rsi <= 70:
        pts = INDICATOR_WEIGHTS["rsi"] * 0.5
    else:
        pts = 0
    total += pts
    breakdown["rsi"] = rsi

    # 3. MACD
    macd_r = calc_macd(closes)
    if macd_r["cross_up"]:
        pts = INDICATOR_WEIGHTS["macd"]
    elif macd_r["hist"] > 0:
        pts = INDICATOR_WEIGHTS["macd"] * 0.5
    else:
        pts = 0
    total += pts

    # 4. Whale — neutral default (see note above)
    total += INDICATOR_WEIGHTS["whale_dark_pool"] * 0.25

    # 5. BTC trend
    if btc_trend == "up":
        pts = INDICATOR_WEIGHTS["btc_trend"]
    elif btc_trend == "sideways":
        pts = INDICATOR_WEIGHTS["btc_trend"] * 0.5
    else:
        pts = 0
    total += pts

    # 6. Momentum (3-candle)
    if len(closes) >= 4:
        mom = (closes[-1] - closes[-4]) / closes[-4] * 100 if closes[-4] > 0 else 0
    else:
        mom = 0
    if mom > 2.0:
        pts = INDICATOR_WEIGHTS["momentum"]
    elif mom > 0.5:
        pts = INDICATOR_WEIGHTS["momentum"] * 0.5
    else:
        pts = 0
    total += pts
    breakdown["momentum"] = mom

    # 7. Pattern
    strength = simple_pattern_strength(opens, highs, lows, closes, volumes)
    pts = INDICATOR_WEIGHTS["simple_pattern"] * strength
    total += pts

    final = max(0, min(100, round(total)))
    return final, breakdown


def get_btc_trend_series(btc_df):
    """Precompute a simple BTC trend label per candle index using % change over last 12 candles (~1h)."""
    closes = btc_df["close"].values
    trend = np.array(["sideways"] * len(closes), dtype=object)
    for i in range(12, len(closes)):
        chg = (closes[i] - closes[i - 12]) / closes[i - 12] * 100 if closes[i - 12] > 0 else 0
        if chg > 0.5:
            trend[i] = "up"
        elif chg < -0.5:
            trend[i] = "down"
        else:
            trend[i] = "sideways"
    return trend


# ──────────────────────────────────────────────────────────────────
# NEW STRATEGY TRIGGERS (Round 2 — replacing dead multi-indicator scoring)
# ──────────────────────────────────────────────────────────────────
LARGE_CAP_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"}


def check_pullback_entry(i, closes, opens, volumes):
    """
    Strategy 1: Pullback Entry (long-only continuation)
    - >5% upward move over the last 12 candles (1h momentum)
    - current candle (i) is red (the pullback)
    - current candle's volume < 80% of avg volume of previous 3 candles
    """
    if i < 12 or closes[i - 12] <= 0:
        return False
    mom = (closes[i] - closes[i - 12]) / closes[i - 12]
    if mom <= 0.05:
        return False
    is_red = closes[i] < opens[i]
    if not is_red:
        return False
    if i < 3:
        return False
    avg_prev3_vol = np.mean(volumes[i - 3:i])
    if avg_prev3_vol <= 0:
        return False
    return volumes[i] < 0.8 * avg_prev3_vol


def compute_full_atr_series(highs, lows, closes, period=14):
    """
    Vectorized ATR(14) computed ONCE for an entire symbol's data,
    instead of recomputing a 14-candle window from scratch for every
    candle (which made check_squeeze_breakout O(n * 50 * 14) and took
    over an hour per symbol). This is O(n) total.
    Returns an array the same length as closes, with np.nan for the
    first `period` entries where ATR isn't yet defined.
    """
    n = len(closes)
    atr_pct = np.full(n, np.nan)
    if n < period + 1:
        return atr_pct

    prev_close = closes[:-1]
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - prev_close),
            np.abs(lows[1:] - prev_close),
        ),
    )
    # Simple moving average of true range over `period`, using pandas for a fast rolling window
    tr_series = pd.Series(tr)
    atr_abs = tr_series.rolling(window=period).mean().values  # aligned to tr (i.e. index 0 corresponds to candles[1])

    # atr_abs[k] is the ATR ending at candles[k+1]; convert to % of that candle's close
    closes_aligned = closes[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        atr_pct_aligned = np.where(closes_aligned > 0, atr_abs / closes_aligned, np.nan)

    atr_pct[1:] = atr_pct_aligned
    return atr_pct


def check_squeeze_breakout(i, opens, highs, lows, closes, volumes, atr_series):
    """
    Strategy 2: Volatility Squeeze Breakout (long-only)
    - ATR(14) at i-1 is the lowest of the last 50 candles (compression)
    - candle i body > 1.5x avg body of last 20 candles
    - candle i volume > 3x avg volume of last 20 candles
    - candle i must be green (bullish breakout direction)

    atr_series: precomputed via compute_full_atr_series() ONCE per symbol —
    this function now does O(1)-ish array slicing instead of recomputing ATR.
    """
    if i < 64:  # need 50 candles of ATR history + 14 for ATR itself
        return False

    window = atr_series[i - 50:i]  # ATR values for the 50 candles ending at i-1
    valid = window[~np.isnan(window)]
    if len(valid) < 30:
        return False
    atr_at_i_minus_1 = atr_series[i - 1]
    if np.isnan(atr_at_i_minus_1):
        return False
    if atr_at_i_minus_1 > np.nanmin(window):
        return False  # not the lowest -> no compression

    body_i = abs(closes[i] - opens[i])
    avg_body_20 = np.mean(np.abs(closes[i - 20:i] - opens[i - 20:i]))
    if avg_body_20 <= 0 or body_i <= 1.5 * avg_body_20:
        return False

    avg_vol_20 = np.mean(volumes[i - 20:i])
    if avg_vol_20 <= 0 or volumes[i] <= 3.0 * avg_vol_20:
        return False

    return closes[i] > opens[i]  # green breakout candle


def check_mean_reversion(i, closes, opens):
    """
    Strategy 3: Large-Cap Mean Reversion (long-only, large caps only — filtered at call site)
    - RSI(14) computed on data up to i-1 drops below 25 (extreme oversold)
    - candle i closes green (reversal confirmation)
    """
    if i < 15:
        return False
    rsi_prev = calc_rsi(closes[:i])  # up to but not including candle i
    if rsi_prev >= 25:
        return False
    return closes[i] > opens[i]


# ──────────────────────────────────────────────────────────────────
# STEP 4: Backtest loop — no look-ahead bias (Fix #3)
# ──────────────────────────────────────────────────────────────────
def calculate_pnl(entry_price, exit_price, cost_bps):
    cost_mult = cost_bps / 10000
    adj_entry = entry_price * (1 + cost_mult)
    adj_exit = exit_price * (1 - cost_mult)
    return (adj_exit - adj_entry) / adj_entry


def run_backtest(df, strategy, cost_bps, symbol="", random_trigger_rate=0.0015):
    trades = []
    position = None

    closes_all = df["close"].values
    opens_all = df["open"].values
    highs_all = df["high"].values
    lows_all = df["low"].values
    volumes_all = df["volume"].values

    # Strategy 3 only runs on large caps — skip entirely for everything else
    if strategy == "mean_reversion" and symbol not in LARGE_CAP_SYMBOLS:
        return []

    # Precompute the full ATR% series ONCE per symbol (huge speedup vs.
    # recomputing a 50x14 nested window inside check_squeeze_breakout per candle)
    atr_series = None
    if strategy == "squeeze_breakout":
        atr_series = compute_full_atr_series(highs_all, lows_all, closes_all)

    n = len(df)
    for i in range(300, n - 1):  # -1 ensures i+1 (realistic entry candle) exists
        if position is None:
            trigger = False

            if strategy == "pullback":
                trigger = check_pullback_entry(i, closes_all, opens_all, volumes_all)

            elif strategy == "squeeze_breakout":
                trigger = check_squeeze_breakout(i, opens_all, highs_all, lows_all, closes_all, volumes_all, atr_series)

            elif strategy == "mean_reversion":
                trigger = check_mean_reversion(i, closes_all, opens_all)

            elif strategy == "random":
                trigger = random.random() < random_trigger_rate

            if trigger:
                atr_pct = atr_14(
                    highs_all[max(0, i - 20):i + 1],
                    lows_all[max(0, i - 20):i + 1],
                    closes_all[max(0, i - 20):i + 1],
                )
                if atr_pct is None or atr_pct <= 0:
                    continue

                entry_price = opens_all[i + 1]  # FIX #3: next candle's open, not this candle's close
                position = {
                    "entry_price": entry_price,
                    "entry_idx": i + 1,
                    "sl": entry_price * (1 - atr_pct * ATR_SL_MULT),
                    "tp": entry_price * (1 + atr_pct * ATR_TP_MULT),
                    "atr_pct": atr_pct,
                }
        else:
            row_high = highs_all[i]
            row_low = lows_all[i]
            row_close = closes_all[i]
            exit_reason = None
            exit_price = None

            if row_low <= position["sl"]:
                exit_reason, exit_price = "SL", position["sl"]
            elif row_high >= position["tp"]:
                exit_reason, exit_price = "TP", position["tp"]
            elif (i - position["entry_idx"]) > TIMEOUT_CANDLES:
                exit_reason, exit_price = "TIMEOUT", row_close

            if exit_reason:
                pnl_pct = calculate_pnl(position["entry_price"], exit_price, cost_bps)
                trades.append({
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                    "atr_pct": position["atr_pct"],
                })
                position = None

    return trades


def profit_factor(trades):
    wins = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    losses = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0))
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def win_rate(trades):
    if not trades:
        return 0.0
    return sum(1 for t in trades if t["pnl_pct"] > 0) / len(trades)


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("SHAHKAR ROUND 2 BACKTEST — New Structural Strategies")
    print("=" * 70)
    print("Old multi-indicator scoring is retired (PF 0.206, tied with random).")
    print("Testing: Pullback Entry | Squeeze Breakout | Mean Reversion | Random")
    print("=" * 70)

    symbols = get_candidate_pairs(top_n=60)

    print(f"\nDownloading + filtering {len(symbols)} pairs (survivorship filter: max single-candle move < {MAX_SINGLE_CANDLE_MOVE:.0%})...")
    clean_data = {}
    for sym in symbols:
        df = download_klines_safe(sym, days=DAYS_BACK)
        if passes_survivorship_filter(df):
            clean_data[sym] = df
            print(f"  KEEP  {sym}  ({len(df)} candles)")
        else:
            reason = "insufficient data" if df is None or len(df) < 50 else "extreme candle detected"
            print(f"  DROP  {sym}  ({reason})")
        time.sleep(0.1)

    print(f"\n{len(clean_data)}/{len(symbols)} pairs survived filtering.")
    if len(clean_data) < 10:
        print("FATAL: too few pairs survived. Aborting.")
        return

    n_large_cap = sum(1 for s in clean_data if s in LARGE_CAP_SYMBOLS)
    print(f"Large-cap pairs available for Mean Reversion strategy: {n_large_cap}/{len(LARGE_CAP_SYMBOLS)}")

    print("\nRunning backtests across 4 strategies x 3 cost scenarios...")
    final_table = []

    strategies = ["pullback", "squeeze_breakout", "mean_reversion", "random"]

    for strategy in strategies:
        print(f"\n--- Strategy: {strategy} ---")

        for scenario_name, cost_bps in COST_SCENARIOS.items():
            all_trades = []
            for sym, df in clean_data.items():
                trades = run_backtest(df, strategy, cost_bps=cost_bps, symbol=sym)
                for t in trades:
                    t["symbol"] = sym
                all_trades.extend(trades)

            n_trades = len(all_trades)
            wr = win_rate(all_trades)
            pf = profit_factor(all_trades)

            final_table.append({
                "strategy": strategy,
                "scenario": scenario_name,
                "n_trades": n_trades,
                "win_rate_pct": round(wr * 100, 1),
                "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
            })
            print(f"  {scenario_name}: {n_trades} trades, win_rate={wr*100:.1f}%, PF={pf if pf==float('inf') else round(pf,3)}")

    print("\n" + "=" * 70)
    print("RESULTS — 4 strategies x 3 cost scenarios")
    print("=" * 70)

    df_results = pd.DataFrame(final_table)
    print(df_results.to_string(index=False))

    # FIX: save in local working directory, not /tmp (Windows-incompatible)
    out_path = "backtest_results.json"
    with open(out_path, "w") as f:
        json.dump(final_table, f, indent=2)
    print(f"\nSaved results to {out_path}")

    print("\n" + "=" * 70)
    print("VERDICT GUIDE:")
    print("  Any strategy's Best_Case PF < 1.0  -> dead on arrival, no edge even theoretically.")
    print("  Base_Case PF > 1.10 and Stress_Case PF > 1.00 -> genuine, robust edge. Worth pursuing.")
    print("  Base_Case PF > 1.10 but Stress_Case PF < 1.00 -> edge exists but fragile execution-dependent.")
    print("  Strategy doesn't beat Random -> no real edge, structurally indistinguishable from chance.")
    print("  Low n_trades (<30) on any strategy -> not enough data to trust the PF number yet.")
    print("=" * 70)


if __name__ == "__main__":
    main()
