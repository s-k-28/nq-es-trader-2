"""Tempo Trades IFVG Model — sweep Asia/London levels, enter on IFVG retest.

Sessions (ET = CST + 1):
  Asia:    8:00 PM - 12:00 AM ET  (7 PM - 11 PM CST)
  London:  2:00 AM -  5:00 AM ET  (1 AM -  4 AM CST)
  NY:      9:30 AM - 11:00 AM ET  (8:30 AM - 10 AM CST)

Setup:
  1. Mark Asia H/L and London H/L
  2. After a session ends, if price takes a level before NY open, it is invalidated
  3. At NY open, wait for price to sweep one of the remaining levels
  4. Sweep must close back inside the level (confirms stop hunt, not breakdown)
  5. After sweep, look for FVGs created by the sweep move and new ones forming
  6. FVG must be singular (no other FVGs nearby). If not singular,
     use the highest FVG for longs or lowest for shorts
  7. Candle must close above/below the FVG to confirm it as an IFVG
  8. Enter at the IFVG zone on retest
  9. Stop at the far side of the IFVG
  10. TP1: 1.5R (half off), TP2: 2.0R (remainder)
  11. Trading ends at 11:00 AM ET
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import time as dt_time, timedelta
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class TempoIFVGModel(BaseModel):
    name = 'tempo'
    priority = 5

    FVG_MIN_TICKS = 6
    NEARBY_TICKS = 30

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=6, max_risk_ticks=80, min_rr=1.5,
            be_trigger_rr=1.5, partial_rr=1.5, partial_pct=0.5,
            time_stop_minutes=60, max_daily=2,
            trail_pct=0.0,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        session_levels = self._compute_session_levels(df)

        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        opens = df['open'].values
        n = len(highs)

        bear_fvg_mask = np.zeros(n, dtype=bool)
        if n > 2:
            gap = lows[:-2] - highs[2:]
            bear_fvg_mask[2:] = gap >= self.FVG_MIN_TICKS * self.tick

        bull_fvg_mask = np.zeros(n, dtype=bool)
        if n > 2:
            gap = lows[2:] - highs[:-2]
            bull_fvg_mask[2:] = gap >= self.FVG_MIN_TICKS * self.tick

        signals: list[Signal] = []
        cur_td = None
        used = 0

        sweep = None
        candidates: list[dict] = []
        target_fvg = None
        ifvg = None

        for idx in range(3, n):
            dt = df.iloc[idx]['datetime']
            t = dt.time()
            td = self._trading_date(dt)

            if td != cur_td:
                cur_td = td
                used = 0
                sweep = None
                candidates = []
                target_fvg = None
                ifvg = None

            if not (dt_time(9, 30) <= t < dt_time(11, 0)):
                continue
            if used >= self.risk_profile.max_daily:
                continue

            levs = session_levels.get(td)
            if levs is None:
                continue

            c = closes[idx]
            h = highs[idx]
            lo = lows[idx]
            o = opens[idx]

            if sweep is None:
                sweep = self._detect_sweep(lo, h, c, levs)
                if sweep is not None:
                    sweep['idx'] = idx
                    fvg_dir = 'bear' if sweep['type'] == 'bull' else 'bull'
                    mask = bear_fvg_mask if fvg_dir == 'bear' else bull_fvg_mask
                    candidates = self._collect_fvgs(
                        mask, highs, lows, fvg_dir,
                        max(3, idx - 5), idx + 1)
                    target_fvg = self._select_target(candidates, sweep['type'])
                continue

            if idx - sweep['idx'] > 20:
                sweep = None
                candidates = []
                target_fvg = None
                ifvg = None
                continue

            fvg_dir = 'bear' if sweep['type'] == 'bull' else 'bull'
            mask = bear_fvg_mask if fvg_dir == 'bear' else bull_fvg_mask
            if mask[idx]:
                new_fvg = self._make_fvg(highs, lows, idx, fvg_dir)
                candidates.append(new_fvg)
                target_fvg = self._select_target(candidates, sweep['type'])

            if target_fvg is not None and ifvg is None:
                if sweep['type'] == 'bear' and c < target_fvg['bottom']:
                    if not self._has_nearby_fvgs(candidates, target_fvg):
                        ifvg = dict(target_fvg)
                        ifvg['inv_idx'] = idx
                    else:
                        target_fvg = self._select_target(candidates, sweep['type'])
                        if target_fvg and c < target_fvg['bottom']:
                            ifvg = dict(target_fvg)
                            ifvg['inv_idx'] = idx

            if ifvg is not None:
                if idx - ifvg['inv_idx'] > 15:
                    sweep = None
                    candidates = []
                    target_fvg = None
                    ifvg = None
                    continue

                sig = self._check_entry(idx, df.iloc[idx], c, o, h, lo, ifvg, sweep)
                if sig:
                    signals.append(sig)
                    used += 1
                    sweep = None
                    candidates = []
                    target_fvg = None
                    ifvg = None

        return signals

    def _detect_sweep(self, bar_low, bar_high, bar_close, levs):
        valid_highs = []
        if levs.get('asia_high') is not None:
            valid_highs.append(('asia', levs['asia_high']))
        if levs.get('london_high') is not None:
            valid_highs.append(('london', levs['london_high']))

        for src, level in valid_highs:
            if bar_high > level and bar_close < level:
                return {'type': 'bear', 'level': level, 'src': src}

        return None

    def _collect_fvgs(self, mask, highs, lows, fvg_dir, start, end):
        fvgs = []
        for j in range(max(2, start), min(len(mask), end)):
            if mask[j]:
                fvgs.append(self._make_fvg(highs, lows, j, fvg_dir))
        return fvgs

    def _make_fvg(self, highs, lows, idx, fvg_dir):
        if fvg_dir == 'bear':
            return {'idx': idx, 'dir': 'bear',
                    'top': float(lows[idx - 2]), 'bottom': float(highs[idx])}
        else:
            return {'idx': idx, 'dir': 'bull',
                    'top': float(lows[idx]), 'bottom': float(highs[idx - 2])}

    def _select_target(self, fvgs, sweep_type):
        if not fvgs:
            return None
        return min(fvgs, key=lambda f: f['bottom'])

    def _has_nearby_fvgs(self, candidates, target):
        count = 0
        for f in candidates:
            if f['idx'] == target['idx']:
                continue
            dist = abs(f['top'] - target['top'])
            if dist < self.NEARBY_TICKS * self.tick:
                count += 1
        return count > 0

    def _check_entry(self, idx, bar, c, o, h, lo, ifvg, sweep):
        touched = h >= ifvg['bottom']
        held = c < ifvg['top']
        bearish = c < o
        if touched and held and bearish:
            entry = c
            stop = ifvg['top']
            risk = stop - entry
            if risk <= 0:
                return None
            target = entry - 2.0 * risk
            reward = entry - target
            if self._risk_ok(risk, reward):
                return self._make_signal(idx, bar, 'short', entry, stop,
                                         target, 'tempo_ifvg_short')
        return None

    @staticmethod
    def _trading_date(dt):
        if dt.time() >= dt_time(18, 0):
            return (dt + timedelta(days=1)).date()
        return dt.date()

    def _compute_session_levels(self, df):
        levels: dict = {}

        for idx in range(len(df)):
            bar = df.iloc[idx]
            dt = bar['datetime']
            t = dt.time()
            td = self._trading_date(dt)

            if td not in levels:
                levels[td] = {}
            lev = levels[td]

            h, lo = bar['high'], bar['low']

            if t >= dt_time(20, 0) or t == dt_time(0, 0):
                if 'asia_high' not in lev or h > lev['asia_high']:
                    lev['asia_high'] = h
                if 'asia_low' not in lev or lo < lev['asia_low']:
                    lev['asia_low'] = lo

            elif dt_time(2, 0) <= t < dt_time(5, 0):
                if 'london_high' not in lev or h > lev['london_high']:
                    lev['london_high'] = h
                if 'london_low' not in lev or lo < lev['london_low']:
                    lev['london_low'] = lo

            elif dt_time(0, 1) <= t < dt_time(9, 30):
                if 'asia_high' in lev and h > lev['asia_high']:
                    del lev['asia_high']
                if 'asia_low' in lev and lo < lev['asia_low']:
                    del lev['asia_low']
                if t >= dt_time(5, 0):
                    if 'london_high' in lev and h > lev['london_high']:
                        del lev['london_high']
                    if 'london_low' in lev and lo < lev['london_low']:
                        del lev['london_low']

        return levels
