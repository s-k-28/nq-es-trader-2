# NQ-ES Trader - TopStepX 100K Funded Account

Autonomous MNQ futures trading system for TopStepX 100K funded accounts. Runs 9 quantitative models with model-tiered risk sizing, funded account simulation, and Monte Carlo payout analysis. Backtest and live execution use identical config -- what you see in the charts is what runs on your account.

**P($10K in 60 days) = 89% | Walk-forward validated across 2023-2026**

## Results

### Equity Curve & Drawdown
![Equity Curve](chart_equity_drawdown.png)

### Per-Model Performance
![Model Breakdown](chart_model_breakdown.png)

### Monthly & Yearly Performance
![Monthly Yearly](chart_monthly_yearly.png)

### Monte Carlo Funded Simulation (25,000 sims)
![Monte Carlo](chart_funded_mc.png)

### Timing & Distribution Analysis
![Timing Analysis](chart_timing_analysis.png)

### Walk-Forward Validation
![Walk Forward](chart_walkforward.png)

## Backtest Summary

| Metric | Value |
|--------|-------|
| Total Trades | 2,468 |
| Trading Days | 789 |
| Trades/Day | 3.1 |
| Win Rate | 40.9% |
| Profit Factor | 1.89 |
| Expectancy | +0.36R per trade |
| Total R | +887R |
| Avg Win | +1.87R |
| Avg Loss | -0.69R |
| Survival Rate (MC) | 92.9% |
| P($10K+ in 60d) | 89.0% |
| Avg Extraction | $12,872 |
| Median Extraction | $14,000 |

### Per-Year Walk-Forward

| Year | P($10K) | Survival | Avg Extraction |
|------|---------|----------|----------------|
| 2023 | 84.8% | 85.6% | $11,979 |
| 2024 | 84.4% | 84.7% | $12,177 |
| 2025 | 91.1% | 91.1% | $13,680 |
| 2026 | 96.0% | 96.2% | $13,441 |

### Per-Model Breakdown

| Model | Trades | WR | Expectancy | Total R |
|-------|--------|----|------------|---------|
| ou_rev | 424 | 47% | +0.576R | +244.0R |
| vwap_rev | 246 | 39% | +0.618R | +152.1R |
| or_rev | 270 | 38% | +0.402R | +108.7R |
| trend | 334 | 45% | +0.278R | +92.8R |
| kalman_mom | 446 | 34% | +0.197R | +87.8R |
| pm_mom | 390 | 41% | +0.224R | +87.2R |
| ema_rev | 231 | 38% | +0.287R | +66.4R |
| pd_rev | 88 | 51% | +0.478R | +42.0R |
| sweep | 39 | 41% | +0.160R | +6.2R |

## Strategy

### 9-Model Architecture

1. **OU Reversion** - Ornstein-Uhlenbeck mean-reversion on price-VWAP deviation. Fits a stochastic process to measure how fast price reverts to VWAP, only trades when half-life is short and Hurst confirms mean-reverting regime. Quality-filtered (Q>=4). $2,500 risk allocation.
2. **PD Level Reversion** - Fades at previous day high/low with reversal candle confirmation. Institutional reference levels where large orders cluster. $1,200 risk allocation.
3. **VWAP Reversion** - Bidirectional VWAP z-score fade (z > 2.0 short, z < -2.0 long). Targets snap-back to session VWAP.
4. **Opening Range Reversion** - Fades extended moves beyond the first 15 minutes of RTH back to OR midpoint. Window: 10:00-12:00 ET.
5. **EMA Reversion** - Fades when price extends 2.5+ standard deviations from the 20-period EMA. Window: 9:50-14:30 ET.
6. **Sweep Reversal** - Liquidity sweep at PDH/PDL/session extremes followed by immediate reversal. Detects stop hunts. Both long and short.
7. **Kalman Momentum** - Trades in direction of Kalman filter slope when Hurst >= 0.5 confirms trending regime. Requires 5-bar slope consistency. Window: 10:15-14:00 ET.
8. **Trend Continuation** - Follows EMA/regime trends with fair value gap (FVG) pullback entries.
9. **Afternoon Momentum** - PM session Kalman slope pullback model (13:30-15:00 ET).

### Quantitative Features

All computed in `strategy/quant/features.py`:

