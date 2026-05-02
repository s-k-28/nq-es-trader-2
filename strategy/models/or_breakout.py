"""Opening Range Breakout — tight-stop entry on confirmed break of 15-min OR."""
from __future__ import annotations
import pandas as pd
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class ORBreakoutModel(BaseModel):
    name = 'or_brk'
    priority = 10

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=16, max_risk_ticks=140, min_rr=2.0,
            be_trigger_rr=1.0, partial_rr=1.0, partial_pct=0.4,
            time_stop_minutes=60, max_daily=2,
            trail_pct=0.5,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        regime_map = context['regime_map']
        daily_map = context['daily_map']

        signals: list[Signal] = []
        cur_date = None
        used = 0
        long_taken = short_taken = False

        for idx in range(2, len(df)):
            bar = df.iloc[idx]
            dt = bar['datetime']
            d = dt.date()
            t = dt.time()

            if d != cur_date:
                cur_date = d
                used = 0
                long_taken = short_taken = False

            if d not in daily_map or d not in regime_map:
                continue
            if used >= self.risk_profile.max_daily:
                continue
            if not (dt_time(9, 45) <= t <= dt_time(11, 0)):
                continue

            or_high = bar.get('or_high')
            or_low = bar.get('or_low')
            or_range = bar.get('or_range')
            if pd.isna(or_high) or pd.isna(or_low) or pd.isna(or_range):
                continue

            regime = regime_map[d]
            prev1 = df.iloc[idx - 1]
            prev2 = df.iloc[idx - 2]

            # Long breakout: close above OR high, bullish bar
            if (not long_taken
                    and bar['close'] > or_high
                    and bar['close'] > bar['open']
                    and regime != 'bear'):

                entry = bar['close']
                stop = min(bar['low'], prev1['low']) - 2 * self.tick
                risk = entry - stop
                target = entry + risk * 2.5
                reward = target - entry

                if self._risk_ok(risk, reward):
                    signals.append(self._make_signal(
                        idx, bar, 'long', entry, stop, target,
                        'or_breakout_long'))
                    used += 1
                    long_taken = True

            # Short breakout: close below OR low, bearish bar
            elif (not short_taken
                    and bar['close'] < or_low
                    and bar['close'] < bar['open']
                    and regime != 'bull'):

                entry = bar['close']
                stop = max(bar['high'], prev1['high']) + 2 * self.tick
                risk = stop - entry
                target = entry - risk * 2.5
                reward = entry - target

                if self._risk_ok(risk, reward):
                    signals.append(self._make_signal(
                        idx, bar, 'short', entry, stop, target,
                        'or_breakout_short'))
                    used += 1
                    short_taken = True

        return signals
