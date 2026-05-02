from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import time as dt_time
from config import Config


class BiasEngine:
    """3-signal vote: overnight delta, weekly-open position, prior-day candle body."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cache: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    def precompute(self, daily: pd.DataFrame, df_1m: pd.DataFrame):
        d = daily.copy()

        # signal 1 — EMA (fallback when delta unavailable)
        d['ema'] = d['close'].ewm(span=self.cfg.strategy.ema_period, adjust=False).mean()
        d['above_ema'] = d['close'] > d['ema']

        # signal 2 — prior day closed above its midpoint
        d['mid'] = (d['high'] + d['low']) / 2
        d['above_mid'] = d['close'] > d['mid']

        # signal 3 — above weekly open
        d['week'] = d['date'].dt.isocalendar().week.astype(int)
        d['year'] = d['date'].dt.year
        wo = d.groupby(['year', 'week'])['open'].first().reset_index()
        wo.columns = ['year', 'week', 'weekly_open']
        d = d.merge(wo, on=['year', 'week'], how='left')
        d['above_wo'] = d['close'] > d['weekly_open']

        # signal 4 — overnight cumulative delta (replaces EMA when available)
        on_delta = self._overnight_delta(df_1m)
        d = d.merge(on_delta, on='date', how='left')
        d['delta_pos'] = d['on_cum_delta'].fillna(0) > 0

        # prefer delta over EMA
        has_delta = d['on_cum_delta'].notna()
        s1 = np.where(has_delta, d['delta_pos'], d['above_ema']).astype(int)

        d['bull_votes'] = s1 + d['above_wo'].astype(int) + d['above_mid'].astype(int)
        min_agree = self.cfg.strategy.bias_min_agreement
        d['bias'] = np.where(
            d['bull_votes'] >= min_agree, 1,
            np.where(d['bull_votes'] <= 3 - min_agree, -1, 0),
        )

        self._cache = d[['date', 'bias', 'ema', 'weekly_open', 'high', 'low']].copy()
        return self._cache

    # ------------------------------------------------------------------
    def get_bias(self, date) -> int:
        if self._cache is None:
            raise RuntimeError("call precompute first")
        date = pd.Timestamp(date).normalize()
        prev = self._cache[self._cache['date'] < date]
        if prev.empty:
            return 0
        return int(prev.iloc[-1]['bias'])

    def get_daily_levels(self, date) -> dict:
        if self._cache is None:
            raise RuntimeError("call precompute first")
        date = pd.Timestamp(date).normalize()
        prev = self._cache[self._cache['date'] < date]
        if prev.empty:
            return {}
        row = prev.iloc[-1]
        return {'pdh': row['high'], 'pdl': row['low'], 'weekly_open': row['weekly_open']}

    # ------------------------------------------------------------------
    def _overnight_delta(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        df = df_1m.copy()
        df['t'] = df['datetime'].dt.time
        on = df[(df['t'] >= dt_time(18, 0)) | (df['t'] < dt_time(9, 30))].copy()

        rng = (on['high'] - on['low']).replace(0, np.nan)
        on['delta'] = on['volume'] * (2 * (on['close'] - on['low']) / rng - 1)
        on['delta'] = on['delta'].fillna(0)

        on['date'] = on['datetime'].dt.normalize()
        pm = on['t'] >= dt_time(18, 0)
        on.loc[pm, 'date'] = on.loc[pm, 'date'] + pd.Timedelta(days=1)

        out = on.groupby('date')['delta'].sum().reset_index()
        out.columns = ['date', 'on_cum_delta']
        out['date'] = pd.to_datetime(out['date'])
        return out
