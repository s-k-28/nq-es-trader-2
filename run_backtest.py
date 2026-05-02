#!/usr/bin/env python3
"""
Liquidity Sweep Reversal v2 — Backtester

Usage:
  python run_backtest.py --nq data/NQ_1min.csv [--es data/ES_1min.csv]
  python run_backtest.py --synthetic          # run on generated test data
"""
import argparse
import sys
import pandas as pd
from config import Config
from data.loader import load_csv, build_daily_bars, generate_synthetic_data
from strategy.signals import SignalGenerator
from backtest.engine import BacktestEngine
from backtest.metrics import Metrics


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--nq', help='NQ intraday CSV path')
    p.add_argument('--es', help='ES intraday CSV (optional, for intermarket filter)')
    p.add_argument('--nq-daily', help='NQ daily CSV for bias/regime warmup (longer history)')
    p.add_argument('--synthetic', action='store_true', help='Use generated test data')
    p.add_argument('--days', type=int, default=120, help='Synthetic data days')
    p.add_argument('--account', type=float, default=50000)
    p.add_argument('--risk', type=float, default=1.0, help='Risk %% per trade')
    p.add_argument('--rr', type=float, default=3.0, help='Target R:R')
    p.add_argument('--plot', default=None, help='Save equity chart to path')
    p.add_argument('--csv', default=None, help='Save trade log CSV')
    args = p.parse_args()

    cfg = Config()
    cfg.account_size = args.account
    cfg.risk.risk_per_trade_pct = args.risk
    cfg.risk.target_rr = args.rr

    # ── load data ─────────────────────────────────────────────────────
    if args.synthetic:
        print(f"Generating {args.days}-day synthetic NQ data...")
        df_nq = generate_synthetic_data(days=args.days)
        df_es = generate_synthetic_data(days=args.days, symbol='ES',
                                        start_price=5200.0)
        cfg.strategy.use_intermarket = True
    elif args.nq:
        print(f"Loading {args.nq}...")
        df_nq = load_csv(args.nq, 'NQ')
        df_es = load_csv(args.es, 'ES') if args.es else None
        cfg.strategy.use_intermarket = df_es is not None
    else:
        print("Provide --nq <file> or --synthetic")
        sys.exit(1)

    print(f"  {len(df_nq):,} NQ bars  "
          f"({df_nq['datetime'].min()} → {df_nq['datetime'].max()})")

    if args.nq_daily:
        print(f"Loading daily warmup from {args.nq_daily}...")
        daily_raw = load_csv(args.nq_daily, 'NQ')
        daily = daily_raw.rename(columns={'datetime': 'date'})
        daily['date'] = pd.to_datetime(daily['date'])
    else:
        daily = build_daily_bars(df_nq)
    print(f"  {len(daily)} daily bars")

    # ── signals ───────────────────────────────────────────────────────
    print("\nScanning for setups...")
    gen = SignalGenerator(cfg)
    setups = gen.generate(df_nq, daily, df_es)
    print(f"  {len(setups)} setups found")

    if not setups:
        print("No trades. Check data range or loosen filters.")
        sys.exit(0)

    # ── simulate ──────────────────────────────────────────────────────
    print("Simulating trades (conservative fills)...")
    engine = BacktestEngine(cfg)
    trades = engine.run(df_nq, setups)
    print(f"  {len(trades)} trades executed")

    # ── report ────────────────────────────────────────────────────────
    metrics = Metrics(trades, cfg)
    metrics.print_report()

    if args.plot:
        metrics.plot(args.plot)
    if args.csv:
        metrics.df.to_csv(args.csv, index=False)
        print(f"\nTrade log → {args.csv}")


if __name__ == '__main__':
    main()
