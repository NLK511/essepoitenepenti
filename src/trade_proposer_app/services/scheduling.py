from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAY_OF_WEEK_ALIASES: dict[str, int] = {
    "SUN": 0,
    "SUNDAY": 0,
    "MON": 1,
    "MONDAY": 1,
    "TUE": 2,
    "TUES": 2,
    "TUESDAY": 2,
    "WED": 3,
    "WEDNESDAY": 3,
    "THU": 4,
    "THUR": 4,
    "THURSDAY": 4,
    "FRI": 5,
    "FRIDAY": 5,
    "SAT": 6,
    "SATURDAY": 6,
}

MONTH_ALIASES: dict[str, int] = {
    "JAN": 1,
    "JANUARY": 1,
    "FEB": 2,
    "FEBRUARY": 2,
    "MAR": 3,
    "MARCH": 3,
    "APR": 4,
    "APRIL": 4,
    "MAY": 5,
    "JUN": 6,
    "JUNE": 6,
    "JUL": 7,
    "JULY": 7,
    "AUG": 8,
    "AUGUST": 8,
    "SEP": 9,
    "SEPT": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVEMBER": 11,
    "DEC": 12,
    "DECEMBER": 12,
}


class ScheduleParseError(ValueError):
    pass


class CronFieldMatcher:
    def __init__(
        self,
        expression: str,
        minimum: int,
        maximum: int,
        aliases: dict[str, int] | None = None,
    ) -> None:
        self.expression = expression.strip()
        self.minimum = minimum
        self.maximum = maximum
        self.aliases = {key.upper(): value for key, value in (aliases or {}).items()}
        self._values = self._parse_values()

    def matches(self, value: int) -> bool:
        return value in self._values

    def _parse_values(self) -> set[int]:
        expression = self.expression
        if expression == "*":
            return set(range(self.minimum, self.maximum + 1))
        if expression.startswith("*/"):
            step = int(expression[2:])
            if step <= 0:
                raise ScheduleParseError(f"invalid step value: {expression}")
            return set(range(self.minimum, self.maximum + 1, step))
        values: set[int] = set()
        for part in expression.split(","):
            token = part.strip()
            if not token:
                raise ScheduleParseError(f"invalid empty cron field in: {expression}")
            self._add_token_values(token, values)
        return values

    def _add_token_values(self, token: str, values: set[int]) -> None:
        if "-" in token:
            start_token, end_token = token.split("-", 1)
            start_value = self._parse_single_value(start_token)
            end_value = self._parse_single_value(end_token)
            if start_value > end_value:
                raise ScheduleParseError(f"cron range {token} must specify ascending values")
            for value in range(start_value, end_value + 1):
                values.add(value)
            return
        values.add(self._parse_single_value(token))

    def _parse_single_value(self, token: str) -> int:
        cleaned = token.strip()
        if not cleaned:
            raise ScheduleParseError(f"invalid empty cron field in: {self.expression}")
        normalized = cleaned.upper()
        if normalized in self.aliases:
            value = self.aliases[normalized]
        else:
            try:
                value = int(normalized)
            except ValueError as exc:
                raise ScheduleParseError(f"invalid cron value '{token}' in: {self.expression}") from exc
        if value < self.minimum or value > self.maximum:
            raise ScheduleParseError(
                f"cron value {value} outside allowed range {self.minimum}-{self.maximum}"
            )
        return value


class CronSchedule:
    def __init__(self, expression: str) -> None:
        parts = expression.split()
        if len(parts) != 5:
            raise ScheduleParseError("cron expression must have exactly 5 fields")
        self.expression = expression
        self.minute = CronFieldMatcher(parts[0], 0, 59)
        self.hour = CronFieldMatcher(parts[1], 0, 23)
        self.day_of_month = CronFieldMatcher(parts[2], 1, 31)
        self.month = CronFieldMatcher(parts[3], 1, 12, aliases=MONTH_ALIASES)
        self.day_of_week = CronFieldMatcher(parts[4], 0, 6, aliases=DAY_OF_WEEK_ALIASES)

    def matches(self, moment: datetime) -> bool:
        return self._matches_fields(normalize_schedule_time(moment))

    def matches_in_timezone(self, moment: datetime, timezone_name: str) -> bool:
        return self._matches_fields(normalize_schedule_time_in_timezone(moment, timezone_name))

    def latest_due_at(self, now: datetime, lookback_minutes: int = 366 * 24 * 60) -> datetime | None:
        candidate = normalize_schedule_time(now)
        for _ in range(lookback_minutes + 1):
            if self._matches_fields(candidate):
                return candidate
            candidate -= timedelta(minutes=1)
        return None

    def latest_due_at_in_timezone(
        self,
        now: datetime,
        timezone_name: str,
        lookback_minutes: int = 366 * 24 * 60,
    ) -> datetime | None:
        candidate = normalize_schedule_time_in_timezone(now, timezone_name)
        for _ in range(lookback_minutes + 1):
            if self._matches_fields(candidate):
                return candidate.astimezone(timezone.utc)
            candidate -= timedelta(minutes=1)
        return None

    def _matches_fields(self, normalized: datetime) -> bool:
        cron_day_of_week = (normalized.weekday() + 1) % 7
        return (
            self.minute.matches(normalized.minute)
            and self.hour.matches(normalized.hour)
            and self.day_of_month.matches(normalized.day)
            and self.month.matches(normalized.month)
            and self.day_of_week.matches(cron_day_of_week)
        )


def normalize_schedule_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)


def normalize_schedule_time_in_timezone(value: datetime, timezone_name: str) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleParseError(f"unknown timezone: {timezone_name}") from exc
    return value.astimezone(zone).replace(second=0, microsecond=0)


def latest_due_at(expression: str, now: datetime) -> datetime | None:
    return CronSchedule(expression).latest_due_at(now)


def latest_due_at_in_timezone(expression: str, now: datetime, timezone_name: str) -> datetime | None:
    return CronSchedule(expression).latest_due_at_in_timezone(now, timezone_name)
