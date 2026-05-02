"""Key Level Breakout — high-conviction breakout of PDH/PDL on trend days.

Only trades breakouts (no rejections — those tested negative). Requires:
- Strong body bar (10+ ticks) clearing the level
- Regime alignment (bull for longs, bear/chop for shorts)
- Price above VWAP for longs, below for shorts
- Prior consolidation near level (tested within last 10 bars but didn't break)
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class LevelBreakoutModel(BaseModel):
    name = 'level'
    priority = 15

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=20, max_risk_ticks=80, min_rr=2.0,
            be_trigger_rr=1.0, partial_rr=1.0, partial_pct=0.5,
            time_stop_minutes=40, max_daily=3,
            trail_pct=0.3,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        daily_map = context['daily_map']
        regime_map = context['regime_map']

        signals: list[Signal] = []
        cur_date = None
        used = 0

        for idx in range(30, len(df)):
            bar = df.iloc[idx]
            dt = bar['datetime']
            d = dt.date()
            t = dt.time()

            if d != cur_date:
                cur_date = d
                used = 0

            if d not in daily_map:
                continue
            if used >= self.risk_profile.max_daily:
                continue
            if not (dt_time(10, 0) <= t < dt_time(14, 30)):
                continue

            levels = daily_map[d]
            pdh = levels['pdh']
            pdl = levels['pdl']
            vwap = bar.get('vwap')
            regime = regime_map.get(d, 'chop')

            if pd.isna(vwap):
                continue

            prev1 = df.iloc[idx - 1]

            sig = self._try_pdh_break(idx, bar, prev1, df, pdh, pdl, vwap, regime)
            if not sig:
                sig = self._try_pdl_break(idx, bar, prev1, df, pdh, pdl, vwap, regime)

            if sig:
                signals.append(sig)
                used += 1

        return signals

    def _has_consolidation(self, df, idx, level, side, lookback=15):
        """Check that price has been near the level recently (building cause)."""
        zone = 8 * self.tick
        count = 0
        for i in range(max(0, idx - lookback), idx):
            b = df.iloc[i]
            if side == 'above':
                if b['high'] >= level - zone and b['close'] < level:
                    count += 1
            else:
                if b['low'] <= level + zone and b['close'] > level:
                    count += 1
        return count >= 3

    def _try_pdh_break(self, idx, bar, prev1, df, pdh, pdl, vwap, regime):
        if regime == 'bear':
            return None

        body = bar['close'] - bar['open']
        body_ticks = body / self.tick
        if body_ticks < 10:
            return None

        if not (prev1['close'] < pdh + 2 * self.tick and bar['close'] > pdh + 2 * self.tick):
            return None

        if bar['close'] <= vwap:
            return None

        if not self._has_consolidation(df, idx, pdh, 'above'):
            return None

        entry = bar['close']
        stop = max(min(bar['low'], prev1['low']), pdh - 4 * self.tick) - 2 * self.tick
        risk = entry - stop

        day_range = pdh - pdl
        target = entry + max(risk * 2.5, day_range * 0.5)
        reward = target - entry

        if self._risk_ok(risk, reward):
            return self._make_signal(idx, bar, 'long', entry, stop, target,
                                     'level_pdh_breakout')
        return None

    def _try_pdl_break(self, idx, bar, prev1, df, pdh, pdl, vwap, regime):
        if regime == 'bull':
            return None

        body = bar['open'] - bar['close']
        body_ticks = body / self.tick
        if body_ticks < 10:
            return None

        if not (prev1['close'] > pdl - 2 * self.tick and bar['close'] < pdl - 2 * self.tick):
            return None

        if bar['close'] >= vwap:
            return None

        if not self._has_consolidation(df, idx, pdl, 'below'):
            return None

        entry = bar['close']
        stop = min(max(bar['high'], prev1['high']), pdl + 4 * self.tick) + 2 * self.tick
        risk = stop - entry

        day_range = pdh - pdl
        target = entry - max(risk * 2.5, day_range * 0.5)
        reward = entry - target

        if self._risk_ok(risk, reward):
            return self._make_signal(idx, bar, 'short', entry, stop, target,
                                     'level_pdl_breakout')
        return None
