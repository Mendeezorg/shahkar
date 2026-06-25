"""
core/indicators.py
Calculates all technical indicators from kline data.
"""
import pandas as pd
import numpy as np
from utils.logger import log


def klines_to_df(klines: list) -> pd.DataFrame:
    df = pd.DataFrame(klines, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_vol","trades","taker_base","taker_quote","ignore"
    ])
    for col in ["open","high","low","close","volume","quote_vol"]:
        df[col] = pd.to_numeric(df[col])
    df["open_time"]  = pd.to_datetime(df["open_time"],  unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    return df.reset_index(drop=True)


def calc_rsi(closes: pd.Series, period: int = 14) -> float:
    delta  = closes.diff()
    gain   = delta.clip(lower=0)
    loss   = -delta.clip(upper=0)
    avg_g  = gain.ewm(com=period-1, min_periods=period).mean()
    avg_l  = loss.ewm(com=period-1, min_periods=period).mean()
    rs     = avg_g / avg_l.replace(0, np.nan)
    rsi    = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def calc_macd(closes: pd.Series) -> dict:
    ema12  = closes.ewm(span=12, adjust=False).mean()
    ema26  = closes.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    cross_up = (macd.iloc[-1] > signal.iloc[-1] and
                macd.iloc[-2] <= signal.iloc[-2])
    return {
        "macd":     round(float(macd.iloc[-1]), 6),
        "signal":   round(float(signal.iloc[-1]), 6),
        "hist":     round(float(hist.iloc[-1]), 6),
        "cross_up": cross_up,
    }


def calc_volume_spike(volumes: pd.Series, window: int = 20) -> float:
    avg = volumes.iloc[-window-1:-1].mean()
    if avg == 0:
        return 0.0
    spike = volumes.iloc[-1] / avg
    return round(float(spike), 2)


def calc_momentum(closes: pd.Series, period: int = 10) -> float:
    if len(closes) < period + 1:
        return 0.0
    return round(float((closes.iloc[-1] / closes.iloc[-period] - 1) * 100), 2)


def calc_bollinger(closes: pd.Series, period: int = 20) -> dict:
    sma   = closes.rolling(period).mean()
    std   = closes.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    price = closes.iloc[-1]
    pct_b = float((price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1] + 1e-10))
    return {
        "upper":  round(float(upper.iloc[-1]), 6),
        "lower":  round(float(lower.iloc[-1]), 6),
        "middle": round(float(sma.iloc[-1]),   6),
        "pct_b":  round(pct_b, 3),
    }


def get_all_indicators(klines: list) -> dict:
    """Run all indicators on raw kline data. Returns dict of results."""
    try:
        df     = klines_to_df(klines)
        closes = df["close"]
        vols   = df["volume"]

        rsi     = calc_rsi(closes)
        macd    = calc_macd(closes)
        v_spike = calc_volume_spike(vols)
        mom     = calc_momentum(closes)
        bb      = calc_bollinger(closes)

        return {
            "rsi":          rsi,
            "macd":         macd,
            "volume_spike": v_spike,
            "momentum":     mom,
            "bollinger":    bb,
            "close":        float(closes.iloc[-1]),
            "ok":           True,
        }
    except Exception as e:
        log.error(f"Indicator calculation error: {e}")
        return {"ok": False}
