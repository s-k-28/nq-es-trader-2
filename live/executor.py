"""Live execution loop — mirrors the backtest state machine exactly."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
import pandas as pd
from config import Config
from data.loader import build_daily_bars
from data.sessions import SessionClassifier
from strategy.bias import BiasEngine
from strategy.regime import RegimeFilter
from strategy.levels import LevelTracker
from strategy.detector import SignalDetector, TradeSetup
from live.broker_ib import IBBroker

log = logging.getLogger(__name__)


class LiveExecutor:
    def __init__(self, cfg: Config, broker: IBBroker):
        self.cfg = cfg
        self.bk = broker
        self.sess = SessionClassifier(cfg.sessions)
        self.bias = BiasEngine(cfg)
        self.regime = RegimeFilter(cfg)
        self.levels = LevelTracker(cfg)
        self.det = SignalDetector(cfg)

        self._state = 'IDLE'
        self._sweep = None
        self._mss = None
        self._setup: TradeSetup | None = None
        self._fvg_wait = 0
        self._buf = pd.DataFrame()

        self._in_pos = False
        self._entry_time: datetime | None = None
        self._cur_stop = 0.0
        self._be = False
        self._partial = False
        self._daily_losses = 0
        self._cur_date = None

    # ──────────────────────────────────────────────────────────────────
    def run(self):
        log.info("Fetching 30-day history for bias/regime...")
        hist = self.bk.bars(duration='30 D')
        daily = build_daily_bars(hist)
        es_hist = self.bk.es_bars(duration='30 D')

        self.bias.precompute(daily, hist)
        self.regime.precompute(daily)
        self._buf = hist.copy()

        log.info(f"{len(hist)} bars, {len(daily)} daily — entering loop")

        while True:
            self.bk.sleep(60)
            try:
                self._tick()
            except Exception:
                log.exception("tick error")

    # ──────────────────────────────────────────────────────────────────
    def _tick(self):
        now = datetime.now()
        date = pd.Timestamp(now.date())

        # new day
        if date != self._cur_date:
            self._cur_date = date
            self._daily_losses = 0
            self._state = 'IDLE'
            self._sweep = self._mss = self._setup = None

            dl = self.bias.get_daily_levels(date)
            if dl:
                self.levels.update_daily(dl['pdh'], dl['pdl'], dl['weekly_open'])
            log.info(f"New day {date.date()} bias={self.bias.get_bias(date)} "
                     f"regime={self.regime.is_tradeable(date)}")

        # get latest bar
        latest = self.bk.bars(duration='300 S')
        if latest.empty:
            return
        bar = latest.iloc[-1]
        self._buf = pd.concat([self._buf, latest.iloc[-1:]], ignore_index=True)
        if len(self._buf) > 600:
            self._buf = self._buf.iloc[-600:].reset_index(drop=True)

        dt = bar['datetime'] if isinstance(bar['datetime'], datetime) else now

        # ── manage open position ──────────────────────────────────────
        if self._in_pos:
            self._manage(bar, dt)
            return

        # ── filters ───────────────────────────────────────────────────
        if not self.sess.is_killzone(dt):
            return
        if self.cfg.risk.no_friday_pm and self.sess.is_friday_pm(dt):
            return
        if self._daily_losses >= self.cfg.risk.max_daily_losses:
            return
        bias = self.bias.get_bias(date)
        if bias == 0:
            return
        if not self.regime.is_tradeable(date):
            return

        levels = self.levels.get_all()
        idx = len(self._buf) - 1

        if idx % 25 == 0:
            self.levels.update_swings(self._buf.iloc[max(0, idx - 120):idx + 1])

        # ── state machine (mirrors signals.py exactly) ────────────────

        if self._state == 'PENDING_FILL':
            self._fvg_wait += 1
            if self._fvg_wait > self.cfg.strategy.fvg_max_wait_candles:
                log.info("FVG fill timeout — cancelling")
                self.bk.cancel_all()
                self._state = 'IDLE'
                self._setup = None
                return

            pos = self.bk.position()
            if pos != 0:
                self._in_pos = True
                self._entry_time = datetime.now()
                self._cur_stop = self._setup.stop
                self._be = self._partial = False
                self._state = 'IN_TRADE'
                log.info(f"FILLED pos={pos}")
            return

        if self._state == 'IDLE':
            sw = self.det.detect_sweep(self._buf, levels, idx)
            if sw is None:
                return
            if bias == 1 and sw.direction != 'bearish_sweep':
                return
            if bias == -1 and sw.direction != 'bullish_sweep':
                return
            self._sweep = sw
            self._state = 'SWEEP_FOUND'
            log.info(f"SWEEP {sw.direction} @ {sw.level_name}={sw.level_price:.2f}")
            return

        if self._state == 'SWEEP_FOUND':
            if idx - self._sweep.idx > 15:
                self._state = 'IDLE'
                self._sweep = None
                return
            m = self.det.detect_mss(self._buf, self._sweep, idx, idx + 1)
            if m is None:
                return
            self._mss = m
            self._state = 'MSS_FOUND'
            log.info(f"MSS {m.direction} break={m.swing_break:.2f}")

        if self._state == 'MSS_FOUND':
            if idx - self._mss.idx > 5:
                self._state = 'IDLE'
                self._sweep = self._mss = None
                return
            f = self.det.detect_fvg(self._buf, self._mss)
            if f is None:
                return
            setup = self.det.build_setup(self._sweep, self._mss, f)
            if setup is None:
                self._state = 'IDLE'
                return

            self._setup = setup
            self._fvg_wait = 0
            self._state = 'PENDING_FILL'

            qty = self._size(setup)
            log.info(f"SETUP {setup.direction} entry={setup.entry:.2f} "
                     f"stop={setup.stop:.2f} target={setup.target:.2f} qty={qty}")
            self.bk.bracket(setup.direction, setup.entry,
                            setup.stop, setup.target, qty)

    # ──────────────────────────────────────────────────────────────────
    def _manage(self, bar, dt):
        if self._setup is None:
            return
        risk = abs(self._setup.entry - self._setup.stop)
        if self._setup.direction == 'long':
            pnl = bar['close'] - self._setup.entry
        else:
            pnl = self._setup.entry - bar['close']

        # time stop
        if self._entry_time and not self._be:
            elapsed = (datetime.now() - self._entry_time).total_seconds() / 60
            if elapsed >= self.cfg.strategy.time_stop_minutes:
                log.info("TIME STOP")
                self.bk.flatten()
                self.bk.cancel_all()
                self._reset('time_stop')
                return

        # BE at 1R
        if not self._be and pnl >= risk * self.cfg.risk.be_trigger_rr:
            self._be = True
            log.info(f"Moved to BE @ {self._setup.entry:.2f}")

        # check flat
        if self.bk.position() == 0:
            log.info("Position closed by bracket")
            self._reset('bracket')

    def _reset(self, reason: str):
        if reason in ('time_stop', 'stop'):
            self._daily_losses += 1
            log.info(f"Daily losses: {self._daily_losses}/{self.cfg.risk.max_daily_losses}")
        self._in_pos = False
        self._setup = None
        self._state = 'IDLE'
        self._sweep = self._mss = None

    def _size(self, setup: TradeSetup) -> int:
        risk_usd = self.cfg.account_size * self.cfg.risk.risk_per_trade_pct / 100
        per_contract = setup.risk_ticks * self.cfg.instrument.tick_value
        return max(int(risk_usd / per_contract), 1) if per_contract > 0 else 1
