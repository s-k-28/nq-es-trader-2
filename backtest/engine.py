"""
Event-driven backtester with conservative fill logic.

P2 fix: when a candle's range spans both stop and target, assume stop first.
PnL with partials: partial_r + remainder_r = total_r.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass
from config import Config
from strategy.detector import TradeSetup


@dataclass
class Trade:
    setup: TradeSetup
    entry_time: pd.Timestamp
    entry_price: float
    direction: str
    stop_price: float
    target_price: float
    risk: float               # absolute price distance

    exit_time: pd.Timestamp | None = None
    exit_price: float = 0.0
    exit_reason: str = ''
    partial_r: float = 0.0    # R earned from the partial (50% at 2R = 1.0R)
    remainder_r: float = 0.0  # R earned from the rest
    total_r: float = 0.0
    moved_be: bool = False
    partial_taken: bool = False
    risk_ticks: float = 0.0


class BacktestEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.tick = cfg.instrument.tick_size

    def run(self, df: pd.DataFrame, setups: list[TradeSetup]) -> list[Trade]:
        trades = []
        for s in setups:
            t = self._sim(df, s)
            if t is not None:
                trades.append(t)
        return trades

    # ──────────────────────────────────────────────────────────────────
    def _sim(self, df: pd.DataFrame, setup: TradeSetup) -> Trade | None:
        mask = df['datetime'] >= setup.ts
        if not mask.any():
            return None
        start = mask.idxmax()

        # find fill candle
        fill_idx = None
        limit = min(start + self.cfg.strategy.fvg_max_wait_candles, len(df))
        for i in range(start, limit):
            b = df.iloc[i]
            if setup.direction == 'long' and b['low'] <= setup.entry:
                fill_idx = i
                break
            if setup.direction == 'short' and b['high'] >= setup.entry:
                fill_idx = i
                break

        if fill_idx is None:
            return None

        risk = abs(setup.entry - setup.stop)
        trade = Trade(
            setup=setup,
            entry_time=df.iloc[fill_idx]['datetime'],
            entry_price=setup.entry,
            direction=setup.direction,
            stop_price=setup.stop,
            target_price=setup.target,
            risk=risk,
            risk_ticks=setup.risk_ticks,
        )

        cur_stop = setup.stop
        be = False
        partial = False
        partial_r = 0.0
        time_limit = trade.entry_time + pd.Timedelta(
            minutes=self.cfg.strategy.time_stop_minutes)

        is_long = setup.direction == 'long'

        for i in range(fill_idx + 1, len(df)):
            b = df.iloc[i]

            if is_long:
                hit_stop = b['low'] <= cur_stop
                hit_target = b['high'] >= setup.target
                pnl_at_close = b['close'] - setup.entry
                best_pnl = b['high'] - setup.entry
            else:
                hit_stop = b['high'] >= cur_stop
                hit_target = b['low'] <= setup.target
                pnl_at_close = setup.entry - b['close']
                best_pnl = setup.entry - b['low']

            # P2 FIX: both hit in same candle → assume stop first
            if hit_stop and hit_target:
                self._close(trade, b, cur_stop, 'stop_ambiguous',
                            is_long, partial_r, partial)
                break

            if hit_stop:
                reason = 'breakeven' if be else 'stop'
                self._close(trade, b, cur_stop, reason,
                            is_long, partial_r, partial)
                break

            if hit_target:
                self._close(trade, b, setup.target, 'target',
                            is_long, partial_r, partial)
                break

            # partial at 2R
            if not partial and best_pnl >= risk * self.cfg.risk.partial_rr:
                partial = True
                partial_r = self.cfg.risk.partial_pct * self.cfg.risk.partial_rr
                trade.partial_taken = True

            # move to BE at 1R
            if not be and best_pnl >= risk * self.cfg.risk.be_trigger_rr:
                cur_stop = setup.entry
                be = True
                trade.moved_be = True

            # time stop (only if not yet at BE — if at BE, let it run)
            if b['datetime'] >= time_limit and not be:
                self._close(trade, b, b['close'], 'time_stop',
                            is_long, partial_r, partial)
                break

            # session close
            if b['datetime'].time() >= self.cfg.sessions.session_close:
                self._close(trade, b, b['close'], 'session_close',
                            is_long, partial_r, partial)
                break
        else:
            last = df.iloc[-1]
            self._close(trade, last, last['close'], 'end_of_data',
                        is_long, partial_r, partial)

        return trade

    # ──────────────────────────────────────────────────────────────────
    def _close(self, trade: Trade, bar, exit_price: float, reason: str,
               is_long: bool, partial_r: float, partial_taken: bool):
        trade.exit_time = bar['datetime'] if isinstance(bar, pd.Series) else bar
        trade.exit_price = exit_price
        trade.exit_reason = reason

        risk = trade.risk
        if risk == 0:
            trade.total_r = 0
            return

        if is_long:
            raw_r = (exit_price - trade.entry_price) / risk
        else:
            raw_r = (trade.entry_price - exit_price) / risk

        if partial_taken:
            # partial already banked
            remainder_pct = 1.0 - self.cfg.risk.partial_pct
            trade.partial_r = partial_r
            trade.remainder_r = remainder_pct * raw_r
            trade.total_r = trade.partial_r + trade.remainder_r
        else:
            trade.partial_r = 0.0
            trade.remainder_r = raw_r
            trade.total_r = raw_r