- **Ornstein-Uhlenbeck process**: Rolling OLS on price-VWAP deviation to estimate mean-reversion speed (theta), half-life, and z-score. Window: 60 bars.
- **Hurst exponent**: Variance-ratio method (16-bar vs 1-bar returns) for regime classification. H < 0.45 = mean-reverting, H > 0.55 = trending. Window: 120 bars.
- **Kalman filter**: 2x2 state-space model estimating level + slope. Inline matrix math for speed on 1M+ bars.
- **Parkinson volatility**: High-low range estimator, more statistically efficient than close-to-close. Window: 30 bars.
- **Bollinger Band squeeze**: BBW percentile for volatility expansion detection. Window: 20 bars, 120-bar lookback.

### Signal Flow

```
1-min bars --> compute_vwap() + compute_opening_range()
          --> compute_all_quant_features() (OU, Hurst, Kalman, Parkinson, BB)
          --> 9 models generate signals independently
          --> filter: cut off after 2:30 PM ET
          --> resolve conflicts: 5-bar cooldown, priority-based (lower # wins)
          --> quality filter: OU needs Q>=4, all others pass through
          --> engine: simulate trades with BE/trail/time-stop
```

### Exit Mechanics

All models use the same optimized exit profile:

| Parameter | Value | What it does |
|-----------|-------|--------------|
| pp (partial pct) | 0.0 | No partial profit-taking. Lets winners run to full target or trail exit. This single change took P($10K) from 7.7% to 40.5%. |
| tp (trail pct) | 0.001 | Once MFE >= partial_rr (0.5R), a trailing stop activates 0.1% of risk behind the maximum favorable excursion. Target is disabled -- the trail IS the exit. |
| be (breakeven) | 0.6R | Move stop to entry price once trade moves 0.6x the risk in your favor. Trade becomes risk-free. |
| Time stop | 30-45 min | Close at market if trade hasn't hit breakeven within the model's time limit. |
| Session close | 4:59 PM ET | Flatten everything. No overnight positions. |

### Daily Controls

| Control | Value | What it does |
|---------|-------|--------------|
| Daily win cap | 2.0R | Stop taking new signals once daily R total reaches +2.0. Protects a good day. |
| Max daily loss R | No limit (999) | Allows intraday recovery. A -1R first trade can be followed by a +3R winner. |
| Dollar loss cap | $1,200 | Daily P&L truncated at -$1,200. Hard protection. |
| Consec cooldown | 10 | After 10 straight losing trades, skip the next signal. Circuit breaker. |
| Max concurrent | 1 | One trade at a time. No overlapping positions. |

### Risk Sizing

Model-tiered dollar risk allocation per trade:

| Tier | Models | Risk per trade | Why |
|------|--------|----------------|-----|
| High | ou_rev | $2,500 | Highest edge (47% WR, +0.576R exp), quality-filtered |
| Medium | pd_rev | $1,200 | High WR (51%), strong at key institutional levels |
| Standard | All other 7 models | $600 | Diversified coverage across market conditions |

Contracts per trade: `min(50, floor(risk_dollars / (risk_ticks * $0.50)))`

Example: OU signal with 40 ticks risk = floor($2,500 / (40 * $0.50)) = 125, capped at 50 MNQ.
Example: Kalman signal with 30 ticks risk = floor($600 / (30 * $0.50)) = 40 MNQ.

## Funded Account Rules (TopStepX 100K XFA)

| Rule | Value |
|------|-------|
| Starting balance | $100,000 |
| Trailing drawdown | $3,000 (trails upward with profit) |
| Static floor | Locks at starting balance ($0 P&L) when peak profit >= $3,000 |
| Dollar loss cap | $1,200/day (daily P&L truncated) |
| Max payout | $2,000 per withdrawal |
| Payout cap | 50% of current account balance |
| Green day minimum | $200 profit |
| Green days per payout | 5 green days to unlock a withdrawal |
| Post-static scaling | 1.25x P&L when balance > $3K above start |

### How payouts work

1. Trade until peak profit hits $3K -- drawdown floor locks (static phase)
2. Every 5 green days ($200+), withdraw min($2,000, 50% of balance)
3. Keep trading and withdrawing. Balance fluctuates but floor is locked at $0
4. Monte Carlo: 89% of 25K simulations extract $10K+ in 60 trading days

## Quick Start

### 1. Install Python 3.10+

