"""Multi-model signal orchestrator v9 — confluence scoring + trailing stops.

Loads all registered models, precomputes shared context (VWAP, ORB, regime,
daily levels), merges signals, scores confluence, and resolves conflicts.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import time as dt_time
from config import Config
from strategy.vwap import compute_vwap, compute_opening_range
from strategy.models.base import Signal
from strategy.models import ALL_MODELS

CONFLUENCE_THRESHOLD = 3


class MultiModelGenerator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.tick = cfg.instrument.tick_size
        self.models = [ModelClass(cfg) for ModelClass in ALL_MODELS]

    def generate(self, df: pd.DataFrame, daily: pd.DataFrame,
                 df_es: pd.DataFrame | None = None) -> list[Signal]:
        df = compute_vwap(df)
        df = compute_opening_range(df, minutes=15)
        df = df.reset_index(drop=True)

        from strategy.quant import compute_all_quant_features
        df = compute_all_quant_features(df)

        vol_ma = df['volume'].rolling(20, min_periods=5).mean()
        ema9 = df['close'].ewm(span=9, adjust=False).mean()
        ema21 = df['close'].ewm(span=21, adjust=False).mean()

        context = self._build_context(daily)

        regime_map = context['regime_map']

        all_signals: list[Signal] = []
        for model in self.models:
            sigs = model.generate(df, daily, context)
            all_signals.extend(sigs)

        filtered = []
        for sig in all_signals:
            t = sig.ts.time()
            if t >= dt_time(14, 30):
                continue
            filtered.append(sig)

        filtered.sort(key=lambda s: s.idx)
        resolved = self._resolve_conflicts(filtered)
        return resolved

    def _confluence_score(self, sig: Signal, df: pd.DataFrame,
                          context: dict, vol_ma, ema9, ema21) -> int:
        idx = sig.idx
        if idx >= len(df):
            return 0
        bar = df.iloc[idx]
        d = sig.ts.date()
        t = sig.ts.time()
        score = 0

        regime_map = context['regime_map']
        daily_map = context['daily_map']
        regime = regime_map.get(d, 'chop')

        is_long = sig.direction == 'long'

        if (is_long and regime == 'bull') or (not is_long and regime == 'bear'):
            score += 2
        elif regime == 'chop':
            score += 1

        vwap = bar.get('vwap')
        if not pd.isna(vwap):
            if (is_long and bar['close'] > vwap) or (not is_long and bar['close'] < vwap):
                score += 1

        if idx < len(vol_ma) and not pd.isna(vol_ma.iloc[idx]):
            if bar['volume'] > 1.2 * vol_ma.iloc[idx]:
                score += 1

        if idx < len(ema9) and idx < len(ema21):
            e9, e21 = ema9.iloc[idx], ema21.iloc[idx]
            if (is_long and e9 > e21) or (not is_long and e9 < e21):
                score += 1

        if dt_time(9, 45) <= t <= dt_time(11, 30):
            score += 1
        elif dt_time(13, 30) <= t <= dt_time(15, 0):
            score += 1

        if sig.rr >= 2.5:
            score += 1

        return score

    def _build_context(self, daily: pd.DataFrame) -> dict:
        daily_map = {}
        regime_map = {}
        daily_s = daily.sort_values('date').reset_index(drop=True)
        closes = daily_s['close'].values
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)

        for i in range(1, len(daily_s)):
            d = daily_s.iloc[i]['date']
            prev = daily_s.iloc[i - 1]
            daily_map[d] = {
                'pdh': prev['high'], 'pdl': prev['low'],
                'prev_close': prev['close'],
            }
            if i >= 50:
                c = prev['close']
                above20 = c > ema20[i - 1]
                above50 = c > ema50[i - 1]
                if above20 and above50:
                    regime_map[d] = 'bull'
                elif not above20 and not above50:
                    regime_map[d] = 'bear'
                else:
                    regime_map[d] = 'chop'

        return {'daily_map': daily_map, 'regime_map': regime_map}

    @staticmethod
    def _ema(data, span):
        out = np.empty_like(data, dtype=float)
        out[0] = data[0]
        k = 2.0 / (span + 1)
        for i in range(1, len(data)):
            out[i] = data[i] * k + out[i - 1] * (1 - k)
        return out

    @staticmethod
    def _resolve_conflicts(signals: list[Signal], cooldown_bars: int = 5) -> list[Signal]:
        if not signals:
            return []

        resolved = [signals[0]]
        for sig in signals[1:]:
            last = resolved[-1]
            if sig.idx - last.idx < cooldown_bars:
                if sig.priority < last.priority:
                    resolved[-1] = sig
                elif sig.priority == last.priority and sig.rr > last.rr:
                    resolved[-1] = sig
            else:
                resolved.append(sig)
        return resolved
