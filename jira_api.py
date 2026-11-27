from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from itertools import accumulate
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from jira_api_error import JiraApiError
from models import (
    DailyIssueStats,
    LifecycleHistogramStats,
    SeverityStats,
    StateDurationStats,
    UserCounter,
    UserIssueStats,
    WorklogHistogramStats,
)


class JiraClient:
    """Загружает данные Jira и преобразует их в модели для графиков."""

    _DURATION_RANGES = (
        "< 1 дня",
        "1–3 дня",
        "3–7 дней",
        "1–4 недели",
        "1–3 месяца",
        "3–6 месяцев",
        "6–12 месяцев",
        "≥ 1 года",
    )
    _DURATION_UPPER_BOUNDS = (
        24 * 60 * 60,
        3 * 24 * 60 * 60,
        7 * 24 * 60 * 60,
        28 * 24 * 60 * 60,
        90 * 24 * 60 * 60,
        180 * 24 * 60 * 60,
        365 * 24 * 60 * 60,
        float("inf"),
    )

    def __init__(
        self,
        base_url: str = "https://issues.apache.org/jira",
        project_key: str = "KAFKA",
        timeout: float = 20.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._project_key = project_key
        self._timeout = timeout

    def get_daily_issue_stats(
        self,
        days: int = 20,
        today: date | None = None,
    ) -> DailyIssueStats:
        if days < 1:
            raise ValueError("Количество дней должно быть положительным")

        period_end = today or date.today()
        period_start = period_end - timedelta(days=days - 1)
        end_exclusive = period_end + timedelta(days=1)
        dates = tuple(period_start + timedelta(days=offset) for offset in range(days))

        created_jql = self._period_jql("created", period_start, end_exclusive)
        closed_jql = self._period_jql("resolutiondate", period_start, end_exclusive)

        created_issues = self._search(created_jql, fields=("created",))
        closed_issues = self._search(closed_jql, fields=("resolutiondate",))

        created = self._count_by_day(created_issues, "created", dates)
        closed = self._count_by_day(closed_issues, "resolutiondate", dates)

        return DailyIssueStats(
            dates=dates,
            created=created,
            closed=closed,
            created_cumulative=tuple(accumulate(created)),
            closed_cumulative=tuple(accumulate(closed)),
        )

    def get_top_user_issue_stats(self, limit: int = 30) -> UserIssueStats:
        if limit < 1:
            raise ValueError("Количество пользователей должно быть положительным")

        issues = self._search(
            f'project = "{self._project_key}" ORDER BY key ASC',
            fields=("assignee", "reporter"),
            page_size=1000,
        )
        counters: dict[str, UserCounter] = {}

        for issue in issues:
            fields = issue.get("fields") or {}
            self._add_user_role(counters, fields.get("assignee"), "assigned")
            self._add_user_role(counters, fields.get("reporter"), "reported")

        top_users = sorted(
            counters.values(),
            key=lambda user: (-user.total, user.name.casefold()),
        )[:limit]

        return UserIssueStats(
            names=tuple(user.name for user in top_users),
            assigned=tuple(user.assigned for user in top_users),
            reported=tuple(user.reported for user in top_users),
        )

    def get_worklog_histogram(self, limit: int = 30) -> WorklogHistogramStats:
        if limit < 1:
            raise ValueError("Количество пользователей должно быть положительным")

        issues = self._search(
            f'project = "{self._project_key}" '
            "AND resolution IS NOT EMPTY AND timespent > 0 ",
            fields=("key", "timespent", "worklog"),
            page_size=1000,
        )
        user_names: dict[str, str] = {}
        user_seconds: dict[str, int] = {}
        issue_user_seconds: dict[str, dict[str, int]] = {}

        for issue in issues:
            issue_key = str(issue.get("key") or "")
            if not issue_key:
                continue

            per_user = issue_user_seconds.setdefault(issue_key, {})
            for worklog in self._all_worklogs(issue):
                identity = self._user_identity(worklog.get("author"))
                seconds = worklog.get("timeSpentSeconds")
                if identity is None or not isinstance(seconds, int) or seconds <= 0:
                    continue

                user_key, display_name = identity
                user_names[user_key] = display_name
                user_seconds[user_key] = user_seconds.get(user_key, 0) + seconds
                per_user[user_key] = per_user.get(user_key, 0) + seconds

        top_user_keys = sorted(
            user_seconds,
            key=lambda key: (-user_seconds[key], user_names[key].casefold()),
        )[:limit]
        selected_users = set(top_user_keys)
        issue_seconds = [
            sum(seconds for key, seconds in per_user.items() if key in selected_users)
            for per_user in issue_user_seconds.values()
        ]
        issue_seconds = [seconds for seconds in issue_seconds if seconds > 0]

        time_ranges = (
            "< 1 ч",
            "1–4 ч",
            "4–8 ч",
            "8–24 ч",
            "1–3 дня",
            "3–7 дней",
            "1–4 недели",
            "≥ 4 недель",
        )
        upper_bounds = (
            60 * 60,
            4 * 60 * 60,
            8 * 60 * 60,
            24 * 60 * 60,
            3 * 24 * 60 * 60,
            7 * 24 * 60 * 60,
            28 * 24 * 60 * 60,
            float("inf"),
        )
        task_counts = [0] * len(time_ranges)
        for seconds in issue_seconds:
            for index, upper_bound in enumerate(upper_bounds):
                if seconds < upper_bound:
                    task_counts[index] += 1
                    break

        return WorklogHistogramStats(
            time_ranges=time_ranges,
            task_counts=tuple(task_counts),
            user_names=tuple(user_names[key] for key in top_user_keys),
            user_hours=tuple(user_seconds[key] / 3600 for key in top_user_keys),
        )

    def get_severity_stats(self) -> SeverityStats:
        issues = self._search(
            f'project = "{self._project_key}" ORDER BY priority ASC',
            fields=("priority",),
            page_size=1000,
        )
        counts: dict[tuple[int, str], int] = {}

        for issue in issues:
            fields = issue.get("fields") or {}
            priority = fields.get("priority")
            if not isinstance(priority, dict):
                key = (10_000, "Не указана")
            else:
                name = str(priority.get("name") or "Не указана")
                priority_id = priority.get("id")
                try:
                    order = int(priority_id)
                except (TypeError, ValueError):
                    order = 9_999
                key = (order, name)
            counts[key] = counts.get(key, 0) + 1

        ordered = sorted(counts.items(), key=lambda item: item[0])
        return SeverityStats(
            names=tuple(key[1] for key, _ in ordered),
            task_counts=tuple(count for _, count in ordered),
        )

    def get_lifecycle_histogram(self) -> LifecycleHistogramStats:
        issues = self._search(
            f'project = "{self._project_key}" '
            "AND resolution IS NOT EMPTY ORDER BY resolutiondate ASC",
            fields=("created", "resolutiondate"),
            page_size=1000,
        )
        durations: list[float] = []

        for issue in issues:
            fields = issue.get("fields") or {}
            created = self._parse_datetime(fields.get("created"))
            resolved = self._parse_datetime(fields.get("resolutiondate"))
            if created is not None and resolved is not None and resolved >= created:
                durations.append((resolved - created).total_seconds())

        return LifecycleHistogramStats(
            time_ranges=self._DURATION_RANGES,
            task_counts=self._duration_histogram(durations),
        )

    def get_state_duration_histograms(self) -> StateDurationStats:
        jql = (
            f'project = "{self._project_key}" '
            "AND resolution IS NOT EMPTY ORDER BY resolutiondate ASC"
        )
        fields = ("created", "resolutiondate", "status")
        page_size = 100
        first_payload = self._search_page(
            jql,
            fields,
            0,
            page_size,
            expand=("changelog",),
        )
        first_page = self._issues_from_payload(first_payload)
        total = first_payload.get("total")
        state_durations: dict[str, list[float]] = {}
        analyzed_tasks = self._collect_state_durations(first_page, state_durations)

        if isinstance(total, int) and len(first_page) < total:
            effective_size = first_payload.get("maxResults")
            if not isinstance(effective_size, int) or effective_size < 1:
                effective_size = max(len(first_page), 1)
            starts = list(range(len(first_page), total, effective_size))

            for batch_start in range(0, len(starts), 3):
                batch = starts[batch_start : batch_start + 3]
                with ThreadPoolExecutor(max_workers=3) as executor:
                    payloads = executor.map(
                        lambda start: self._search_page(
                            jql,
                            fields,
                            start,
                            page_size,
                            expand=("changelog",),
                        ),
                        batch,
                    )
                    for payload in payloads:
                        analyzed_tasks += self._collect_state_durations(
                            self._issues_from_payload(payload),
                            state_durations,
                        )

        ordered_states = sorted(
            state_durations,
            key=lambda state: (-len(state_durations[state]), state.casefold()),
        )
        return StateDurationStats(
            time_ranges=self._DURATION_RANGES,
            state_names=tuple(ordered_states),
            task_counts=tuple(
                self._duration_histogram(state_durations[state])
                for state in ordered_states
            ),
            analyzed_tasks=analyzed_tasks,
        )

    def _period_jql(
        self,
        field: str,
        period_start: date,
        end_exclusive: date,
    ) -> str:
        return (
            f'project = "{self._project_key}" '
            f'AND {field} >= "{period_start:%Y-%m-%d}" '
            f'AND {field} < "{end_exclusive:%Y-%m-%d}" '
            f"ORDER BY {field} ASC"
        )

    def _search(
        self,
        jql: str,
        fields: tuple[str, ...],
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        first_payload = self._search_page(jql, fields, 0, page_size)
        issues = self._issues_from_payload(first_payload)
        total = first_payload.get("total")

        if not isinstance(total, int) or len(issues) >= total:
            return issues

        effective_page_size = first_payload.get("maxResults")
        if not isinstance(effective_page_size, int) or effective_page_size < 1:
            effective_page_size = max(len(issues), 1)

        starts = range(len(issues), total, effective_page_size)
        with ThreadPoolExecutor(max_workers=3) as executor:
            payloads = executor.map(
                lambda start: self._search_page(
                    jql,
                    fields,
                    start,
                    page_size,
                ),
                starts,
            )
            for payload in payloads:
                issues.extend(self._issues_from_payload(payload))

        return issues

    def _search_page(
        self,
        jql: str,
        fields: tuple[str, ...],
        start_at: int,
        page_size: int,
        expand: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        query: dict[str, object] = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": page_size,
            "fields": ",".join(fields),
        }
        if expand:
            query["expand"] = ",".join(expand)
        return self._get_json("/rest/api/2/search", query)

    @staticmethod
    def _issues_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
        page = payload.get("issues")
        if not isinstance(page, list):
            raise JiraApiError("Jira вернула ответ без списка issues")
        return page

    def _get_json(self, path: str, query: dict[str, object]) -> dict[str, Any]:
        url = f"{self._base_url}{path}?{urlencode(query)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "jira-analize/0.1",
            },
        )

        payload: object | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=self._timeout) as response:
                    payload = json.load(response)
                break
            except HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                if retryable and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                details = error.read().decode("utf-8", errors="replace")
                raise JiraApiError(
                    f"Jira API вернула HTTP {error.code}: {details[:300]}"
                ) from error
            except (URLError, TimeoutError) as error:
                if attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                reason = getattr(error, "reason", error)
                raise JiraApiError(f"Jira API недоступна: {reason}") from error
            except json.JSONDecodeError as error:
                raise JiraApiError(f"Некорректный ответ Jira API: {error}") from error

        if not isinstance(payload, dict):
            raise JiraApiError("Jira вернула неожиданный формат ответа")
        return payload

    def _all_worklogs(self, issue: dict[str, Any]) -> list[dict[str, Any]]:
        fields = issue.get("fields") or {}
        worklog_data = fields.get("worklog") or {}
        worklogs = worklog_data.get("worklogs") or []
        if not isinstance(worklogs, list):
            return []

        total = worklog_data.get("total")
        if not isinstance(total, int) or len(worklogs) >= total:
            return worklogs

        issue_key = issue.get("key")
        if not issue_key:
            return worklogs

        payload = self._get_json(
            f"/rest/api/2/issue/{issue_key}/worklog",
            {"startAt": 0, "maxResults": 1000},
        )
        complete_worklogs = payload.get("worklogs")
        return complete_worklogs if isinstance(complete_worklogs, list) else worklogs

    def _collect_state_durations(
        self,
        issues: list[dict[str, Any]],
        state_durations: dict[str, list[float]],
    ) -> int:
        analyzed = 0
        for issue in issues:
            durations = self._issue_state_durations(issue)
            if not durations:
                continue
            analyzed += 1
            for state, seconds in durations.items():
                if seconds > 0:
                    state_durations.setdefault(state, []).append(seconds)
        return analyzed

    def _issue_state_durations(self, issue: dict[str, Any]) -> dict[str, float]:
        fields = issue.get("fields") or {}
        created = self._parse_datetime(fields.get("created"))
        resolved = self._parse_datetime(fields.get("resolutiondate"))
        if created is None or resolved is None or resolved < created:
            return {}

        changelog = issue.get("changelog") or {}
        histories = changelog.get("histories") or []
        transitions: list[tuple[datetime, str | None, str | None]] = []
        for history in histories:
            changed_at = self._parse_datetime(history.get("created"))
            if changed_at is None:
                continue
            for item in history.get("items") or []:
                if str(item.get("field") or "").casefold() == "status":
                    transitions.append(
                        (changed_at, item.get("fromString"), item.get("toString"))
                    )

        transitions.sort(key=lambda transition: transition[0])
        if not transitions:
            return {}
        current_state = transitions[0][1] or "Неизвестно"

        cursor = created
        durations: dict[str, float] = {}
        for changed_at, _from_state, to_state in transitions:
            if changed_at <= created:
                current_state = to_state or current_state
                continue
            if changed_at >= resolved:
                break
            durations[current_state] = durations.get(current_state, 0) + (
                changed_at - cursor
            ).total_seconds()
            cursor = changed_at
            current_state = to_state or current_state

        durations[current_state] = durations.get(current_state, 0) + (
            resolved - cursor
        ).total_seconds()
        return durations

    @classmethod
    def _duration_histogram(cls, durations: list[float]) -> tuple[int, ...]:
        counts = [0] * len(cls._DURATION_RANGES)
        for seconds in durations:
            for index, upper_bound in enumerate(cls._DURATION_UPPER_BOUNDS):
                if seconds < upper_bound:
                    counts[index] += 1
                    break
        return tuple(counts)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _count_by_day(
        issues: list[dict[str, Any]],
        field_name: str,
        dates: tuple[date, ...],
    ) -> tuple[int, ...]:
        counts = dict.fromkeys(dates, 0)

        for issue in issues:
            fields = issue.get("fields") or {}
            value = fields.get(field_name)
            if not isinstance(value, str):
                continue

            try:
                issue_date = datetime.fromisoformat(value).date()
            except ValueError:
                continue

            if issue_date in counts:
                counts[issue_date] += 1

        return tuple(counts[day] for day in dates)

    @staticmethod
    def _add_user_role(
        counters: dict[str, UserCounter],
        user: object,
        role: str,
    ) -> None:
        identity = JiraClient._user_identity(user)
        if identity is None:
            return

        user_key, display_name = identity
        counter = counters.setdefault(user_key, UserCounter(display_name))
        if role == "assigned":
            counter.assigned += 1
        else:
            counter.reported += 1

    @staticmethod
    def _user_identity(user: object) -> tuple[str, str] | None:
        if not isinstance(user, dict):
            return None

        identity = next(
            (
                str(user[field])
                for field in ("key", "accountId", "name", "displayName")
                if user.get(field)
            ),
            None,
        )
        if identity is None:
            return None

        display_name = str(user.get("displayName") or user.get("name") or identity)
        return identity, display_name
