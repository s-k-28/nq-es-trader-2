"""Opening Range Breakout — momentum entries on first break of 15m ORB."""
from __future__ import annotations
import pandas as pd
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class ORBBreakoutModel(BaseModel):
    name = 'orb'
    priority = 25

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=20, max_risk_ticks=100, min_rr=1.5,
            be_trigger_rr=1.0, partial_rr=1.0, partial_pct=0.5,
            time_stop_minutes=40, max_daily=2,
            trail_pct=0.3,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        regime_map = context['regime_map']
        daily_map = context['daily_map']

        signals: list[Signal] = []
        cur_date = None
        used = 0
        broken_long = False
        broken_short = False

        for idx in range(20, len(df)):
            bar = df.iloc[idx]
            dt = bar['datetime']
            d = dt.date()
            t = dt.time()

            if d != cur_date:
                cur_date = d
                used = 0
                broken_long = False
                broken_short = False

            if d not in daily_map or d not in regime_map:
                continue
            if used >= self.risk_profile.max_daily:
                continue
            if not (dt_time(9, 50) <= t < dt_time(11, 0)):
                continue

            or_high = bar.get('or_high')
            or_low = bar.get('or_low')
            or_range = bar.get('or_range')

            if pd.isna(or_high) or pd.isna(or_low) or pd.isna(or_range):
                continue

            or_ticks = or_range / self.tick
            if or_ticks < 60 or or_ticks > 400:
                continue

            regime = regime_map[d]
            prev1 = df.iloc[idx - 1]

            vol_ma = bar.get('volume', 0)
            vol_ok = bar['volume'] > 0

            if (not broken_long
                    and bar['close'] > or_high
                    and bar['close'] > bar['open']
                    and prev1['close'] <= or_high
                    and regime != 'bear'
                    and vol_ok):

                broken_long = True
                entry = bar['close']
                stop = min(bar['low'], or_high) - 2 * self.tick
                risk = entry - stop
                target = entry + risk * 2.0
                reward = target - entry

                if reward > 0 and self._risk_ok(risk, reward):
                    signals.append(self._make_signal(
                        idx, bar, 'long', entry, stop, target,
                        'orb_break_long'))
                    used += 1

            elif (not broken_short
                    and bar['close'] < or_low
                    and bar['close'] < bar['open']
                    and prev1['close'] >= or_low
                    and regime != 'bull'
                    and vol_ok):

                broken_short = True
                entry = bar['close']
                stop = max(bar['high'], or_low) + 2 * self.tick
                risk = stop - entry
                target = entry - risk * 2.0
                reward = entry - target

                if reward > 0 and self._risk_ok(risk, reward):
                    signals.append(self._make_signal(
                        idx, bar, 'short', entry, stop, target,
                        'orb_break_short'))
                    used += 1

        return signals
