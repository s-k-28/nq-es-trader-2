"""
Orchestrator — runs the full detection pipeline over a 1-min dataframe
and returns a list of TradeSetup objects.

Uses a per-day state machine:
  IDLE → SWEEP_FOUND → MSS_FOUND → SETUP_READY

Resets state each new day.  Applies all filters before scanning:
  1. killzone window
  2. no Friday PM
  3. daily loss limit (tracked externally in backtest)
  4. bias ≠ 0
  5. regime expanding
  6. intermarket confirmation (ES not diverging)
"""
from __future__ import annotations
import pandas as pd
from config import Config
from data.sessions import SessionClassifier
from strategy.bias import BiasEngine
from strategy.regime import RegimeFilter
from strategy.levels import LevelTracker
from strategy.detector import SignalDetector, TradeSetup


class SignalGenerator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.bias = BiasEngine(cfg)
        self.regime = RegimeFilter(cfg)
        self.levels = LevelTracker(cfg)
        self.det = SignalDetector(cfg)
        self.sess = SessionClassifier(cfg.sessions)

    def generate(self, df_nq: pd.DataFrame, daily: pd.DataFrame,
                 df_es: pd.DataFrame | None = None) -> list[TradeSetup]:

        self.bias.precompute(daily, df_nq)
        self.regime.precompute(daily)

        setups: list[TradeSetup] = []

        cur_date = None
        state = 'IDLE'
        sweep = None
        mss = None
        fvg_wait = 0
        pending_setup: TradeSetup | None = None

        on_high = on_low = None
        sess_high = sess_low = None

        for idx in range(60, len(df_nq)):
            bar = df_nq.iloc[idx]
            dt = bar['datetime']
            date = pd.Timestamp(dt.date())

            # ── new day ───────────────────────────────────────────────
            if date != cur_date:
                cur_date = date
                state = 'IDLE'
                sweep = mss = None
                pending_setup = None

                dl = self.bias.get_daily_levels(date)
                if dl:
                    self.levels.update_daily(dl['pdh'], dl['pdl'], dl['weekly_open'])

                if on_high is not None:
                    self.levels.update_session(on_high, on_low, 'overnight')

                sess_high = sess_low = None
                on_high = on_low = None

            # ── track session extremes ────────────────────────────────
            s = self.sess.get_session(dt)
            if s == 'rth':
                sess_high = max(sess_high, bar['high']) if sess_high else bar['high']
                sess_low = min(sess_low, bar['low']) if sess_low else bar['low']
            else:
                on_high = max(on_high, bar['high']) if on_high else bar['high']
                on_low = min(on_low, bar['low']) if on_low else bar['low']

            if idx % 25 == 0:
                self.levels.update_swings(df_nq.iloc[max(0, idx - 120): idx + 1])

            # ── filters ───────────────────────────────────────────────
            if not self.sess.is_killzone(dt):
                continue
            if self.cfg.risk.no_friday_pm and self.sess.is_friday_pm(dt):
                continue

            bias = self.bias.get_bias(date)
            if bias == 0:
                continue
            if not self.regime.is_tradeable(date):
                continue

            levels = self.levels.get_all()

            # ── state: waiting for FVG fill ───────────────────────────
            if state == 'PENDING_FILL':
                fvg_wait += 1
                if fvg_wait > self.cfg.strategy.fvg_max_wait_candles:
                    state = 'IDLE'
                    pending_setup = None
                    continue

                filled = False
                if pending_setup.direction == 'long' and bar['low'] <= pending_setup.entry:
                    filled = True
                elif pending_setup.direction == 'short' and bar['high'] >= pending_setup.entry:
                    filled = True

                if filled:
                    if self._intermarket_ok(df_es, dt, pending_setup.direction):
                        setups.append(pending_setup)
                    state = 'IDLE'
                    pending_setup = None
                continue

            # ── IDLE: look for sweep ──────────────────────────────────
            if state == 'IDLE':
                sw = self.det.detect_sweep(df_nq, levels, idx)
                if sw is None:
                    continue
                if bias == 1 and sw.direction != 'bearish_sweep':
                    continue
                if bias == -1 and sw.direction != 'bullish_sweep':
                    continue
                sweep = sw
                state = 'SWEEP_FOUND'
                continue

            # ── SWEEP_FOUND: look for MSS ─────────────────────────────
            if state == 'SWEEP_FOUND':
                if idx - sweep.idx > 15:
                    state = 'IDLE'
                    sweep = None
                    continue

                m = self.det.detect_mss(df_nq, sweep, idx, idx + 1)
                if m is None:
                    continue
                mss = m
                state = 'MSS_FOUND'
                # fall through to check FVG immediately

            # ── MSS_FOUND: look for FVG ───────────────────────────────
            if state == 'MSS_FOUND':
                if idx - mss.idx > 5:
                    state = 'IDLE'
                    sweep = mss = None
                    continue

                f = self.det.detect_fvg(df_nq, mss)
                if f is None:
                    continue

                setup = self.det.build_setup(sweep, mss, f)
                if setup is None:
                    state = 'IDLE'
                    sweep = mss = None
                    continue

                pending_setup = setup
                fvg_wait = 0
                state = 'PENDING_FILL'

        return setups

    # ── intermarket ───────────────────────────────────────────────────
    def _intermarket_ok(self, df_es: pd.DataFrame | None,
                        dt: pd.Timestamp, direction: str) -> bool:
        if not self.cfg.strategy.use_intermarket or df_es is None:
            return True

        es = df_es[df_es['datetime'] <= dt]
        if len(es) < 20:
            return True

        now = es.iloc[-1]['close']
        then = es.iloc[-20]['close']
        if direction == 'long':
            return now >= then
        return now <= then
