"""Funded account simulator — position sizing, dollar loss cap, post-static scaling.

Converts raw Trade objects from the engine into dollar P&L per day,
then simulates funded account mechanics (trailing DD, static phase, payouts).
"""
from __future__ import annotations
import numpy as np
from config import Config
from backtest.engine_v2 import Trade


MNQ_TICK_VALUE = 0.50
MAX_CONTRACTS = 50


def trades_to_daily_pnl(
    trades: list[Trade],
    all_dates: list,
    cfg: Config,
) -> np.ndarray:
    risk_map = cfg.funded.model_risk_dollars
    dlc = cfg.funded.dollar_loss_cap

    daily_pnl: dict = {}
    daily_running: dict = {}

    for t in trades:
        d = t.entry_time.date()
        risk_per_contract = t.risk_ticks * MNQ_TICK_VALUE
        if risk_per_contract <= 0:
            continue

        model_risk = risk_map.get(t.model, 600)
        contracts = min(MAX_CONTRACTS, int(model_risk / risk_per_contract))
        if contracts <= 0:
            continue

        trade_pnl = t.total_r * risk_per_contract * contracts

        if dlc is not None and dlc > 0:
            running = daily_running.get(d, 0.0)
            if running <= -dlc:
                continue

        daily_pnl[d] = daily_pnl.get(d, 0.0) + trade_pnl
        daily_running[d] = daily_running.get(d, 0.0) + trade_pnl

    if dlc is not None and dlc > 0:
        for d in daily_pnl:
            if daily_pnl[d] < -dlc:
                daily_pnl[d] = -dlc

    return np.array([daily_pnl.get(d, 0.0) for d in all_dates])


def simulate_funded_account(
    daily_pnl: np.ndarray,
    rng: np.random.Generator,
    cfg: Config,
    n_days: int = 60,
) -> tuple[float, int, bool]:
    funded = cfg.funded
    sample = rng.choice(daily_pnl, size=n_days, replace=True)

    balance = 0.0
    peak = 0.0
    floor = -funded.trailing_dd
    static = False
    green_days = 0
    extracted = 0.0

    for pnl in sample:
        if pnl != 0 and static:
            scale = 1.0
            for threshold, factor in funded.post_static_scaling:
                if balance > threshold:
                    scale = factor
                    break
            pnl *= scale

        balance += pnl

        if pnl >= funded.green_day_min:
            green_days += 1

        if balance > peak:
            peak = balance

        if not static:
            floor = peak - funded.trailing_dd
            if peak >= funded.static_threshold:
                static = True
                floor = 0.0

        if balance <= floor:
            return extracted, green_days, True

        if green_days >= funded.green_days_per_payout and balance > 0:
            payout = min(funded.max_payout, balance * funded.payout_balance_pct)
            if payout > 0:
                extracted += payout
                balance -= payout
                green_days = 0
            if balance <= floor:
                return extracted, green_days, True

    return extracted, green_days, False


def run_monte_carlo(
    daily_pnl: np.ndarray,
    cfg: Config,
    n_sims: int = 25000,
    n_days: int = 60,
    seed: int = 142,
) -> dict:
    rng = np.random.default_rng(seed)
    survived = 0
    extractions = []

    for _ in range(n_sims):
        ext, _, blew = simulate_funded_account(daily_pnl, rng, cfg, n_days)
        survived += (not blew)
        extractions.append(ext)

    exs = np.array(extractions)
    active = daily_pnl[daily_pnl != 0]
    wins = daily_pnl[daily_pnl > 0]
    losses = daily_pnl[daily_pnl < 0]

    return {
        'survival_rate': survived / n_sims * 100,
        'p5k': (exs >= 5000).sum() / n_sims * 100,
        'p10k': (exs >= 10000).sum() / n_sims * 100,
        'avg_extraction': exs.mean(),
        'median_extraction': np.median(exs),
        'daily_wr': len(wins) / len(active) * 100 if len(active) else 0,
        'daily_wl': wins.mean() / abs(losses.mean()) if len(losses) else 0,
        'green_day_rate': (daily_pnl >= cfg.funded.green_day_min).sum() / len(active) * 100 if len(active) else 0,
        'trading_days': len(active),
        'avg_win': wins.mean() if len(wins) else 0,
        'avg_loss': abs(losses.mean()) if len(losses) else 0,
    }
