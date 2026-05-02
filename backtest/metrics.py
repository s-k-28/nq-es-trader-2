from __future__ import annotations
import pandas as pd
import numpy as np
from backtest.engine import Trade
from config import Config


class Metrics:
    def __init__(self, trades: list[Trade], cfg: Config):
        self.trades = trades
        self.cfg = cfg
        self.df = self._build()

    def _build(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        rows = []
        for t in self.trades:
            rows.append({
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'direction': t.direction,
                'entry': t.entry_price,
                'exit': t.exit_price,
                'stop': t.stop_price,
                'target': t.target_price,
                'reason': t.exit_reason,
                'risk_ticks': t.risk_ticks,
                'partial_r': t.partial_r,
                'remainder_r': t.remainder_r,
                'total_r': t.total_r,
                'moved_be': t.moved_be,
                'partial_taken': t.partial_taken,
                'sweep_level': t.setup.sweep.level_name,
            })
        return pd.DataFrame(rows)

    # ── summary ───────────────────────────────────────────────────────
    def summary(self) -> dict:
        if self.df.empty:
            return {'total_trades': 0}

        df = self.df
        w = df[df['total_r'] > 0]
        l = df[df['total_r'] <= 0]
        n = len(df)

        wr = len(w) / n
        avg_w = w['total_r'].mean() if len(w) else 0
        avg_l = l['total_r'].mean() if len(l) else 0
        exp = df['total_r'].mean()

        cum = df['total_r'].cumsum()
        peak = cum.expanding().max()
        dd = (cum - peak).min()

        risk_usd = self.cfg.account_size * self.cfg.risk.risk_per_trade_pct / 100
        pnl_usd = df['total_r'].sum() * risk_usd

        gp = w['total_r'].sum() if len(w) else 0
        gl = abs(l['total_r'].sum()) if len(l) else 1
        pf = gp / gl if gl > 0 else float('inf')

        is_loss = (df['total_r'] <= 0).astype(int)
        groups = (is_loss != is_loss.shift()).cumsum()
        max_cl = int((is_loss * is_loss.groupby(groups).cumcount().add(1)).max())

        days = max(df['entry_time'].dt.date.nunique(), 1)
        tpd = n / days
        if df['total_r'].std() > 0 and tpd > 0:
            dr = df['total_r'].mean() * tpd
            ds = df['total_r'].std() * np.sqrt(tpd)
            sharpe = (dr / ds) * np.sqrt(250)
        else:
            sharpe = 0.0

        df['month'] = pd.to_datetime(df['entry_time']).dt.to_period('M')
        monthly = df.groupby('month')['total_r'].agg(
            total_r='sum', trades='count',
            wr=lambda x: (x > 0).mean(),
        )

        return dict(
            total_trades=n, winners=len(w), losers=len(l),
            win_rate=wr, avg_win_r=avg_w, avg_loss_r=avg_l,
            expectancy_r=exp, total_r=df['total_r'].sum(),
            profit_factor=pf, sharpe=sharpe,
            max_dd_r=dd, max_consec_losses=max_cl,
            pnl_usd=pnl_usd, avg_risk_ticks=df['risk_ticks'].mean(),
            monthly=monthly,
        )

    # ── print ─────────────────────────────────────────────────────────
    def print_report(self):
        s = self.summary()
        if s['total_trades'] == 0:
            print("No trades.")
            return

        print("\n" + "=" * 60)
        print("  LIQUIDITY SWEEP REVERSAL v2 — BACKTEST")
        print("=" * 60)

        rows = [
            ['Total Trades',       s['total_trades']],
            ['Winners / Losers',   f"{s['winners']} / {s['losers']}"],
            ['Win Rate',           f"{s['win_rate']:.1%}"],
            ['Avg Win (R)',        f"{s['avg_win_r']:.2f}"],
            ['Avg Loss (R)',       f"{s['avg_loss_r']:.2f}"],
            ['Expectancy (R)',     f"{s['expectancy_r']:.3f}"],
            ['Profit Factor',      f"{s['profit_factor']:.2f}"],
            ['Sharpe',             f"{s['sharpe']:.2f}"],
            ['Total R',            f"{s['total_r']:.1f}"],
            ['Max Drawdown (R)',   f"{s['max_dd_r']:.1f}"],
            ['Max Consec Losses',  s['max_consec_losses']],
            ['Avg Risk (ticks)',   f"{s['avg_risk_ticks']:.1f}"],
            ['Total PnL ($)',      f"${s['pnl_usd']:,.0f}"],
        ]

        try:
            from tabulate import tabulate
            print(tabulate(rows, headers=['Metric', 'Value'], tablefmt='simple'))
        except ImportError:
            for r in rows:
                print(f"  {r[0]:25s}  {r[1]}")

        print("\n--- By Exit Reason ---")
        for reason, grp in self.df.groupby('reason'):
            ar = grp['total_r'].mean()
            print(f"  {reason:20s}  {len(grp):4d} trades  avg {ar:+.2f}R")

        print("\n--- By Direction ---")
        for d, grp in self.df.groupby('direction'):
            wr = (grp['total_r'] > 0).mean()
            ar = grp['total_r'].mean()
            print(f"  {d:6s}  {len(grp):4d} trades  {wr:.0%} WR  avg {ar:+.2f}R")

        print("\n--- Monthly ---")
        m = s['monthly']
        if not m.empty:
            for period, row in m.iterrows():
                print(f"  {period}  {row['total_r']:+6.1f}R  "
                      f"{int(row['trades']):3d} trades  {row['wr']:.0%} WR")

        print("=" * 60)

    # ── plot ──────────────────────────────────────────────────────────
    def plot(self, path: str | None = None):
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not installed")
            return

        fig, axes = plt.subplots(3, 1, figsize=(14, 10), tight_layout=True)

        eq = self.df['total_r'].cumsum()
        axes[0].plot(eq.values, lw=1.5)
        axes[0].set_title('Equity Curve (R)')
        axes[0].set_ylabel('Cumulative R')
        axes[0].axhline(0, color='grey', ls='--', alpha=.5)
        axes[0].grid(True, alpha=.3)

        axes[1].hist(self.df['total_r'], bins=40, edgecolor='black', alpha=.7)
        axes[1].axvline(0, color='red', ls='--')
        axes[1].set_title('R Distribution')
        axes[1].grid(True, alpha=.3)

        dd = eq - eq.expanding().max()
        axes[2].fill_between(range(len(dd)), dd.values, 0, color='red', alpha=.3)
        axes[2].set_title('Drawdown (R)')
        axes[2].grid(True, alpha=.3)

        if path:
            fig.savefig(path, dpi=150)
            print(f"Saved → {path}")
        else:
            plt.show()
        plt.close(fig)
