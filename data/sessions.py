from __future__ import annotations
from datetime import time, datetime
from config import SessionTimes


class SessionClassifier:
    def __init__(self, sessions: SessionTimes):
        self.s = sessions

    def get_session(self, dt: datetime) -> str:
        t = dt.time()
        if self._in(t, self.s.rth_start, self.s.rth_end):
            return 'rth'
        return 'overnight'

    def is_killzone(self, dt: datetime) -> bool:
        return self.get_killzone(dt) is not None

    def get_killzone(self, dt: datetime) -> str | None:
        t = dt.time()
        if self._in(t, self.s.london_kz_start, self.s.london_kz_end):
            return 'london'
        if self._in(t, self.s.ny_am_kz_start, self.s.ny_am_kz_end):
            return 'ny_am'
        return None

    def is_friday_pm(self, dt: datetime) -> bool:
        return dt.weekday() == 4 and dt.time() >= time(13, 0)

    @staticmethod
    def _in(t: time, start: time, end: time) -> bool:
        if start <= end:
            return start <= t < end
        return t >= start or t < end
