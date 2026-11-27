from dataclasses import dataclass


@dataclass(frozen=True)
class StateDurationStats:
    """Хранит отдельные распределения времени для состояний задач."""

    time_ranges: tuple[str, ...]
    state_names: tuple[str, ...]
    task_counts: tuple[tuple[int, ...], ...]
    analyzed_tasks: int
