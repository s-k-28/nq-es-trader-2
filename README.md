<div align="center">

# NQ-ES Trader (Gen 2)

**A nine-model ensemble trading system for NQ/MNQ futures on TopStepX funded accounts.**

Generation 2 of the NQ/ES ensemble trader line. Nine independent quantitative models scan the same intraday tape, a priority-based orchestrator resolves their conflicts, and a funded-account simulator stress tests the whole thing against TopStep's trailing drawdown and payout rules before a single live order goes out. Backtest and live execution share one config, one signal path, and one sizing formula.

<img src="https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/pandas-2.0+-150458?style=flat-square&logo=pandas&logoColor=white" alt="pandas">
<img src="https://img.shields.io/badge/NumPy-1.24+-013243?style=flat-square&logo=numpy&logoColor=white" alt="NumPy">
<img src="https://img.shields.io/badge/Matplotlib-3.7+-11557c?style=flat-square" alt="Matplotlib">
<img src="https://img.shields.io/badge/Broker-TopStepX%20(ProjectX%20API)-f59e0b?style=flat-square" alt="TopStepX">
<img src="https://img.shields.io/badge/Models-9-22c55e?style=flat-square" alt="Models">

</div>

---

## What it does

The system trades MNQ (Micro E-mini Nasdaq) intraday during regular trading hours. Each of the nine models hunts a different edge: statistical mean reversion, liquidity sweeps at key levels, Kalman-filtered momentum, opening range fades, and more. Every model emits `Signal` objects with a concrete entry, stop, target, and its own risk profile (min/max risk ticks, breakeven trigger, time stop, daily trade cap).

The orchestrator in `strategy/multi.py` runs all nine over the same feature-enriched dataframe, drops anything after 14:30 ET, resolves collisions within a 5-bar cooldown by model priority then reward-to-risk, and passes survivors through a composite quality gate. The result feeds either the backtest engine, the funded-account Monte Carlo, or the live executor - identical logic in all three.

Signal context comes from `strategy/quant/features.py`: a rolling Ornstein-Uhlenbeck fit on the price-VWAP spread (theta, half-life, z-score), Hurst exponent regime classification, a Kalman filter for level and slope, Parkinson high-low volatility, and Bollinger Band squeeze detection.

## Architecture

```
                              RESEARCH PATH
┌──────────────────┐   ┌──────────────────┐   ┌───────────────────────────┐
│  data/loader.py  │   │ quant/features   │   │  strategy/models/  (x9)   │
│  CSV -> bars     ├──►│ OU, Hurst,       ├──►│  ou_rev  pd_rev  vwap_rev │
│  fetch_data.py   │   │ Kalman, VWAP,    │   │  or_rev  ema_rev sweep    │
│  (yfinance/API)  │   │ opening range    │   │  kalman  trend   pm_mom   │
└──────────────────┘   └──────────────────┘   └─────────────┬─────────────┘
                                                            │ Signals
                                                            ▼
┌───────────────────────────┐        ┌──────────────────────────────────┐
│  backtest/engine_v2.py    │◄───────┤  strategy/multi.py               │
│  bar-by-bar simulation    │        │  14:30 cutoff -> conflict        │
│  backtest/funded_sim.py   │        │  resolution -> quality gate      │
│  Monte Carlo (25k runs)   │        │  (strategy/quality.py, 0-12)     │
└────────────┬──────────────┘        └───────────────┬──────────────────┘
             │                                       │
             ▼                            LIVE PATH  ▼
┌───────────────────────────┐        ┌──────────────────────────────────┐
│  metrics_v2, charts,      │        │  live/executor_multi.py          │
│  trades CSVs,             │        │  polls bars, sizes by model tier,│
│  frontend/server.py :8080 │        │  manages BE / trail / time stop  │
└───────────────────────────┘        └───────────────┬──────────────────┘
                                                     ▼
                                     ┌──────────────────────────────────┐
                                     │  live/broker_topstep.py          │
                                     │  TopStepX REST (ProjectX API):   │
                                     │  auth, bars, bracket orders,     │
                                     │  stop modify, flatten            │
                                     └──────────────────────────────────┘
```