- **Mac**: `brew install python` or download from [python.org](https://www.python.org/downloads/)
- **Windows**: Download from [python.org](https://www.python.org/downloads/) (check "Add to PATH")

### 2. Clone and install

```bash
git clone https://github.com/s-k-28/nq-es-trader-2.git
cd nq-es-trader-2
pip install -r requirements.txt
```

### 3. Run backtest with charts

```bash
python generate_charts.py
```

Generates 6 chart PNGs and prints full backtest summary with per-model breakdown.

### 4. Launch interactive dashboard

```bash
python frontend/server.py
```

Open [http://localhost:8080](http://localhost:8080) in your browser. 4 tabs:
- **Interactive Charts** - Equity curve, per-model equity, monthly P&L, win rates, R distribution, DOW/hour analysis. Filter by period and toggle models on/off.
- **Deep Analysis** - Pre-rendered matplotlib charts (equity/drawdown, model breakdown, monthly heatmap, timing, walk-forward)
- **Monte Carlo** - Funded account simulation results and probability outcomes
- **Strategy Rules** - Complete configuration reference

### 5. Run live bot (TopStepX)

```bash
cp .env.example .env
# Edit .env with your TopStepX credentials
python run_live.py
```

The bot connects to TopStepX via REST API, loads ~83 days of 1-min history for regime warmup, then trades all 9 models autonomously. Same config as the backtest -- model-tiered risk, 2.0R win cap, $1,200 DLC, BE at 0.6R, 0.001 trail, no partials.

```
TOPSTEP_USER=your_topstep_username
TOPSTEP_API_KEY=your_api_key
TOPSTEP_ENV=demo
```

Get your API key from: TopStepX dashboard > API Access.

Use `--env live` when you're ready for real money. Press `Ctrl+C` to stop and flatten all positions.

### 6. Run backtest on custom data

```bash
python run_multi.py --nq data/Dataset_NQ_1min_2022_2025.csv
python run_multi.py --nq data/mnq_2026_1min.csv --history data/Dataset_NQ_1min_2022_2025.csv
```

## Project Structure

```
nq-es-trader/
  config.py                    # All strategy parameters and funded account rules
  generate_charts.py           # Full backtest + 6-chart equity curve dashboard
  run_live.py                  # Live bot entry point (TopStepX 100K, 9 models)
  run_multi.py                 # Backtest runner with per-model reporting
  strategy/
    models/
      base.py                  # BaseModel, Signal, ModelRiskProfile dataclasses
      ou_reversion.py          # OU mean-reversion (pri=15, $2,500)
      pd_level_reversion.py    # Previous day level fade (pri=22, $1,200)
      vwap_reversion.py        # VWAP z-score reversion, long + short (pri=25)
      or_reversion.py          # Opening range reversion (pri=28)
      ema_reversion.py         # EMA mean-reversion (pri=30)
      sweep_reversal.py        # Liquidity sweep reversal, both sides (pri=35)
      kalman_momentum.py       # Kalman filter momentum (pri=40)
      trend_cont.py            # Trend continuation with FVG (pri=40)
      afternoon_momentum.py    # PM session momentum (pri=50)
      __init__.py              # ALL_MODELS registry (9 models)
    multi.py                   # Signal orchestrator: generate, filter, resolve conflicts
    quality.py                 # OU quality scoring (Q>=4 filter, other models bypass)
    quant/
      features.py              # OU, Hurst, Kalman, Parkinson, BB squeeze
    vwap.py                    # Session VWAP + 15-min opening range computation
  backtest/
    engine_v2.py               # Backtester: trail, BE, partials, time stops, win cap
    funded_sim.py              # Monte Carlo funded account simulator
    metrics_v2.py              # Trade metrics, per-model breakdown, funded projections
  data/
    loader.py                  # CSV loader, 2-min resampler, daily bar builder
    Dataset_NQ_1min_2022_2025.csv  # NQ 1-min data (2022-2025)
    mnq_2026_1min.csv          # MNQ 1-min data (2026)
  live/
    broker_topstep.py          # TopStepX REST API: auth, orders, positions, bars
    executor_multi.py          # Live executor: model-tiered sizing, same config as backtest
  frontend/
    index.html                 # Interactive dashboard (4 tabs, Chart.js)
    server.py                  # Dashboard server (trade API + chart images)
```
