"""VWAP Bounce model — enter on rejection off VWAP in trend direction."""
from __future__ import annotations
import pandas as pd
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class VWAPBounceModel(BaseModel):
    name = 'vwap_bounce'
    priority = 30

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=30, max_risk_ticks=200, min_rr=1.5,
            be_trigger_rr=1.0, partial_rr=1.5, partial_pct=0.5,
            time_stop_minutes=45, max_daily=3,
            trail_pct=0.0,
        )
        super().__init__(cfg, rp)

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 context: dict) -> list[Signal]:
        regime_map = context['regime_map']
        daily_map = context['daily_map']

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

            if d not in daily_map or d not in regime_map:
                continue
            if dt.weekday() == 0:
                continue

            prev_close = daily_map[d]['prev_close']
            bias = 1 if bar['close'] > prev_close else -1
            regime = regime_map[d]

            if (dt_time(10, 0) <= t < dt_time(14, 30)
                    and used < self.risk_profile.max_daily
                    and not pd.isna(bar.get('vwap'))):

                if bias == 1:
                    sig = self._vwap_long(df, idx, bar, bar['vwap'])
                    if sig:
                        signals.append(sig)
                        used += 1
                elif bias == -1 and regime == 'chop':
                    sig = self._vwap_short(df, idx, bar, bar['vwap'])
                    if sig:
                        signals.append(sig)
                        used += 1

        return signals

    def _vwap_long(self, df, idx, bar, vwap) -> Signal | None:
        if idx < 3:
            return None
        prev1 = df.iloc[idx - 1]
        prev2 = df.iloc[idx - 2]

        zone = 3.0 * self.tick
        touched = prev1['low'] <= vwap + zone
        rejected = bar['close'] > vwap and bar['close'] > bar['open']
        from_above = prev2['close'] > vwap

        if not (touched and rejected and from_above):
            return None

        entry = bar['close']
        rej_size = max(bar['close'] - bar['low'], 4 * self.tick)
        stop = vwap - rej_size
        risk = entry - stop

        recent_high = df.iloc[max(0, idx - 30):idx]['high'].max()
        target = max(entry + risk * 2.0, recent_high)
        reward = target - entry
        if not self._risk_ok(risk, reward):
            return None

        return self._make_signal(idx, bar, 'long', entry, stop, target,
                                 'vwap_bounce_long')

    def _vwap_short(self, df, idx, bar, vwap) -> Signal | None:
        if idx < 3:
            return None
        prev1 = df.iloc[idx - 1]
        prev2 = df.iloc[idx - 2]

        zone = 3.0 * self.tick
        touched = prev1['high'] >= vwap - zone
        rejected = bar['close'] < vwap and bar['close'] < bar['open']
        from_below = prev2['close'] < vwap

        if not (touched and rejected and from_below):
            return None

        entry = bar['close']
        rej_size = max(bar['high'] - bar['close'], 4 * self.tick)
        stop = vwap + rej_size
        risk = stop - entry

        recent_low = df.iloc[max(0, idx - 30):idx]['low'].min()
        target = min(entry - risk * 2.0, recent_low)
        reward = entry - target
        if not self._risk_ok(risk, reward):
            return None

        return self._make_signal(idx, bar, 'short', entry, stop, target,
                                 'vwap_bounce_short')
