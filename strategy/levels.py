from __future__ import annotations
import numpy as np
import pandas as pd
from config import Config


class LevelTracker:
    """Tracks key liquidity levels: PDH/PDL, session extremes, equal H/L clusters."""

    def __init__(self, cfg: Config):
        self.tick = cfg.instrument.tick_size
        self.tol = cfg.strategy.equal_level_tolerance_ticks * self.tick
        self.lookback = cfg.strategy.swing_lookback
        self._levels: dict[str, float] = {}

    def update_daily(self, pdh: float, pdl: float, weekly_open: float):
        self._levels['pdh'] = pdh
        self._levels['pdl'] = pdl
        self._levels['weekly_open'] = weekly_open

    def update_session(self, hi: float, lo: float, name: str):
        self._levels[f'{name}_high'] = hi
        self._levels[f'{name}_low'] = lo

    def update_swings(self, bars: pd.DataFrame):
        lb = self.lookback
        if len(bars) < 2 * lb + 1:
            return

        highs = bars['high'].values
        lows = bars['low'].values
        sh, sl = [], []

        for i in range(lb, len(bars) - lb):
            window_h = highs[i - lb: i + lb + 1]
            window_l = lows[i - lb: i + lb + 1]
            if highs[i] == window_h.max():
                sh.append(highs[i])
            if lows[i] == window_l.min():
                sl.append(lows[i])

        # purge old equal-level keys
        self._levels = {k: v for k, v in self._levels.items()
                        if not k.startswith('eq_')}

        for lvl in self._cluster(sh):
            self._levels[f'eq_high_{lvl:.2f}'] = lvl
        for lvl in self._cluster(sl):
            self._levels[f'eq_low_{lvl:.2f}'] = lvl

    def get_all(self) -> dict[str, float]:
        return self._levels.copy()

    def nearest_above(self, price: float):
        above = [(k, v) for k, v in self._levels.items() if v > price]
        return min(above, key=lambda x: x[1]) if above else None

    def nearest_below(self, price: float):
        below = [(k, v) for k, v in self._levels.items() if v < price]
        return max(below, key=lambda x: x[1]) if below else None

    def _cluster(self, vals: list[float]) -> list[float]:
        if len(vals) < 2:
            return []
        vals = sorted(vals)
        clusters = []
        i = 0
        while i < len(vals):
            group = [vals[i]]
            j = i + 1
            while j < len(vals) and vals[j] - vals[i] <= self.tol:
                group.append(vals[j])
                j += 1
            if len(group) >= 2:
                clusters.append(float(np.mean(group)))
            i = j
        return clusters
