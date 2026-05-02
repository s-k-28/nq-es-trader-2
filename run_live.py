#!/usr/bin/env python3
"""
NQ Multi-Model Trading Bot — TopStepX 50K
Connects directly to TopStepX via their REST API.

Usage:
  python run_live.py              # uses .env file
  python run_live.py --contracts 5 --env demo
"""
import argparse
import logging
import os
from dotenv import load_dotenv
from config import Config, InstrumentConfig
from live.broker_topstep import TopStepBroker
from live.executor_multi import LiveExecutor

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)


def main():
    p = argparse.ArgumentParser(description='NQ Trading Bot — TopStepX 50K')
    p.add_argument('--contracts', type=int,
                   default=int(os.getenv('CONTRACTS', '20')))
    p.add_argument('--env', default=os.getenv('TOPSTEP_ENV', 'demo'),
                   choices=['demo', 'live'])
    args = p.parse_args()

    username = os.getenv('TOPSTEP_USER')
    api_key = os.getenv('TOPSTEP_API_KEY')

    if not username or not api_key:
        print("ERROR: Missing credentials.")
        print("Copy .env.example to .env and fill in your TopStepX credentials:")
        print("  TOPSTEP_USER=your_username")
        print("  TOPSTEP_API_KEY=your_api_key")
        return

    cfg = Config()
    cfg.instrument = InstrumentConfig('MNQ', 0.25, 0.50, 2.0)
    cfg.account_size = 50000

    print(f"""
╔══════════════════════════════════════════════════════╗
║          NQ TRADING BOT — TOPSTEP 50K               ║
╠══════════════════════════════════════════════════════╣
║  Contracts:  {args.contracts} MNQ (max 20 = 2 NQ){' ' * (21 - len(str(args.contracts)))}║
║  Mode:       {args.env.upper()}{' ' * (38 - len(args.env))}║
║  Models:     OU + VWAP + Trend + Sweep               ║
║  Risk:       1.8R profit cap / 0.25R loss cap        ║
║  DD:         $2K trailing (locks at $52K)             ║
║  Payout:     90/10 | 5 winning days                  ║
╠══════════════════════════════════════════════════════╣
║  Press Ctrl+C to stop and flatten all positions      ║
╚══════════════════════════════════════════════════════╝
""")

    broker = TopStepBroker(username, api_key, env=args.env)

    try:
        broker.connect()
    except Exception as e:
        print(f"Connection failed: {e}")
        print("Check your .env credentials and try again.")
        return

    executor = LiveExecutor(cfg, broker, contracts=args.contracts)

    try:
        executor.run()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        executor.shutdown()
        print("Clean exit.")


if __name__ == '__main__':
    main()
