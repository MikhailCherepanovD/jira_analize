import sys
from collections.abc import Callable

import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from PyQt6.QtCore import QThread, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jira_api import JiraClient
from models import (
    DailyIssueStats,
    LifecycleHistogramStats,
    SeverityStats,
    StateDurationStats,
    UserIssueStats,
    WorklogHistogramStats,
)
from statistics_loader import StatisticsLoader


class JiraChartWindow(QMainWindow):
    """Создаёт главное окно и отображает все шесть графиков Jira."""

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._loader: StatisticsLoader | None = None
        self._client = JiraClient(project_key="KAFKA")

        self.setWindowTitle("Статистика Apache Jira")
        self.resize(1280, 760)
        self.setMinimumSize(960, 600)
        self._build_ui()

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)

        controls = QWidget(central_widget)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        self.lifecycle_button = QPushButton("Время задачи\nв открытом состоянии")
        self.lifecycle_button.setMinimumHeight(64)
        self.lifecycle_button.clicked.connect(self.load_lifecycle_statistics)
        controls_layout.addWidget(self.lifecycle_button)

        self.states_button = QPushButton("Распределение времени\nпо состояниям")
        self.states_button.setMinimumHeight(64)
        self.states_button.clicked.connect(self.load_state_statistics)
        controls_layout.addWidget(self.states_button)

        self.load_button = QPushButton("Заведенные и закрытые\nзадачи за 20 дней")
        self.load_button.setMinimumHeight(64)
        self.load_button.clicked.connect(self.load_statistics)
        controls_layout.addWidget(self.load_button)

        self.users_button = QPushButton("Топ-30 исполнителей\nи репортёров")
        self.users_button.setMinimumHeight(64)
        self.users_button.clicked.connect(self.load_user_statistics)
        controls_layout.addWidget(self.users_button)

        self.worklog_button = QPushButton("Залогированное время\nзакрытых задач")
        self.worklog_button.setMinimumHeight(64)
        self.worklog_button.clicked.connect(self.load_worklog_statistics)
        controls_layout.addWidget(self.worklog_button)

        self.severity_button = QPushButton("Количество задач\nпо серьёзности")
        self.severity_button.setMinimumHeight(64)
        self.severity_button.clicked.connect(self.load_severity_statistics)
        controls_layout.addWidget(self.severity_button)

        controls_layout.addStretch(1)
        self.status_label = QLabel("Выберите график для загрузки данных")
        self.status_label.setWordWrap(True)
        controls_layout.addWidget(self.status_label)

        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._show_placeholder()

        root_layout.addWidget(controls, 1)
        root_layout.addWidget(self.canvas, 4)
        self.setCentralWidget(central_widget)

    def _show_placeholder(self) -> None:
        axes = self.figure.add_subplot(111)
        axes.text(
            0.5,
            0.5,
            "Здесь будет отображаться график",
            ha="center",
            va="center",
            color="#6b7280",
            fontsize=14,
            transform=axes.transAxes,
        )
        axes.set_axis_off()

    @pyqtSlot()
    def load_statistics(self) -> None:
        self._start_loading(
            lambda: self._client.get_daily_issue_stats(days=20),
            self._statistics_loaded,
            "Загрузка статистики по дням…",
        )

    @pyqtSlot()
    def load_lifecycle_statistics(self) -> None:
        self._start_loading(
            self._client.get_lifecycle_histogram,
            self._lifecycle_statistics_loaded,
            "Загрузка времени жизни закрытых задач…",
        )

    @pyqtSlot()
    def load_state_statistics(self) -> None:
        self._start_loading(
            self._client.get_state_duration_histograms,
            self._state_statistics_loaded,
            "Загрузка истории состояний закрытых задач…",
        )

    @pyqtSlot()
    def load_user_statistics(self) -> None:
        self._start_loading(
            lambda: self._client.get_top_user_issue_stats(limit=30),
            self._user_statistics_loaded,
            "Загрузка всех задач и подсчёт пользователей…",
        )

    @pyqtSlot()
    def load_worklog_statistics(self) -> None:
        self._start_loading(
            lambda: self._client.get_worklog_histogram(limit=30),
            self._worklog_statistics_loaded,
            "Загрузка worklog закрытых задач…",
        )

    @pyqtSlot()
    def load_severity_statistics(self) -> None:
        self._start_loading(
            self._client.get_severity_stats,
            self._severity_statistics_loaded,
            "Загрузка распределения задач по серьёзности…",
        )

    def _start_loading(
        self,
        load: Callable[[], object],
        on_loaded: Callable[[object], None],
        status: str,
    ) -> None:
        if self._thread is not None:
            return

        self.lifecycle_button.setEnabled(False)
        self.states_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.users_button.setEnabled(False)
        self.worklog_button.setEnabled(False)
        self.severity_button.setEnabled(False)
        self.status_label.setText(status)

        thread = QThread(self)
        loader = StatisticsLoader(load)
        loader.moveToThread(thread)
        thread.started.connect(loader.run)
        loader.loaded.connect(on_loaded)
        loader.failed.connect(self._loading_failed)
        loader.loaded.connect(thread.quit)
        loader.failed.connect(thread.quit)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._loading_finished)

        self._thread = thread
        self._loader = loader
        thread.start()

    @pyqtSlot(object)
    def _statistics_loaded(self, statistics: DailyIssueStats) -> None:
        self._draw_statistics(statistics)
        self.status_label.setText(
            f"Загружено: {statistics.period_start:%d.%m.%Y} — "
            f"{statistics.period_end:%d.%m.%Y}"
        )

    @pyqtSlot(object)
    def _lifecycle_statistics_loaded(
        self,
        statistics: LifecycleHistogramStats,
    ) -> None:
        self._draw_lifecycle_histogram(statistics)
        self.status_label.setText(
            f"Проанализировано закрытых задач: {statistics.task_count}"
        )

    @pyqtSlot(object)
    def _state_statistics_loaded(self, statistics: StateDurationStats) -> None:
        self._draw_state_duration_histograms(statistics)
        self.status_label.setText(
            f"Проанализировано задач: {statistics.analyzed_tasks}; "
            f"состояний: {len(statistics.state_names)}"
        )

    @pyqtSlot(object)
    def _user_statistics_loaded(self, statistics: UserIssueStats) -> None:
        self._draw_user_statistics(statistics)
        self.status_label.setText(
            f"Загружен топ-{len(statistics.names)} пользователей проекта KAFKA"
        )

    @pyqtSlot(object)
    def _worklog_statistics_loaded(self, statistics: WorklogHistogramStats) -> None:
        self._draw_worklog_histogram(statistics)
        self.status_label.setText(
            f"Закрытых задач с worklog: {statistics.task_count}; "
            f"пользователей: {statistics.user_count}"
        )

    @pyqtSlot(object)
    def _severity_statistics_loaded(self, statistics: SeverityStats) -> None:
        self._draw_severity_statistics(statistics)
        self.status_label.setText(
            f"Распределено задач по серьёзности: {statistics.task_count}"
        )

    @pyqtSlot(str)
    def _loading_failed(self, message: str) -> None:
        self.status_label.setText("Не удалось загрузить данные")
        QMessageBox.critical(
            self,
            "Ошибка Jira API",
            f"Не удалось получить статистику:\n\n{message}",
        )

    @pyqtSlot()
    def _loading_finished(self) -> None:
        self._thread = None
        self._loader = None
        self.lifecycle_button.setEnabled(True)
        self.states_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.users_button.setEnabled(True)
        self.worklog_button.setEnabled(True)
        self.severity_button.setEnabled(True)

    def _draw_statistics(self, statistics: DailyIssueStats) -> None:
        self.figure.clear()
        axes = self.figure.add_subplot(111)

        dates = list(statistics.dates)
        bar_width = 0.36
        date_numbers = mdates.date2num(dates)

        axes.bar(
            date_numbers - bar_width / 2,
            statistics.created,
            width=bar_width,
            color="#3b82f6",
            alpha=0.8,
            label="Заведено за день",
        )
        axes.bar(
            date_numbers + bar_width / 2,
            statistics.closed,
            width=bar_width,
            color="#ef4444",
            alpha=0.8,
            label="Закрыто за день",
        )
        axes.plot(
            dates,
            statistics.created_cumulative,
            color="#1d4ed8",
            marker="o",
            linewidth=2,
            markersize=4,
            label="Заведено, накопительный итог",
        )
        axes.plot(
            dates,
            statistics.closed_cumulative,
            color="#b91c1c",
            marker="o",
            linewidth=2,
            markersize=4,
            label="Закрыто, накопительный итог",
        )

        axes.set_title("Apache Kafka: заведенные и закрытые задачи за 20 дней")
        axes.set_xlabel("Календарный день")
        axes.set_ylabel("Количество задач")
        axes.set_xticks(dates)
        axes.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        axes.yaxis.set_major_locator(MaxNLocator(integer=True))
        axes.tick_params(axis="x", rotation=45)
        axes.grid(axis="y", linestyle="--", alpha=0.35)
        axes.legend(loc="upper left", fontsize=9)
        axes.margins(x=0.02)
        self.canvas.draw_idle()

    def _draw_lifecycle_histogram(
        self,
        statistics: LifecycleHistogramStats,
    ) -> None:
        self.figure.clear()
        axes = self.figure.add_subplot(111)

        positions = list(range(len(statistics.time_ranges)))
        bars = axes.bar(
            positions,
            statistics.task_counts,
            color="#6366f1",
            alpha=0.85,
            width=0.8,
        )
        axes.bar_label(bars, padding=4, fontsize=10)
        axes.set_title("Закрытые задачи KAFKA: время от создания до закрытия")
        axes.set_xlabel("Время в открытом состоянии")
        axes.set_ylabel("Количество задач")
        axes.set_xticks(
            positions,
            labels=statistics.time_ranges,
            rotation=30,
            ha="right",
        )
        axes.yaxis.set_major_locator(MaxNLocator(integer=True))
        axes.grid(axis="y", linestyle="--", alpha=0.35)
        axes.margins(y=0.1)
        self.canvas.draw_idle()

    def _draw_state_duration_histograms(
        self,
        statistics: StateDurationStats,
    ) -> None:
        self.figure.clear()
        state_count = len(statistics.state_names)
        if state_count == 0:
            axes = self.figure.add_subplot(111)
            axes.text(
                0.5,
                0.5,
                "Нет данных об изменениях состояний",
                ha="center",
                va="center",
                transform=axes.transAxes,
            )
            axes.set_axis_off()
            self.canvas.draw_idle()
            return

        columns = 2
        rows = (state_count + columns - 1) // columns
        axes_grid = self.figure.subplots(rows, columns, squeeze=False)
        positions = list(range(len(statistics.time_ranges)))

        for index, (state, counts) in enumerate(
            zip(statistics.state_names, statistics.task_counts)
        ):
            axes = axes_grid[index // columns][index % columns]
            axes.bar(
                positions,
                counts,
                color="#0ea5e9",
                alpha=0.85,
                width=0.8,
            )
            axes.set_title(state, fontsize=10)
            axes.set_xlabel("Время", fontsize=8)
            axes.set_ylabel("Количество задач", fontsize=8)
            axes.set_xticks(
                positions,
                labels=statistics.time_ranges,
                rotation=45,
                ha="right",
                fontsize=7,
            )
            axes.yaxis.set_major_locator(MaxNLocator(integer=True))
            axes.tick_params(axis="y", labelsize=8)
            axes.grid(axis="y", linestyle="--", alpha=0.3)

        for index in range(state_count, rows * columns):
            axes_grid[index // columns][index % columns].set_axis_off()

        self.figure.suptitle(
            "Закрытые задачи KAFKA: распределение времени по состояниям"
        )
        self.canvas.draw_idle()

    def _draw_user_statistics(self, statistics: UserIssueStats) -> None:
        self.figure.clear()
        axes = self.figure.add_subplot(111)

        positions = list(range(len(statistics.names)))
        axes.barh(
            positions,
            statistics.assigned,
            color="#3b82f6",
            alpha=0.85,
            label="Исполнитель",
        )
        axes.barh(
            positions,
            statistics.reported,
            left=statistics.assigned,
            color="#f59e0b",
            alpha=0.85,
            label="Репортёр",
        )

        maximum = max(statistics.totals, default=0)
        label_offset = max(maximum * 0.01, 1)
        for position, total in zip(positions, statistics.totals):
            axes.text(
                total + label_offset,
                position,
                str(total),
                va="center",
                fontsize=8,
            )

        axes.set_title("Apache Kafka: топ-30 пользователей по количеству задач")
        axes.set_xlabel("Количество задач")
        axes.set_ylabel("Имя пользователя")
        axes.set_yticks(positions, labels=statistics.names)
        axes.invert_yaxis()
        axes.xaxis.set_major_locator(MaxNLocator(integer=True))
        axes.tick_params(axis="y", labelsize=8)
        axes.grid(axis="x", linestyle="--", alpha=0.35)
        axes.legend(loc="lower right")
        axes.set_xlim(right=maximum + label_offset * 7 if maximum else 1)
        self.canvas.draw_idle()

    def _draw_worklog_histogram(
        self,
        statistics: WorklogHistogramStats,
    ) -> None:
        self.figure.clear()
        histogram_axes, users_axes = self.figure.subplots(
            1,
            2,
            gridspec_kw={"width_ratios": (3, 2)},
        )

        positions = list(range(len(statistics.time_ranges)))
        bars = histogram_axes.bar(
            positions,
            statistics.task_counts,
            color="#8b5cf6",
            alpha=0.85,
            width=0.8,
        )
        histogram_axes.bar_label(bars, padding=3, fontsize=9)
        histogram_axes.set_xlabel("Залогированное время на задачу")
        histogram_axes.set_ylabel("Количество задач")
        histogram_axes.set_xticks(
            positions,
            labels=statistics.time_ranges,
            rotation=35,
            ha="right",
        )
        histogram_axes.yaxis.set_major_locator(MaxNLocator(integer=True))
        histogram_axes.grid(axis="y", linestyle="--", alpha=0.35)

        user_positions = list(range(statistics.user_count))
        users_axes.barh(
            user_positions,
            statistics.user_hours,
            color="#14b8a6",
            alpha=0.85,
        )
        users_axes.set_xlabel("Залогировано, часов")
        users_axes.set_ylabel("Пользователь")
        users_axes.set_yticks(user_positions, labels=statistics.user_names)
        users_axes.invert_yaxis()
        users_axes.tick_params(axis="y", labelsize=8)
        users_axes.grid(axis="x", linestyle="--", alpha=0.35)

        self.figure.suptitle(
            "Закрытые задачи KAFKA: залогированное время "
            f"и топ-{statistics.user_count} пользователей"
        )
        self.canvas.draw_idle()

    def _draw_severity_statistics(self, statistics: SeverityStats) -> None:
        self.figure.clear()
        axes = self.figure.add_subplot(111)

        positions = list(range(len(statistics.names)))
        colors = ("#dc2626", "#f97316", "#f59e0b", "#3b82f6", "#22c55e")
        bars = axes.bar(
            positions,
            statistics.task_counts,
            color=[colors[index % len(colors)] for index in positions],
            alpha=0.85,
            width=0.7,
        )
        axes.bar_label(bars, padding=4, fontsize=10)
        axes.set_title("Apache Kafka: количество задач по степени серьёзности")
        axes.set_xlabel("Степень серьёзности (Priority)")
        axes.set_ylabel("Количество задач")
        axes.set_xticks(positions, labels=statistics.names)
        axes.yaxis.set_major_locator(MaxNLocator(integer=True))
        axes.grid(axis="y", linestyle="--", alpha=0.35)
        axes.margins(y=0.1)
        self.canvas.draw_idle()


def main() -> None:
    application = QApplication(sys.argv)
    application.setStyle("Fusion")
    window = JiraChartWindow()
    window.show()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
