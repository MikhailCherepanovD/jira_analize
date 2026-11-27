from dataclasses import dataclass


@dataclass
class UserCounter:
    """Накапливает внутренние счётчики ролей одного пользователя."""

    name: str
    assigned: int = 0
    reported: int = 0

    @property
    def total(self) -> int:
        return self.assigned + self.reported
