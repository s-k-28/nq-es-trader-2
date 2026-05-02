"""Initial Balance Extension — Market Profile concept for trend day moves.

The Initial Balance (IB) is the first 60 minutes of RTH (9:30-10:30).
When price breaks out of the IB with conviction, it often extends 1-2x the IB range.

Narrow IB days are the highest probability for extension moves.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class IBExtensionModel(BaseModel):
    name = 'IB'
    priority = 12

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=25, max_risk_ticks=100, min_rr=1.8,
            be_trigger_rr=1.0, partial_rr=1.2, partial_pct=0.5,
            time_stop_minutes=60, max_daily=2,
            trail_pct=0.4,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        regime_map = context['regime_map']
        daily_map = context['daily_map']

        ib_levels = self._compute_ib(df)

        avg_ib_range = np.mean([v['range'] for v in ib_levels.values()]) if ib_levels else 0

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

            if d not in ib_levels or d not in daily_map:
                continue
            if used >= self.risk_profile.max_daily:
                continue
            if not (dt_time(10, 32) <= t < dt_time(14, 0)):
                continue

            ib = ib_levels[d]
            ib_high = ib['high']
            ib_low = ib['low']
            ib_range = ib['range']
            ib_mid = (ib_high + ib_low) / 2

            if ib_range < 10 * self.tick:
                continue

            vwap = bar.get('vwap')
            regime = regime_map.get(d, 'chop')
            if pd.isna(vwap):
                continue

            prev1 = df.iloc[idx - 1]

            is_narrow = ib_range < avg_ib_range * 0.8

            if (prev1['close'] <= ib_high
                    and bar['close'] > ib_high + 2 * self.tick
                    and bar['close'] > bar['open']
                    and (bar['close'] - bar['open']) / self.tick >= 6
                    and bar['close'] > vwap
                    and regime != 'bear'):

                entry = bar['close']
                stop = max(ib_mid, bar['low'] - 2 * self.tick)
                risk = entry - stop

                extension = 1.5 if is_narrow else 1.0
                target = ib_high + ib_range * extension
                pdh = daily_map[d]['pdh']
                if pdh > entry:
                    target = max(target, pdh)
                reward = target - entry

                if self._risk_ok(risk, reward):
                    tag = 'ib_ext_long_narrow' if is_narrow else 'ib_ext_long'
                    signals.append(self._make_signal(
                        idx, bar, 'long', entry, stop, target, tag))
                    used += 1

            elif (prev1['close'] >= ib_low
                    and bar['close'] < ib_low - 2 * self.tick
                    and bar['close'] < bar['open']
                    and (bar['open'] - bar['close']) / self.tick >= 6
                    and bar['close'] < vwap
                    and regime != 'bull'):

                entry = bar['close']
                stop = min(ib_mid, bar['high'] + 2 * self.tick)
                risk = stop - entry

                extension = 1.5 if is_narrow else 1.0
                target = ib_low - ib_range * extension
                pdl = daily_map[d]['pdl']
                if pdl < entry:
                    target = min(target, pdl)
                reward = entry - target

                if self._risk_ok(risk, reward):
                    tag = 'ib_ext_short_narrow' if is_narrow else 'ib_ext_short'
                    signals.append(self._make_signal(
                        idx, bar, 'short', entry, stop, target, tag))
                    used += 1

        return signals

    def _compute_ib(self, df: pd.DataFrame) -> dict:
        ib_start = dt_time(9, 30)
        ib_end = dt_time(10, 30)

        ib_bars = df[(df['datetime'].dt.time >= ib_start) &
                     (df['datetime'].dt.time < ib_end)].copy()
        ib_bars['date'] = ib_bars['datetime'].dt.date

        result = {}
        for d, grp in ib_bars.groupby('date'):
            h = grp['high'].max()
            l = grp['low'].min()
            result[d] = {'high': h, 'low': l, 'range': h - l}
        return result
