from datetime import datetime, timedelta, timezone


class ScheduleParseError(ValueError):
    pass


class CronFieldMatcher:
    def __init__(self, expression: str, minimum: int, maximum: int) -> None:
        self.expression = expression.strip()
        self.minimum = minimum
        self.maximum = maximum
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
            item = part.strip()
            if not item:
                raise ScheduleParseError(f"invalid empty cron field in: {expression}")
            value = int(item)
            if value < self.minimum or value > self.maximum:
                raise ScheduleParseError(
                    f"cron value {value} outside allowed range {self.minimum}-{self.maximum}"
                )
            values.add(value)
        return values


class CronSchedule:
    def __init__(self, expression: str) -> None:
        parts = expression.split()
        if len(parts) != 5:
            raise ScheduleParseError("cron expression must have exactly 5 fields")
        self.expression = expression
        self.minute = CronFieldMatcher(parts[0], 0, 59)
        self.hour = CronFieldMatcher(parts[1], 0, 23)
        self.day_of_month = CronFieldMatcher(parts[2], 1, 31)
        self.month = CronFieldMatcher(parts[3], 1, 12)
        self.day_of_week = CronFieldMatcher(parts[4], 0, 6)

    def matches(self, moment: datetime) -> bool:
        normalized = normalize_schedule_time(moment)
        cron_day_of_week = (normalized.weekday() + 1) % 7
        return (
            self.minute.matches(normalized.minute)
            and self.hour.matches(normalized.hour)
            and self.day_of_month.matches(normalized.day)
            and self.month.matches(normalized.month)
            and self.day_of_week.matches(cron_day_of_week)
        )

    def latest_due_at(self, now: datetime, lookback_minutes: int = 366 * 24 * 60) -> datetime | None:
        candidate = normalize_schedule_time(now)
        for _ in range(lookback_minutes + 1):
            if self.matches(candidate):
                return candidate
            candidate -= timedelta(minutes=1)
        return None


def normalize_schedule_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)


def latest_due_at(expression: str, now: datetime) -> datetime | None:
    return CronSchedule(expression).latest_due_at(now)
