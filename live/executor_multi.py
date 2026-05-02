"""Live executor — runs OU+VWAP strategy on TopStepX funded account.

Schedule: Mon-Fri mornings, up to 20 MNQ dynamically sized.

Adaptive withdrawals: extract $500-$2K whenever balance exceeds
DD floor + $2K buffer. Requires 5 winning days ($150+) per TopStepX.

Risk controls:
- Dynamic position sizing: qty = min(20, floor($500 / (risk_ticks * $0.50)))
- $500 prospective daily loss cap: skip trades if worst-case would breach
- Streak protection: 50% size after 3 consecutive losing days
- Skip 30-50 tick risk signals (dead zone)
- Reduce to 15 MNQ when drawdown >= $1,500
- Halt trading if cushion above DD floor < max single-trade loss

Funded account rules (TopStepX Express Funded 50K):
- $2,000 EOD trailing drawdown (locks at $50K floor once peak hits $52K)
- $1,000 daily loss limit (auto-liquidation, not permanent)
- 90/10 profit split
"""
from __future__ import annotations
import logging
import time
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field
import pandas as pd
from config import Config
from data.loader import build_daily_bars
from strategy.multi import MultiModelGenerator
from strategy.models.base import Signal
from live.broker_topstep import TopStepBroker

log = logging.getLogger(__name__)

TICK_SIZE = 0.25
MNQ_TICK_VALUE = 0.50
CT = ZoneInfo('America/Chicago')


@dataclass
class LiveTrade:
    signal: Signal
    direction: str
    entry_price: float
    stop_price: float
    target_price: float
    risk: float
    entry_time: datetime
    contracts: int
    order_ids: dict = field(default_factory=dict)
    moved_be: bool = False
    partial_taken: bool = False
    trailing: bool = False
    mfe: float = 0.0


