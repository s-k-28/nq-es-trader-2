"""
Core detection: sweep → market-structure-shift → FVG → trade setup.

Solves the five problems identified in theoretical analysis:
  P1 (fill-rate): entry is the FVG 50% level, but the backtest only counts
      trades where price actually retraces there.  Unfilled setups are logged
      separately so you see true opportunity cost.
  P3 (sweep ≠ reversal): we require a full MSS (break of prior swing) with
      displacement quality, not just one green candle.
  P4 (discretion): every filter is a number — body ratio, tick thresholds,
      candle counts.  No adjectives.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass
from config import Config


# ── data classes ──────────────────────────────────────────────────────

@dataclass
class Sweep:
    idx: int
    ts: pd.Timestamp
    level_name: str
    level_price: float
    sweep_price: float
    direction: str            # 'bearish_sweep' (took lows) | 'bullish_sweep' (took highs)


@dataclass
class MSS:
    idx: int
    ts: pd.Timestamp
    direction: str            # 'bullish' | 'bearish'
    disp_open: float
    disp_close: float
    disp_high: float
    disp_low: float
    swing_break: float        # the swing level that got broken


@dataclass
class FVG:
    idx: int
    ts: pd.Timestamp
    direction: str            # 'bullish' | 'bearish'
    top: float
    bottom: float
    entry: float
    size_ticks: float


@dataclass
class TradeSetup:
    ts: pd.Timestamp
    direction: str            # 'long' | 'short'
    entry: float
    stop: float
    target: float
    risk_ticks: float
    reward_ticks: float
    rr: float
    sweep: Sweep
    mss: MSS
    fvg: FVG


# ── detector ──────────────────────────────────────────────────────────

class SignalDetector:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.tick = cfg.instrument.tick_size

    # ── sweep ─────────────────────────────────────────────────────────

    def detect_sweep(self, bars: pd.DataFrame, levels: dict[str, float],
                     idx: int) -> Sweep | None:
        if idx < 1:
            return None
        sweep_min = self.cfg.strategy.sweep_min_ticks * self.tick
        lookback = self.cfg.strategy.sweep_max_candles
        bar = bars.iloc[idx]

        for name, lvl in levels.items():
            # bearish sweep — recent candle wicked below key low, current closes above
            if 'low' in name or name == 'pdl':
                # check current bar (single-candle sweep)
                if bar['low'] <= lvl - sweep_min and bar['close'] > lvl:
                    return Sweep(idx, bar['datetime'], name, lvl,
                                 bar['low'], 'bearish_sweep')
                # multi-candle: a recent bar wicked below, current bar closed back above
                if bar['close'] > lvl:
                    for j in range(1, lookback + 1):
                        if idx - j < 0:
                            break
                        prev = bars.iloc[idx - j]
                        if prev['low'] <= lvl - sweep_min:
                            sweep_low = min(bars.iloc[idx - j:idx + 1]['low'])
                            return Sweep(idx, bar['datetime'], name, lvl,
                                         sweep_low, 'bearish_sweep')

            # bullish sweep — recent candle wicked above key high, current closes below
            if 'high' in name or name == 'pdh':
                if bar['high'] >= lvl + sweep_min and bar['close'] < lvl:
                    return Sweep(idx, bar['datetime'], name, lvl,
                                 bar['high'], 'bullish_sweep')
                if bar['close'] < lvl:
                    for j in range(1, lookback + 1):
                        if idx - j < 0:
                            break
                        prev = bars.iloc[idx - j]
                        if prev['high'] >= lvl + sweep_min:
                            sweep_high = max(bars.iloc[idx - j:idx + 1]['high'])
                            return Sweep(idx, bar['datetime'], name, lvl,
                                         sweep_high, 'bullish_sweep')
        return None

    # ── market structure shift ────────────────────────────────────────

    def detect_mss(self, bars: pd.DataFrame, sweep: Sweep,
                   search_start: int, search_end: int) -> MSS | None:
        if sweep.direction == 'bearish_sweep':
            return self._bullish_mss(bars, sweep, search_start, search_end)
        return self._bearish_mss(bars, sweep, search_start, search_end)

    def _bullish_mss(self, bars, sweep, start, end) -> MSS | None:
        lb = self.cfg.strategy.swing_lookback
        min_body = self.cfg.strategy.mss_body_ratio
        min_disp = self.cfg.strategy.mss_min_ticks * self.tick

        # find most recent swing high before sweep
        pre = bars.iloc[max(0, sweep.idx - 60): sweep.idx]
        if len(pre) < lb:
            return None

        swing_high = None
        for i in range(len(pre) - 1, lb - 1, -1):
            h = pre.iloc[i]['high']
            lo_idx = max(0, i - lb)
            hi_idx = min(len(pre), i + lb + 1)
            if h >= pre.iloc[lo_idx:hi_idx]['high'].max():
                swing_high = h
                break

        if swing_high is None:
            return None

        end = min(end, len(bars))
        for i in range(start, end):
            b = bars.iloc[i]
            body = abs(b['close'] - b['open'])
            rng = b['high'] - b['low']
            if rng == 0:
                continue
            if (b['close'] > b['open']
                    and b['close'] > swing_high
                    and body / rng >= min_body
                    and body >= min_disp):
                return MSS(i, b['datetime'], 'bullish',
                           b['open'], b['close'], b['high'], b['low'],
                           swing_high)
        return None

    def _bearish_mss(self, bars, sweep, start, end) -> MSS | None:
        lb = self.cfg.strategy.swing_lookback
        min_body = self.cfg.strategy.mss_body_ratio
        min_disp = self.cfg.strategy.mss_min_ticks * self.tick

        pre = bars.iloc[max(0, sweep.idx - 60): sweep.idx]
        if len(pre) < lb:
            return None

        swing_low = None
        for i in range(len(pre) - 1, lb - 1, -1):
            lo = pre.iloc[i]['low']
            lo_idx = max(0, i - lb)
            hi_idx = min(len(pre), i + lb + 1)
            if lo <= pre.iloc[lo_idx:hi_idx]['low'].min():
                swing_low = lo
                break

        if swing_low is None:
            return None

        end = min(end, len(bars))
        for i in range(start, end):
            b = bars.iloc[i]
            body = abs(b['close'] - b['open'])
            rng = b['high'] - b['low']
            if rng == 0:
                continue
            if (b['close'] < b['open']
                    and b['close'] < swing_low
                    and body / rng >= min_body
                    and body >= min_disp):
                return MSS(i, b['datetime'], 'bearish',
                           b['open'], b['close'], b['high'], b['low'],
                           swing_low)
        return None

    # ── FVG ───────────────────────────────────────────────────────────

    def detect_fvg(self, bars: pd.DataFrame, mss: MSS) -> FVG | None:
        start = max(mss.idx, 2)
        end = min(mss.idx + 5, len(bars))
        pct = self.cfg.strategy.fvg_entry_pct
        min_gap = self.cfg.strategy.fvg_min_ticks * self.tick

        for i in range(start, end):
            c1 = bars.iloc[i - 2]
            c3 = bars.iloc[i]

            if mss.direction == 'bullish' and c3['low'] > c1['high']:
                gap = c3['low'] - c1['high']
                if gap >= min_gap:
                    entry = c1['high'] + gap * pct
                    return FVG(i, c3['datetime'], 'bullish',
                               c3['low'], c1['high'],
                               self._rt(entry), gap / self.tick)

            if mss.direction == 'bearish' and c3['high'] < c1['low']:
                gap = c1['low'] - c3['high']
                if gap >= min_gap:
                    entry = c1['low'] - gap * pct
                    return FVG(i, c3['datetime'], 'bearish',
                               c1['low'], c3['high'],
                               self._rt(entry), gap / self.tick)
        return None

    # ── full setup ────────────────────────────────────────────────────

    def build_setup(self, sweep: Sweep, mss: MSS, fvg: FVG) -> TradeSetup | None:
        buf = self.cfg.risk.stop_buffer_ticks * self.tick
        rr = self.cfg.risk.target_rr

        if fvg.direction == 'bullish':
            entry = fvg.entry
            stop = sweep.sweep_price - buf
            risk = entry - stop
            if risk <= 0:
                return None
            target = entry + risk * rr
        else:
            entry = fvg.entry
            stop = sweep.sweep_price + buf
            risk = stop - entry
            if risk <= 0:
                return None
            target = entry - risk * rr

        risk_ticks = risk / self.tick
        if risk_ticks > self.cfg.risk.max_risk_ticks:
            return None

        return TradeSetup(
            ts=fvg.ts,
            direction='long' if fvg.direction == 'bullish' else 'short',
            entry=self._rt(entry),
            stop=self._rt(stop),
            target=self._rt(target),
            risk_ticks=risk_ticks,
            reward_ticks=risk * rr / self.tick,
            rr=rr,
            sweep=sweep, mss=mss, fvg=fvg,
        )

    def _rt(self, price: float) -> float:
        return round(price / self.tick) * self.tick
