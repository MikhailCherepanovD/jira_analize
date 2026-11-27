from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class StatisticsLoader(QObject):
    """Выполняет загрузку статистики вне основного потока интерфейса."""

    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, load: Callable[[], object]) -> None:
        super().__init__()
        self._load = load

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.loaded.emit(self._load())
        except Exception as error:
            self.failed.emit(str(error))
