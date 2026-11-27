from dataclasses import dataclass


@dataclass(frozen=True)
class LifecycleHistogramStats:
    """Хранит гистограмму времени от создания задачи до её закрытия."""

    time_ranges: tuple[str, ...]
    task_counts: tuple[int, ...]

    @property
    def task_count(self) -> int:
        return sum(self.task_counts)
