"""Gap Fill — fade overnight gaps that are likely to fill during RTH."""
from __future__ import annotations
import pandas as pd
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class GapFillModel(BaseModel):
    name = 'gap'
    priority = 18

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=16, max_risk_ticks=120, min_rr=1.5,
            be_trigger_rr=1.0, partial_rr=1.0, partial_pct=0.5,
            time_stop_minutes=90, max_daily=1,
            trail_pct=0.0,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        daily_map = context['daily_map']
        regime_map = context['regime_map']

        signals: list[Signal] = []
        cur_date = None
        used = 0
        day_open = None
        prev_close = None
        first_5min_done = False
        first_5min_high = None
        first_5min_low = None

        for idx in range(1, len(df)):
            bar = df.iloc[idx]
            dt = bar['datetime']
            d = dt.date()
            t = dt.time()

            if d != cur_date:
                cur_date = d
                used = 0
                day_open = None
                first_5min_done = False
                first_5min_high = None
                first_5min_low = None
                if d in daily_map:
                    prev_close = daily_map[d].get('prev_close')

            if d not in daily_map or d not in regime_map:
                continue
            if used >= self.risk_profile.max_daily:
                continue
            if prev_close is None:
                continue

            if t == dt_time(9, 30) and day_open is None:
                day_open = bar['open']

            if day_open is None:
                continue

            if dt_time(9, 30) <= t < dt_time(9, 35):
                if first_5min_high is None:
                    first_5min_high = bar['high']
                    first_5min_low = bar['low']
                else:
                    first_5min_high = max(first_5min_high, bar['high'])
                    first_5min_low = min(first_5min_low, bar['low'])
                continue

            if t == dt_time(9, 35):
                first_5min_done = True

            if not first_5min_done:
                continue

            if not (dt_time(9, 35) <= t <= dt_time(10, 30)):
                continue

            gap = day_open - prev_close
            gap_pct = abs(gap) / prev_close if prev_close > 0 else 0
            gap_ticks = abs(gap) / self.tick

            if gap_pct < 0.0015 or gap_pct > 0.005:
                continue
            if gap_ticks < 20:
                continue

            regime = regime_map[d]

            if gap > 0 and regime != 'bull':
                if first_5min_high < day_open + abs(gap) * 0.3:
                    entry = bar['close']
                    stop = day_open + abs(gap) * 0.5 + 3 * self.tick
                    risk = stop - entry
                    target = prev_close
                    reward = entry - target

                    if risk > 0 and reward > 0 and self._risk_ok(risk, reward):
                        signals.append(self._make_signal(
                            idx, bar, 'short', entry, stop, target,
                            'gap_fill_short'))
                        used += 1

            elif gap < 0 and regime != 'bear':
                if first_5min_low > day_open - abs(gap) * 0.3:
                    entry = bar['close']
                    stop = day_open - abs(gap) * 0.5 - 3 * self.tick
                    risk = entry - stop
                    target = prev_close
                    reward = target - entry

                    if risk > 0 and reward > 0 and self._risk_ok(risk, reward):
                        signals.append(self._make_signal(
                            idx, bar, 'long', entry, stop, target,
                            'gap_fill_long'))
                        used += 1

        return signals
