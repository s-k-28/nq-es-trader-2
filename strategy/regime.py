from __future__ import annotations
import numpy as np
import pandas as pd
from config import Config


class RegimeFilter:
    """Only trade when vol is expanding from compression (ATR or BBW signal)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cache: pd.DataFrame | None = None

    def precompute(self, daily: pd.DataFrame):
        d = daily.copy()

        # ATR
        d['tr'] = np.maximum(
            d['high'] - d['low'],
            np.maximum(
                (d['high'] - d['close'].shift(1)).abs(),
                (d['low'] - d['close'].shift(1)).abs(),
            ),
        )
        p = self.cfg.strategy.atr_period
        d['atr'] = d['tr'].rolling(p).mean()
        d['atr_prev'] = d['atr'].shift(self.cfg.strategy.atr_expansion_lookback)
        d['atr_ok'] = d['atr'] > d['atr_prev']

        # BBW
        bp = self.cfg.strategy.bbw_period
        d['sma'] = d['close'].rolling(bp).mean()
        d['std'] = d['close'].rolling(bp).std()
        d['bbw'] = (2 * self.cfg.strategy.bbw_std * d['std']) / d['sma']
        d['bbw_sma'] = d['bbw'].rolling(bp).mean()
        d['bbw_ok'] = d['bbw'] > d['bbw_sma']

        d['regime_ok'] = d['atr_ok'] | d['bbw_ok']
        self._cache = d[['date', 'regime_ok', 'atr']].copy()
        return self._cache

    def is_tradeable(self, date) -> bool:
        if self._cache is None:
            raise RuntimeError("call precompute first")
        date = pd.Timestamp(date).normalize()
        prev = self._cache[self._cache['date'] < date]
        if prev.empty:
            return False
        return bool(prev.iloc[-1]['regime_ok'])

    def get_atr(self, date) -> float:
        if self._cache is None:
            return 0.0
        date = pd.Timestamp(date).normalize()
        prev = self._cache[self._cache['date'] < date]
        return float(prev.iloc[-1]['atr']) if not prev.empty else 0.0
