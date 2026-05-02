#!/usr/bin/env python3
"""Multi-model NQ day trading strategy backtester.

Usage:
  python3 run_multi.py --nq data/Dataset_NQ_1min_2022_2025.csv
"""
import argparse
import pandas as pd
from config import Config
from data.loader import load_csv, build_daily_bars
from strategy.multi import MultiModelGenerator
from backtest.engine_v2 import BacktestEngineV2
from backtest.metrics_v2 import MetricsV2


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--nq', required=True)
    p.add_argument('--nq-daily', default=None)
    p.add_argument('--es', default=None)
    p.add_argument('--account', type=float, default=50000)
    p.add_argument('--risk', type=float, default=1.0)
    p.add_argument('--plot', default=None)
    p.add_argument('--csv', default=None)
    args = p.parse_args()

    cfg = Config()
    cfg.account_size = args.account
    cfg.risk.risk_per_trade_pct = args.risk

    raw = load_csv(args.nq, 'NQ')
    print(f"NQ: {len(raw):,} bars  "
          f"({raw['datetime'].min()} -> {raw['datetime'].max()})")

    if args.nq_daily:
        daily_raw = load_csv(args.nq_daily, 'NQ')
        daily = daily_raw.rename(columns={'datetime': 'date'})
        daily['date'] = pd.to_datetime(daily['date']).dt.date
    else:
        print("Building daily bars from intraday data...")
        daily = build_daily_bars(raw)
        daily = daily.rename(columns={'date': 'date'})
        daily['date'] = pd.to_datetime(daily['date']).dt.date

    df_es = load_csv(args.es, 'ES') if args.es else None

    print("Scanning models...")
    gen = MultiModelGenerator(cfg)
    signals = gen.generate(raw, daily, df_es)

    model_counts = {}
    for s in signals:
        model_counts[s.model] = model_counts.get(s.model, 0) + 1
    for m, c in sorted(model_counts.items()):
        print(f"  {m}: {c} signals")
    print(f"  total: {len(signals)} signals")

    print("Simulating...")
    engine = BacktestEngineV2(cfg)
    trades = engine.run(raw, signals)
    print(f"  {len(trades)} trades")

    m = MetricsV2(trades, cfg)
    m.print_report()

    m.funded_sweep()
    m.print_funded_projection(eval_contracts=9)

    if args.plot:
        m.plot(args.plot)
    if args.csv:
        m.df.to_csv(args.csv, index=False)
        print(f"\nTrades -> {args.csv}")


if __name__ == '__main__':
    main()
