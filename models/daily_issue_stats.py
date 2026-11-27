from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyIssueStats:
    """Хранит дневные и накопительные количества созданных и закрытых задач."""

    dates: tuple[date, ...]
    created: tuple[int, ...]
    closed: tuple[int, ...]
    created_cumulative: tuple[int, ...]
    closed_cumulative: tuple[int, ...]

    @property
    def period_start(self) -> date:
        return self.dates[0]

    @property
    def period_end(self) -> date:
        return self.dates[-1]
