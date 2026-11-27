from dataclasses import dataclass


@dataclass(frozen=True)
class SeverityStats:
    """Хранит количество задач для каждой степени серьёзности."""

    names: tuple[str, ...]
    task_counts: tuple[int, ...]

    @property
    def task_count(self) -> int:
        return sum(self.task_counts)