## The model ensemble

| Model | File | What it actually does |
|---|---|---|
| `ou_rev` | `ou_reversion.py` | Ornstein-Uhlenbeck mean reversion on the price-VWAP spread. Requires z-score beyond 2 sigma, half-life under 25 bars, positive theta, and Hurst below 0.45. |
| `pd_rev` | `pd_level_reversion.py` | Fades price at the previous day's high or low with candle confirmation. |
| `vwap_rev` | `vwap_reversion.py` | Fades extended moves beyond the VWAP standard deviation bands back toward VWAP. |
| `or_rev` | `or_reversion.py` | Fades extensions beyond the 15-minute opening range. |
| `ema_rev` | `ema_reversion.py` | Fades stretched moves away from the 20-EMA back toward the mean. |
| `sweep` | `sweep_reversal.py` | Liquidity sweep reversal: price runs stops through PDH/PDL or a session extreme, closes back inside, and a strong reversal candle confirms. Restricted to the 9:45-11:00 and 14:00-15:00 windows. |
| `kalman_mom` | `kalman_momentum.py` | Trades in the direction of the Kalman filter slope when the market is trending. |
| `trend` | `trend_cont.py` | Trend continuation: enters on pullbacks to a fast EMA inside an established intraday trend. |
| `pm_mom` | `afternoon_momentum.py` | Kalman-slope pullback entries limited to the afternoon session. |

All nine inherit from `strategy/models/base.py`, which enforces per-model risk bounds and rounds every price to the 0.25 tick.

## How it works

**Entry and exit.** Each signal carries its own `ModelRiskProfile`. The backtest engine (`engine_v2.py`) walks forward bar by bar: stop, target, breakeven move (default 0.6R), optional partial and trailing stop, a per-model time stop (30-45 minutes), and a forced flatten at the 16:59 session close. Stop-type exits are charged a quarter tick of slippage. Only one trade can be open at a time.

**Quality gate.** `strategy/quality.py` scores signals 0-12 using direction, day of week, hour of day, OU half-life, OU z-score magnitude, Hurst exponent, and R:R shape. OU reversion signals scoring below 4 are discarded.

**Regime context.** Daily closes against their 20 and 50 EMAs classify each day as bull, bear, or chop, and models consume that alongside previous-day high/low levels.

**Funded-account rules** (from `config.py` and `backtest/funded_sim.py`, mirrored in the live executor):

- Model-tiered dollar risk: OU $2,500, PD $1,200, everything else $600, converted to contracts as `min(50, floor(risk_dollars / (risk_ticks * $0.50)))` on MNQ
- Daily dollar loss cap of $1,200: once breached, no new trades that day
- Daily win cap of 2.0R and a cooldown after 10 consecutive losses
- $3,000 trailing drawdown that locks static at a $0 floor once peak profit reaches $3,000, with 1.25x sizing above the static threshold
- Payout logic: max $2,000 per payout, 50% of balance, after 5 green days of $200 or more

**Monte Carlo validation.** `funded_sim.py` bootstraps daily P&L into 25,000 simulated evaluation and funded runs to estimate pass rates, blow-up risk, and payout extraction. `sim_topstep50k.py` does the same against the exact TopStep 50K Combine ruleset ($3K target, $2K trailing DD, $1K daily loss limit, 50% consistency rule, contract scaling plan). Backtest trade logs and the charts built from them are committed in this repo (`trades_*.csv`, `chart_*.png`).

**Live execution.** `executor_multi.py` polls TopStepX for fresh bars, regenerates signals with the same `MultiModelGenerator`, places a limit entry with a 60-second timeout, brackets it with stop and target orders, then manages breakeven and trailing by modifying the live stop. Ctrl+C flattens everything and exits cleanly.

## Quickstart