class LiveExecutor:
    def __init__(self, cfg: Config, broker: TopStepBroker, contracts: int = 20):
        self.cfg = cfg
        self.broker = broker
        self.contracts = contracts

        self.buf = pd.DataFrame()
        self.daily_df = pd.DataFrame()
        self.gen = MultiModelGenerator(cfg)
        self.last_signal_key = None
        self.trade: LiveTrade | None = None

        self.daily_r = 0.0
        self.daily_pnl_usd = 0.0
        self.daily_model_count = {}
        self.cur_date = None
        self.peak_balance = None
        self.start_balance = None
        self.winning_days = 0
        self.total_days = 0

        self.active_models = {'ou_rev', 'vwap_rev'}
        self.withdraw_buffer_usd = 2000
        self.min_withdraw_usd = 500
        self.contracts_reduced = 15
        self.dd_cutback_usd = 1500
        self.risk_skip_min = 30
        self.risk_skip_max = 50
        self.dd_floor = None
        self.dd_locked = False
        self.max_risk_ticks = 100
        self.max_trade_loss_usd = 500
        self.daily_loss_cap_usd = 500
        self.consec_losing_days = 0
        self.streak_reduce_after = 3
        self.streak_reduce_pct = 0.50

    def run(self):
        log.info("Loading historical bars for warmup...")
        self.buf = self.broker.get_bars(minutes_back=5000)
        log.info(f"Loaded {len(self.buf)} bars "
                 f"({self.buf['datetime'].min()} → {self.buf['datetime'].max()})")

        self.daily_df = build_daily_bars(self.buf)
        self.daily_df['date'] = pd.to_datetime(self.daily_df['date']).dt.date

        acct = self.broker.get_account_info()
        self.start_balance = acct.get('balance', 50000)
        self.peak_balance = self.start_balance
        self.dd_floor = self.start_balance - 2000
        self.dd_locked = False
        log.info(f"Account balance: ${self.start_balance:,.0f}")

        log.info(f"Strategy active — {self.contracts} MNQ max | "
                 f"Models: {', '.join(sorted(self.active_models))}")
        log.info(f"Risk: max trade loss ${self.max_trade_loss_usd} | "
                 f"daily cap -${self.daily_loss_cap_usd} | "
                 f"skip {self.risk_skip_min}-{self.risk_skip_max}t dead zone")
        log.info(f"Streak: {self.streak_reduce_pct*100:.0f}% size after "
                 f"{self.streak_reduce_after} losing days | "
                 f"DD cutback: {self.contracts_reduced} MNQ @ ${self.dd_cutback_usd} DD")
        log.info(f"Withdraw: adaptive, ${self.min_withdraw_usd}+ when "
                 f"${self.withdraw_buffer_usd} buffer above DD floor")
        log.info("Waiting for signals...\n")

        while True:
            try:
                self._tick()
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("Tick error")
            time.sleep(30)

    def _tick(self):
        now = datetime.now(CT)
        today = now.date()

        if today != self.cur_date:
            self._new_day(today)

        if now.time() < dt_time(8, 30):
            return
        if now.time() >= dt_time(14, 55):
            if self.trade:
                log.info("Session close — flattening")
                self._close_trade('session_close')
            return

        latest = self.broker.get_latest_bars(10)
        if latest.empty:
            return
        new_bars = self._merge_bars(latest)
        if new_bars == 0:
            return

        self.daily_df = build_daily_bars(self.buf)
        self.daily_df['date'] = pd.to_datetime(self.daily_df['date']).dt.date

        if self.trade:
            self._manage_trade()
        else:
            self._check_signals()

    def _new_day(self, today):
        if self.cur_date is not None:
            self.total_days += 1
            if self.daily_pnl_usd > 0:
                self.winning_days += 1
            if self.daily_pnl_usd < 0:
                self.consec_losing_days += 1
            else:
                self.consec_losing_days = 0

        self.cur_date = today
        self.daily_r = 0.0
        self.daily_pnl_usd = 0.0
        self.daily_model_count = {}

        log.info(f"\n{'='*55}")
        log.info(f"New day: {today}")

        acct = self.broker.get_account_info()
        bal = acct.get('balance', self.start_balance)
        if bal > self.peak_balance:
            self.peak_balance = bal
        self._update_dd_floor()
        dd = self.peak_balance - bal
        cushion = bal - self.dd_floor
        total_pnl = bal - self.start_balance

        log.info(f"Balance: ${bal:,.0f} | P&L: ${total_pnl:+,.0f} | "
                 f"Peak: ${self.peak_balance:,.0f}")
        log.info(f"DD floor: ${self.dd_floor:,.0f} ({'locked' if self.dd_locked else 'trailing'}) | "
                 f"Cushion: ${cushion:,.0f} | "
                 f"Win days: {self.winning_days} | "
                 f"Trading days: {self.total_days}")
        if self.consec_losing_days >= self.streak_reduce_after:
            log.info(f"STREAK ALERT: {self.consec_losing_days} consecutive losing days — "
                     f"reducing size to {self.streak_reduce_pct*100:.0f}%")
        log.info(f"{'='*55}\n")

    def _merge_bars(self, latest: pd.DataFrame) -> int:
        if self.buf.empty:
            self.buf = latest
            return len(latest)
        last_time = self.buf['datetime'].max()
        new = latest[latest['datetime'] > last_time]
        if new.empty:
            return 0
        self.buf = pd.concat([self.buf, new], ignore_index=True)
        if len(self.buf) > 3000:
            self.buf = self.buf.iloc[-3000:].reset_index(drop=True)
        return len(new)

    def _update_dd_floor(self):
        if not self.dd_locked and (self.peak_balance - self.start_balance) >= 2000:
            self.dd_locked = True
            self.dd_floor = self.peak_balance - 2000
        if not self.dd_locked:
            self.dd_floor = self.peak_balance - 2000

    def _check_signals(self):
        now = datetime.now(CT)
        if now.time() >= dt_time(12, 0):
            return

        acct = self.broker.get_account_info()
        bal = acct.get('balance', self.start_balance)
        if bal > self.peak_balance:
            self.peak_balance = bal
        self._update_dd_floor()
        cushion = bal - self.dd_floor
        if cushion <= self.max_trade_loss_usd:
            log.warning(f"DD protection — ${cushion:,.0f} cushion above floor "
                        f"${self.dd_floor:,.0f}, need ${self.max_trade_loss_usd:,.0f} for max trade")
            return

        try:
            signals = self.gen.generate(self.buf, self.daily_df, None)
        except Exception:
            log.exception("Signal generation failed")
            return

        if not signals:
            return

        signals = [s for s in signals if s.model in self.active_models]
        if not signals:
            return

        sig = signals[-1]
        sig_key = f"{sig.model}_{sig.ts}_{sig.direction}"
        if sig_key == self.last_signal_key:
            return

        now = datetime.now(CT)
        sig_age = (now - sig.ts.to_pydatetime().replace(tzinfo=CT)).total_seconds()
        if sig_age > 120:
            return

        model_key = (self.cur_date, sig.model)
        rp = sig.risk_profile
        if rp and self.daily_model_count.get(model_key, 0) >= rp.max_daily:
            return

        self.last_signal_key = sig_key
        self._enter_trade(sig)

    def _enter_trade(self, sig: Signal):
        risk = abs(sig.entry - sig.stop)
        if risk <= 0:
            return

        if self.risk_skip_min <= sig.risk_ticks <= self.risk_skip_max:
            log.info(f"    SKIP — {sig.risk_ticks:.0f} tick risk in dead zone "
                     f"({self.risk_skip_min}-{self.risk_skip_max})")
            return

        qty = min(self.contracts,
                  int(self.max_trade_loss_usd / (sig.risk_ticks * MNQ_TICK_VALUE)))
        if qty < 1:
            qty = 1

        if self.consec_losing_days >= self.streak_reduce_after:
            qty = max(1, int(qty * self.streak_reduce_pct))
            log.info(f"    STREAK — {self.consec_losing_days} losing days, "
                     f"reduced to {qty} MNQ")

        acct = self.broker.get_account_info()
        bal = acct.get('balance', self.start_balance)
        dd = self.peak_balance - bal if self.peak_balance else 0
        if dd >= self.dd_cutback_usd:
            qty = min(qty, self.contracts_reduced)
            log.info(f"    DD protection — ${dd:,.0f} drawdown, reducing to {qty} MNQ")

        potential_loss = sig.risk_ticks * qty * MNQ_TICK_VALUE
        if self.daily_pnl_usd - potential_loss < -self.daily_loss_cap_usd:
            log.info(f"    SKIP — daily cap: P&L ${self.daily_pnl_usd:,.0f}, "
                     f"potential loss ${potential_loss:,.0f} would breach "
                     f"-${self.daily_loss_cap_usd:,.0f} cap")
            return

        log.info(f"\n>>> SIGNAL: [{sig.model}] {sig.direction.upper()} "
                 f"@ {sig.entry:.2f} ({qty} MNQ)")
        log.info(f"    Stop: {sig.stop:.2f} | Target: {sig.target:.2f} | "
                 f"RR: {sig.rr:.1f} | Risk: {sig.risk_ticks:.0f} ticks | "
                 f"Max loss: ${potential_loss:,.0f}")

        try:
            ids = self.broker.place_bracket(
                direction=sig.direction,
                qty=qty,
                stop_price=sig.stop,
                target_price=sig.target,
            )
        except Exception:
            log.exception("Order placement failed")
            return

        rp = sig.risk_profile
        time_stop = rp.time_stop_minutes if rp else self.cfg.strategy.time_stop_minutes

        self.trade = LiveTrade(
            signal=sig,
            direction=sig.direction,
            entry_price=sig.entry,
            stop_price=sig.stop,
            target_price=sig.target,
            risk=risk,
            entry_time=datetime.now(CT),
            contracts=qty,
            order_ids=ids,
        )

        model_key = (self.cur_date, sig.model)
        self.daily_model_count[model_key] = \
            self.daily_model_count.get(model_key, 0) + 1

        log.info(f"    ENTERED — {qty} MNQ | "
                 f"Time stop: {time_stop} min")

    def _manage_trade(self):
        t = self.trade
        if not t:
            return

        pos = self.broker.position_size()
        if pos == 0:
            self._on_trade_closed()
            return

        bar = self.buf.iloc[-1]
        is_long = t.direction == 'long'
        rp = t.signal.risk_profile

        be_trigger = rp.be_trigger_rr if rp else self.cfg.risk.be_trigger_rr
        partial_rr = rp.partial_rr if rp else self.cfg.risk.partial_rr
        trail_pct = rp.trail_pct if rp else 0.0
        time_stop_min = rp.time_stop_minutes if rp else self.cfg.strategy.time_stop_minutes

        if is_long:
            best = bar['high'] - t.entry_price
        else:
            best = t.entry_price - bar['low']

        if best > t.mfe:
            t.mfe = best
            if t.trailing and trail_pct > 0:
                trail_dist = trail_pct * t.risk
                if is_long:
                    new_stop = t.entry_price + t.mfe - trail_dist
                    if new_stop > t.stop_price:
                        t.stop_price = round(new_stop / TICK_SIZE) * TICK_SIZE
                        self.broker.modify_stop(t.stop_price)
                else:
                    new_stop = t.entry_price - t.mfe + trail_dist
                    if new_stop < t.stop_price:
                        t.stop_price = round(new_stop / TICK_SIZE) * TICK_SIZE
                        self.broker.modify_stop(t.stop_price)

        if not t.partial_taken and t.risk > 0 and best >= t.risk * partial_rr:
            t.partial_taken = True
            if trail_pct > 0:
                t.trailing = True
            log.info(f"    Partial trigger hit ({partial_rr}R)")

        if not t.moved_be and t.risk > 0 and best >= t.risk * be_trigger:
            t.moved_be = True
            t.stop_price = t.entry_price
            self.broker.modify_stop(t.entry_price)
            log.info(f"    Moved stop to BREAKEVEN @ {t.entry_price:.2f}")

        elapsed = (datetime.now(CT) - t.entry_time).total_seconds() / 60
        if elapsed >= time_stop_min and not t.moved_be:
            log.info(f"    TIME STOP ({time_stop_min} min)")
            self._close_trade('time_stop')
            return

        if datetime.now(CT).time() >= dt_time(14, 55):
            log.info("    SESSION CLOSE")
            self._close_trade('session_close')

    def _on_trade_closed(self):
        t = self.trade
        if not t:
            return

        self.broker.cancel_all_exit_orders()

        try:
            trades = self.broker._post('/api/Trade/search', {
                'accountId': self.broker.account_id,
                'startTimestamp': t.entry_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            })
            trade_list = trades.get('trades', [])
            pnl = sum(tr.get('profitAndLoss', 0) for tr in trade_list
                      if tr.get('contractId') == self.broker.contract_id)
        except Exception:
            pnl = 0

        risk_usd = t.risk * t.contracts * MNQ_TICK_VALUE / TICK_SIZE
        total_r = pnl / risk_usd if risk_usd > 0 else 0

        self.daily_r += total_r
        self.daily_pnl_usd += pnl

        reason = 'target' if total_r > 0.5 else ('stop' if total_r < -0.5 else 'breakeven')
        log.info(f"\n    CLOSED — {reason} | {total_r:+.2f}R (${pnl:+,.0f})")
        log.info(f"    Daily: {self.daily_r:+.2f}R (${self.daily_pnl_usd:+,.0f})")

        self.broker._stop_order_id = None
        self.broker._target_order_id = None
        self.broker._entry_order_id = None
        self.trade = None

        self._check_withdraw_threshold()

    def _close_trade(self, reason: str):
        log.info(f"    Closing trade: {reason}")
        self.broker.flatten()

        t = self.trade
        if t:
            bar = self.buf.iloc[-1] if not self.buf.empty else None
            if bar is not None:
                is_long = t.direction == 'long'
                if is_long:
                    raw_pnl = (bar['close'] - t.entry_price)
                else:
                    raw_pnl = (t.entry_price - bar['close'])
                total_r = raw_pnl / t.risk if t.risk > 0 else 0
            else:
                total_r = 0

            self.daily_r += total_r
            pnl_usd = total_r * t.risk * t.contracts * MNQ_TICK_VALUE / TICK_SIZE
            self.daily_pnl_usd += pnl_usd

            log.info(f"    Result: {total_r:+.2f}R (${pnl_usd:+,.0f}) | "
                     f"Daily: {self.daily_r:+.2f}R (${self.daily_pnl_usd:+,.0f})")

        self.broker._stop_order_id = None
        self.broker._target_order_id = None
        self.broker._entry_order_id = None
        self.trade = None

    def _check_withdraw_threshold(self):
        acct = self.broker.get_account_info()
        bal = acct.get('balance', self.start_balance)
        if bal > self.peak_balance:
            self.peak_balance = bal
        self._update_dd_floor()

        if self.winning_days < 5:
            return

        available = bal - (self.dd_floor + self.withdraw_buffer_usd)
        if available < self.min_withdraw_usd:
            return

        payout_amt = min(2000, int(available / 100) * 100)
        if payout_amt < self.min_withdraw_usd:
            return

        log.info(f"\n{'*'*55}")
        log.info(f"WITHDRAW READY — Balance ${bal:,.0f}")
        log.info(f"DD floor: ${self.dd_floor:,.0f} | Buffer: ${self.withdraw_buffer_usd:,.0f}")
        log.info(f"Available: ${available:,.0f} | Withdraw: ${payout_amt:,}")
        log.info(f"{'*'*55}\n")

    def shutdown(self):
        if self.trade:
            log.info("Shutdown — flattening open position")
            self.broker.flatten()
        log.info("Executor shutdown complete.")
