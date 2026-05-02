"""Opening Range Breakout — trade breakout of first 15-min range with volume confirmation."""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class ORBModel(BaseModel):
    name = 'orb'
    priority = 10

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=40, max_risk_ticks=200, min_rr=1.5,
            be_trigger_rr=1.0, partial_rr=1.5, partial_pct=0.5,
            time_stop_minutes=60, max_daily=2,
            trail_pct=2.0,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        regime_map = context['regime_map']
        daily_map = context['daily_map']

        vol_ma = df['volume'].rolling(20, min_periods=5).mean()

        signals: list[Signal] = []
        cur_date = None
        used = 0
        triggered_long = False
        triggered_short = False

        for idx in range(30, len(df)):
            bar = df.iloc[idx]
            dt = bar['datetime']
            d = dt.date()
            t = dt.time()

            if d != cur_date:
                cur_date = d
                used = 0
                triggered_long = False
                triggered_short = False

            if d not in daily_map or d not in regime_map:
                continue
            if pd.isna(bar.get('or_high')) or pd.isna(bar.get('or_low')):
                continue
            if used >= self.risk_profile.max_daily:
                continue

            or_high = bar['or_high']
            or_low = bar['or_low']
            or_mid = bar['or_mid']
            or_range = bar['or_range']

            if or_range < 8 * self.tick:
                continue

            if not (dt_time(9, 46) <= t <= dt_time(11, 30)):
                continue

            has_volume = bar['volume'] > 1.3 * vol_ma.iloc[idx] if not pd.isna(vol_ma.iloc[idx]) else False

            regime = regime_map[d]
            prev_close = daily_map[d]['prev_close']
            bias = 1 if bar['close'] > prev_close else -1
            vwap = bar.get('vwap', None)

            if (not triggered_long
                    and bar['close'] > or_high
                    and bar['close'] > bar['open']
                    and has_volume):

                if regime == 'bear' and bias == -1:
                    continue

                entry = bar['close']
                stop = or_mid
                risk = entry - stop
                target = entry + risk * 2.0

                pdh = daily_map[d].get('pdh')
                if pdh and pdh > entry and pdh < target:
                    target = pdh
                    if target - entry < risk * 1.5:
                        target = entry + risk * 2.0

                reward = target - entry
                if self._risk_ok(risk, reward):
                    signals.append(self._make_signal(
                        idx, bar, 'long', entry, stop, target, 'orb_long'))
                    used += 1
                    triggered_long = True

            elif (not triggered_short
                    and bar['close'] < or_low
                    and bar['close'] < bar['open']
                    and has_volume):

                if regime == 'bull' and bias == 1:
                    continue

                entry = bar['close']
                stop = or_mid
                risk = stop - entry
                target = entry - risk * 2.0

                pdl = daily_map[d].get('pdl')
                if pdl and pdl < entry and pdl > target:
                    target = pdl
                    if entry - target < risk * 1.5:
                        target = entry - risk * 2.0

                reward = entry - target
                if self._risk_ok(risk, reward):
                    signals.append(self._make_signal(
                        idx, bar, 'short', entry, stop, target, 'orb_short'))
                    used += 1
                    triggered_short = True

        return signals
