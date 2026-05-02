# NQ Trading Bot - TopStepX 50K Funded Account

Autonomous MNQ futures trading bot for TopStepX funded accounts. Runs 4 models (OU Reversion, VWAP Reversion, Trend Continuation, Sweep Reversal) and manages all entries, exits, and risk automatically.

## Quick Start

### 1. Install Python 3.10+

- **Mac**: `brew install python` or download from [python.org](https://www.python.org/downloads/)
- **Windows**: Download from [python.org](https://www.python.org/downloads/) (check "Add to PATH" during install)

### 2. Install dependencies

```bash
cd nq-es-trader
pip install -r requirements.txt
```

### 3. Set up credentials

Copy the example env file and fill in your TopStepX credentials:

```bash
cp .env.example .env
```

Edit `.env` with your details:
```
TOPSTEP_USER=your_topstep_username
TOPSTEP_API_KEY=your_api_key
TOPSTEP_ENV=demo
CONTRACTS=20
```

Get your API key from: TopStepX dashboard > API Access

### 4. Run the bot

**Mac**: Double-click `start_bot.command`

**Windows**: Double-click `start_bot.bat`

**Or from terminal**:
```bash
python run_live.py
```

Press `Ctrl+C` to stop and flatten all positions.

## Funded Account Rules

| Rule | Value |
|------|-------|
| Starting balance | $50,000 |
| Trailing drawdown | $2,000 (locks at $52K) |
| Max position | 20 MNQ (2 NQ) |
| Profit split | 90/10 |
| Max payout | $2,000 per withdrawal |
| Payout eligibility | 5 winning trading days |

## Strategy

- **OU Reversion**: Mean-reversion on Ornstein-Uhlenbeck process (PF 2.12)
- **VWAP Reversion**: VWAP-based mean reversion (PF 1.58)
- **Trend Continuation**: Trend-following with momentum (PF 1.58)
- **Sweep Reversal**: Liquidity sweep reversals (PF 1.70)

Overall: 60.5% win rate, 1.73 profit factor, +$138/trade at 20 MNQ.

## Risk Management

- $1,700 drawdown protection buffer (of $2,000 max)
- 1.8R daily profit cap / 0.25R daily loss cap
- Breakeven stops, partial exits, trailing stops
- Time stops per model (30-45 min)
- Auto-flatten at 2:55 PM CT
- 2 consecutive loss cooldown
