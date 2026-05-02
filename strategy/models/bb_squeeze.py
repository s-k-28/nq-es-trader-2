"""Bollinger Band Squeeze Breakout — enter on expansion after tight compression."""
from __future__ import annotations
import pandas as pd
from datetime import time as dt_time
from strategy.models.base import BaseModel, ModelRiskProfile, Signal
from config import Config


class BBSqueezeModel(BaseModel):
    name = 'bb_sqz'
    priority = 12

    def __init__(self, cfg: Config):
        rp = ModelRiskProfile(
            min_risk_ticks=8, max_risk_ticks=80, min_rr=2.0,
            be_trigger_rr=1.0, partial_rr=1.0, partial_pct=0.5,
            time_stop_minutes=40, max_daily=3,
            trail_pct=0.5,
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
        squeeze_active = False
        squeeze_start_idx = 0

        for idx in range(130, len(df)):
            bar = df.iloc[idx]
            dt = bar['datetime']
            d = dt.date()
            t = dt.time()

            if d != cur_date:
                cur_date = d
                used = 0
                squeeze_active = False

            if d not in daily_map or d not in regime_map:
                continue
            if used >= self.risk_profile.max_daily:
                continue
            if not ((dt_time(9, 45) <= t < dt_time(11, 0))
                    or (dt_time(14, 0) <= t < dt_time(15, 30))):
                continue

            bbw_pctile = bar.get('bbw_pctile')
            bb_upper = bar.get('bb_upper')
            bb_lower = bar.get('bb_lower')
            bb_mid = bar.get('bb_mid')
            if pd.isna(bbw_pctile) or pd.isna(bb_upper) or pd.isna(bb_mid):
                continue

            if bbw_pctile <= 10:
                if not squeeze_active:
                    squeeze_active = True
                    squeeze_start_idx = idx
                continue

            if not squeeze_active:
                continue

            bars_in_squeeze = idx - squeeze_start_idx
            if bars_in_squeeze < 5 or bars_in_squeeze > 60:
                squeeze_active = False
                continue

            vol_ok = (not pd.isna(vol_ma.iloc[idx])
                      and bar['volume'] > 1.3 * vol_ma.iloc[idx])

            regime = regime_map[d]

            if bar['close'] > bb_upper and vol_ok and regime != 'bear':
                entry = bar['close']
                stop = bb_mid
                risk = entry - stop
                target = entry + risk * 2.5
                reward = target - entry

                if risk > 0 and self._risk_ok(risk, reward):
                    signals.append(self._make_signal(
                        idx, bar, 'long', entry, stop, target,
                        'bb_squeeze_long'))
                    used += 1
                    squeeze_active = False

            elif bar['close'] < bb_lower and vol_ok and regime != 'bull':
                entry = bar['close']
                stop = bb_mid
                risk = stop - entry
                target = entry - risk * 2.5
                reward = entry - target

                if risk > 0 and self._risk_ok(risk, reward):
                    signals.append(self._make_signal(
                        idx, bar, 'short', entry, stop, target,
                        'bb_squeeze_short'))
                    used += 1
                    squeeze_active = False

        return signals
