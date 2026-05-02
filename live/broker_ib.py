"""Interactive Brokers connection via ib_insync."""
from __future__ import annotations
import pandas as pd
from config import Config
from typing import Optional

try:
    from ib_insync import IB, Future, LimitOrder, MarketOrder, StopOrder
except ImportError:
    IB = Future = LimitOrder = MarketOrder = StopOrder = None


class IBBroker:
    def __init__(self, cfg: Config, host='127.0.0.1', port=7497, client_id=1):
        if IB is None:
            raise ImportError("pip install ib_insync")
        self.cfg = cfg
        self.ib = IB()
        self.host = host
        self.port = port
        self.cid = client_id
        self._con = None
        self._es = None

    def connect(self):
        self.ib.connect(self.host, self.port, clientId=self.cid)
        sym = self.cfg.instrument.symbol
        self._con = Future(sym, exchange='CME')
        self.ib.qualifyContracts(self._con)

        if self.cfg.strategy.use_intermarket:
            es_sym = 'MES' if sym.startswith('M') else 'ES'
            self._es = Future(es_sym, exchange='CME')
            self.ib.qualifyContracts(self._es)

    def disconnect(self):
        self.ib.disconnect()

    def bars(self, duration='2 D', size='1 min', contract=None) -> pd.DataFrame:
        c = contract or self._con
        raw = self.ib.reqHistoricalData(
            c, endDateTime='', durationStr=duration,
            barSizeSetting=size, whatToShow='TRADES',
            useRTH=False, formatDate=1,
        )
        rows = [{'datetime': b.date, 'open': b.open, 'high': b.high,
                 'low': b.low, 'close': b.close, 'volume': b.volume}
                for b in raw]
        df = pd.DataFrame(rows)
        df['datetime'] = pd.to_datetime(df['datetime'])
        return df

    def es_bars(self, duration='2 D', size='1 min') -> pd.DataFrame | None:
        return self.bars(duration, size, self._es) if self._es else None

    def bracket(self, direction: str, entry: float,
                stop: float, target: float, qty: int = 1):
        action = 'BUY' if direction == 'long' else 'SELL'
        orders = self.ib.bracketOrder(action, qty, entry, target, stop)
        trades = [self.ib.placeOrder(self._con, o) for o in orders]
        return trades

    def cancel_all(self):
        self.ib.reqGlobalCancel()

    def position(self) -> int:
        for p in self.ib.positions():
            if p.contract.symbol == self._con.symbol:
                return int(p.position)
        return 0

    def flatten(self):
        pos = self.position()
        if pos == 0:
            return
        action = 'SELL' if pos > 0 else 'BUY'
        self.ib.placeOrder(self._con, MarketOrder(action, abs(pos)))

    def sleep(self, sec: float):
        self.ib.sleep(sec)