```bash
git clone https://github.com/s-k-28/nq-es-trader-2.git
cd nq-es-trader-2
pip install -r requirements.txt
```

**Backtest** the full ensemble on committed 1-minute NQ data (2022-2025):

```bash
python run_multi.py --nq data/Dataset_NQ_1min_2022_2025.csv
python run_multi.py --nq data/mnq_2026_1min.csv   # 2026 MNQ, auto-prepends history for regime warmup
```

**Simulate** the funded account and payout cadence:

```bash
python sim_topstep50k.py          # TopStep 50K Combine Monte Carlo on trades_current.csv
python show_daily.py              # day-by-day eval walkthrough
python show_payout_timeline.py    # 3-month payout cadence simulation
```

**Dashboard**:

```bash
python frontend/server.py         # serves trades + charts at http://localhost:8080
```

**Go live** (demo first):

```bash
cp .env.example .env              # fill in TOPSTEP_USER, TOPSTEP_API_KEY, TOPSTEP_ENV
python run_live.py --env demo
python run_live.py --env live
```

Non-technical launch: `start_bot.command` (macOS) or `start_bot.bat` (Windows) double-click launchers, with a step-by-step guide in `SETUP_MAC.md`.

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Data and math | pandas, NumPy |
| Charts | Matplotlib |
| Reports | tabulate |
| Broker API | TopStepX REST (ProjectX order API) via requests |
| Config | python-dotenv, dataclass-based `Config` |
| Data sources | Committed CSVs, yfinance fetcher, TopStepX history endpoint |
| Dashboard | Stdlib `http.server` + static HTML/JS |

## Project structure

```
nq-es-trader-2/
├── config.py                 # instrument, sessions, risk, funded-account params
├── strategy/
│   ├── multi.py              # 9-model orchestrator: cutoff, conflicts, quality gate
│   ├── quality.py            # composite 0-12 signal scoring
│   ├── vwap.py               # session VWAP + bands, opening range
│   ├── quant/features.py     # OU process, Hurst, Kalman, Parkinson vol, BB squeeze
│   └── models/               # base.py + 9 models (ou, pd, vwap, or, ema,
│                             #   sweep, kalman, trend, pm momentum)
├── backtest/
│   ├── engine_v2.py          # bar-by-bar simulator with funded-account limits
│   ├── funded_sim.py         # trailing DD, payouts, 25k-run Monte Carlo
│   └── metrics_v2.py         # performance reports and plots
├── live/
│   ├── broker_topstep.py     # TopStepX REST client (auth, bars, brackets)
│   └── executor_multi.py     # live loop mirroring backtest sizing and exits
├── data/                     # loader.py + NQ/ES/MNQ CSVs (1m/2m/5m/daily, 2022-2026)
├── frontend/                 # server.py + dashboard HTML
├── run_multi.py              # backtest CLI
├── run_live.py               # live trading CLI
├── sim_topstep50k.py         # TopStep 50K Combine simulator
├── sweep_permodel.py         # per-model parameter sweeps
├── show_daily.py / show_payout_timeline.py / diagnose.py / generate_charts.py
├── trades_*.csv              # committed backtest trade logs
└── chart_*.png               # committed equity, Monte Carlo, and timing charts
```

## Lineage

This repo is an earlier generation of the NQ ensemble trader: generation 2 of the line. It is where the project grew from a single strategy into a nine-model ensemble with per-model risk profiles, a statistical quality gate, and funded-account Monte Carlo baked directly into the research loop. The line continues in [nq-es-trader-5k-payout](https://github.com/s-k-28/nq-es-trader-5k-payout), which carries this architecture forward toward real payout milestones.

## Disclaimer

This project is for education and research. Futures trading involves substantial risk of loss and is not suitable for everyone; leveraged instruments like NQ and MNQ can lose more than the intended risk per trade, and funded-account programs have their own rules and failure modes. Backtest results committed in this repo do not guarantee future performance. Nothing here is investment advice. Trade at your own risk.
