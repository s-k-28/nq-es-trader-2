# NQ-ES Trader - TopStepX 100K Funded Account

Autonomous MNQ futures trading system for TopStepX 100K funded accounts. Runs 9 quantitative models with model-tiered risk sizing, funded account simulation, and Monte Carlo payout analysis.

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

1. **OU Reversion** - Ornstein-Uhlenbeck mean-reversion on price-VWAP deviation. Quality-filtered (Q>=4). $2,500 risk allocation.
2. **PD Level Reversion** - Fades at previous day high/low with reversal confirmation. $1,200 risk allocation.
3. **VWAP Reversion** - Bidirectional VWAP z-score fade (z > 2.0 short, z < -2.0 long).
4. **Opening Range Reversion** - Fades extended moves beyond 15-min opening range back to OR midpoint.
5. **EMA Reversion** - Fades extended moves beyond 20-EMA using z-score threshold.
6. **Sweep Reversal** - Liquidity sweep at PDH/PDL/session extremes with MSS confirmation. Both long and short.
7. **Kalman Momentum** - Trades Kalman filter slope direction in trending regime (Hurst >= 0.5).
8. **Trend Continuation** - Follows EMA/regime trends with FVG pullback entries.
9. **Afternoon Momentum** - PM session Kalman slope pullback model (13:30-15:00).

### Quantitative Features

- **Ornstein-Uhlenbeck process**: half-life, theta, z-score for mean-reversion timing
- **Hurst exponent**: variance-ratio method for regime classification (H < 0.45 = mean-reverting, H > 0.55 = trending)
- **Kalman filter**: recursive level + slope estimation with 2x2 state-space model
- **Parkinson volatility**: high-low range estimator (more efficient than close-to-close)
- **Bollinger Band squeeze**: BBW percentile for volatility expansion detection

### Exit Mechanics

All models use the same optimized exit profile:

| Parameter | Value | Description |
|-----------|-------|-------------|
| pp (partial pct) | 0.0 | No partial profit-taking -- lets winners run |
| tp (trail pct) | 0.001 | Ultra-tight 0.1% trail behind MFE |
| be (breakeven) | 0.6R | Move stop to breakeven at 0.6R |
| Daily win cap | 2.0R | Stop adding trades when daily R >= 2.0 |
| Consec cooldown | 10 | Skip after 10 consecutive losses |
| Max daily loss R | No limit | Allows intraday recovery |

### Risk Sizing

Model-tiered dollar risk allocation per trade:

| Tier | Models | $ Risk |
|------|--------|--------|
| High | ou_rev | $2,500 |
| Medium | pd_rev | $1,200 |
| Standard | vwap_rev, ema_rev, kalman_mom, pm_mom, sweep, trend, or_rev | $600 |

Contracts per trade: `min(50, floor(risk_dollars / (risk_ticks * $0.50)))`

## Funded Account Rules (TopStepX 100K XFA)

| Rule | Value |
|------|-------|
| Starting balance | $100,000 |
| Trailing drawdown | $3,000 (trails with profit, locks at $0 floor when peak >= $3K) |
| Dollar loss cap | $1,200/day (daily P&L truncated at -$1,200) |
| Max payout | $2,000 per withdrawal |
| Payout cap | 50% of account balance |
| Green day minimum | $200 |
| Green days per payout | 5 |
| Post-static scaling | 1.25x above $3K balance |

## Quick Start

### 1. Install Python 3.10+

- **Mac**: `brew install python` or download from [python.org](https://www.python.org/downloads/)
- **Windows**: Download from [python.org](https://www.python.org/downloads/) (check "Add to PATH")

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up credentials

```bash
cp .env.example .env
```

Edit `.env` with your TopStepX credentials:
```
TOPSTEP_USER=your_topstep_username
TOPSTEP_API_KEY=your_api_key
TOPSTEP_ENV=demo
CONTRACTS=20
```

### 4. Run backtest with charts

```bash
python generate_charts.py
```

Generates 6 detailed chart PNGs and prints full backtest summary.

### 5. Run live bot

**Mac**: Double-click `start_bot.command`

**Windows**: Double-click `start_bot.bat`

**Or from terminal**:
```bash
python run_live.py
```

Press `Ctrl+C` to stop and flatten all positions.

## Project Structure

```
nq-es-trader/
  config.py                    # All strategy parameters and funded account rules
  generate_charts.py           # Full backtest + 6-chart equity curve dashboard
  strategy/
    models/
      base.py                  # BaseModel, Signal, ModelRiskProfile dataclasses
      ou_reversion.py          # OU mean-reversion model
      pd_level_reversion.py    # Previous day level fade
      vwap_reversion.py        # VWAP z-score reversion (long + short)
      or_reversion.py          # Opening range reversion
      ema_reversion.py         # EMA mean-reversion
      sweep_reversal.py        # Liquidity sweep reversal (both sides)
      kalman_momentum.py       # Kalman filter momentum
      trend_cont.py            # Trend continuation with FVG
      afternoon_momentum.py    # PM session momentum
    multi.py                   # Signal orchestrator (generate, filter, resolve)
    quality.py                 # OU quality scoring (Q>=4 filter)
    quant/
      features.py              # OU, Hurst, Kalman, Parkinson, BB squeeze
    vwap.py                    # Session VWAP + opening range computation
  backtest/
    engine_v2.py               # Backtester with trail, BE, partials, time stops
    funded_sim.py              # Funded account MC simulator (trades -> daily $ -> payouts)
    metrics_v2.py              # Trade metrics and reporting
  data/
    loader.py                  # CSV loader, resampler, daily bar builder
  live/
    broker_topstep.py          # TopStepX API integration
    executor_multi.py          # Live multi-model executor
  run_live.py                  # Single-model live runner
  run_multi.py                 # Multi-model live runner
```
