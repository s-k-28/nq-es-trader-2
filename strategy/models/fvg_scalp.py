"""Fair Value Gap Scalp — enter on FVG retests during Silver Bullet windows.

ICT concept: displacement moves leave imbalances (FVGs) that act as
magnets for price. When price retests an unfilled FVG, it tends to
bounce from that zone with high probability.

Detects FVGs on 1-min data, then enters when price retests them.
Filtered by Silver Bullet time windows and regime alignment.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class FVGScalpModel(BaseModel):
    name = 'fvg'
    priority = 14

    FVG_MIN_TICKS = 6
    FVG_MAX_AGE = 25
    DISP_MIN_BODY_TICKS = 8

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=8, max_risk_ticks=60, min_rr=2.0,
            be_trigger_rr=1.0, partial_rr=1.0, partial_pct=0.5,
            time_stop_minutes=25, max_daily=3,
            trail_pct=0.0,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        regime_map = context['regime_map']
        daily_map = context['daily_map']

        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        opens = df['open'].values

        bull_fvgs = self._detect_bull_fvgs(highs, lows, closes, opens)
        bear_fvgs = self._detect_bear_fvgs(highs, lows, closes, opens)

        all_fvgs = bull_fvgs + bear_fvgs
        all_fvgs.sort(key=lambda x: x['idx'])

        signals: list[Signal] = []
        cur_date = None
        used = 0
        fvg_ptr = 0
        active_fvgs: list[dict] = []

        for idx in range(30, len(df)):
            bar = df.iloc[idx]
            dt = bar['datetime']
            d = dt.date()
            t = dt.time()

            if d != cur_date:
                cur_date = d
                used = 0
                active_fvgs = []
                fvg_ptr = max(fvg_ptr, 0)

            if d not in daily_map or d not in regime_map:
                continue

            while fvg_ptr < len(all_fvgs) and all_fvgs[fvg_ptr]['idx'] <= idx:
                fvg = all_fvgs[fvg_ptr]
                fvg_dt = df.iloc[fvg['idx']]['datetime']
                if fvg_dt.date() == d:
                    fvg_t = fvg_dt.time()
                    in_fvg_window = (dt_time(9, 35) <= fvg_t < dt_time(11, 0) or
                                     dt_time(13, 45) <= fvg_t < dt_time(15, 0))
                    if in_fvg_window:
                        active_fvgs.append(fvg)
                fvg_ptr += 1

            active_fvgs = [f for f in active_fvgs
                           if idx - f['idx'] <= self.FVG_MAX_AGE and not f.get('filled')]

            if used >= self.risk_profile.max_daily:
                continue

            in_window = (dt_time(9, 50) <= t < dt_time(11, 15) or
                         dt_time(14, 0) <= t < dt_time(15, 15))
            if not in_window:
                continue

            regime = regime_map[d]
            vwap = bar.get('vwap')
            if pd.isna(vwap):
                continue

            for fvg in active_fvgs:
                if fvg.get('filled'):
                    continue

                if fvg['dir'] == 'bull' and regime != 'bear':
                    sig = self._try_bull_fvg_entry(idx, bar, fvg, vwap, df)
                    if sig:
                        signals.append(sig)
                        used += 1
                        fvg['filled'] = True
                        break

                elif fvg['dir'] == 'bear' and regime != 'bull':
                    sig = self._try_bear_fvg_entry(idx, bar, fvg, vwap, df)
                    if sig:
                        signals.append(sig)
                        used += 1
                        fvg['filled'] = True
                        break

            for fvg in active_fvgs:
                if fvg['dir'] == 'bull' and bar['close'] < fvg['bottom']:
                    fvg['filled'] = True
                elif fvg['dir'] == 'bear' and bar['close'] > fvg['top']:
                    fvg['filled'] = True

        return signals

    def _try_bull_fvg_entry(self, idx, bar, fvg, vwap, df):
        if bar['low'] > fvg['top'] or bar['high'] < fvg['bottom']:
            return None

        if bar['low'] > fvg['mid']:
            return None

        if bar['close'] <= bar['open']:
            return None
        if bar['close'] < fvg['mid']:
            return None

        entry = bar['close']
        stop = fvg['bottom'] - 2 * self.tick
        risk = entry - stop

        recent_high = df.iloc[max(0, fvg['idx']-5):fvg['idx']]['high'].max()
        target = max(recent_high, entry + risk * 2.5)
        reward = target - entry

        if reward > 0 and self._risk_ok(risk, reward):
            return self._make_signal(idx, bar, 'long', entry, stop, target,
                                     'fvg_bull_retest')
        return None

    def _try_bear_fvg_entry(self, idx, bar, fvg, vwap, df):
        if bar['high'] < fvg['bottom'] or bar['low'] > fvg['top']:
            return None

        if bar['high'] < fvg['mid']:
            return None

        if bar['close'] >= bar['open']:
            return None
        if bar['close'] > fvg['mid']:
            return None

        entry = bar['close']
        stop = fvg['top'] + 2 * self.tick
        risk = stop - entry

        recent_low = df.iloc[max(0, fvg['idx']-5):fvg['idx']]['low'].min()
        target = min(recent_low, entry - risk * 2.5)
        reward = entry - target

        if reward > 0 and self._risk_ok(risk, reward):
            return self._make_signal(idx, bar, 'short', entry, stop, target,
                                     'fvg_bear_retest')
        return None

    def _detect_bull_fvgs(self, highs, lows, closes, opens):
        n = len(highs)
        if n < 3:
            return []

        gap = lows[2:] - highs[:-2]
        disp_body = closes[1:n-1] - opens[1:n-1]

        mask = ((gap >= self.FVG_MIN_TICKS * self.tick) &
                (disp_body >= self.DISP_MIN_BODY_TICKS * self.tick))

        indices = np.where(mask)[0]
        fvgs = []
        for i in indices:
            actual_idx = int(i + 2)
            top = float(lows[actual_idx])
            bottom = float(highs[i])
            fvgs.append({
                'idx': actual_idx, 'dir': 'bull',
                'top': top, 'bottom': bottom,
                'mid': (top + bottom) / 2,
                'filled': False,
            })
        return fvgs

    def _detect_bear_fvgs(self, highs, lows, closes, opens):
        n = len(highs)
        if n < 3:
            return []

        gap = lows[:-2] - highs[2:]
        disp_body = opens[1:n-1] - closes[1:n-1]

        mask = ((gap >= self.FVG_MIN_TICKS * self.tick) &
                (disp_body >= self.DISP_MIN_BODY_TICKS * self.tick))

        indices = np.where(mask)[0]
        fvgs = []
        for i in indices:
            actual_idx = int(i + 2)
            top = float(lows[i])
            bottom = float(highs[actual_idx])
            fvgs.append({
                'idx': actual_idx, 'dir': 'bear',
                'top': top, 'bottom': bottom,
                'mid': (top + bottom) / 2,
                'filled': False,
            })
        return fvgs
