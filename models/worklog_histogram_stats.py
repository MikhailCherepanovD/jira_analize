from dataclasses import dataclass


@dataclass(frozen=True)
class WorklogHistogramStats:
    """Хранит распределение worklog и рейтинг пользователей по часам."""

    time_ranges: tuple[str, ...]
    task_counts: tuple[int, ...]
    user_names: tuple[str, ...]
    user_hours: tuple[float, ...]

    @property
    def user_count(self) -> int:
        return len(self.user_names)

    @property
    def task_count(self) -> int:
        return sum(self.task_counts)
