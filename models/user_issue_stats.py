from dataclasses import dataclass


@dataclass(frozen=True)
class UserIssueStats:
    """Хранит количества задач пользователей в ролях исполнителя и репортёра."""

    names: tuple[str, ...]
    assigned: tuple[int, ...]
    reported: tuple[int, ...]

    @property
    def totals(self) -> tuple[int, ...]:
        return tuple(
            assigned + reported
            for assigned, reported in zip(self.assigned, self.reported)
        )
