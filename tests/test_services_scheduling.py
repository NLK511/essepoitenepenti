import unittest
from datetime import datetime, timezone

from trade_proposer_app.services.scheduling import (
    CronFieldMatcher,
    CronSchedule,
    DAY_OF_WEEK_ALIASES,
    MONTH_ALIASES,
    latest_due_at_in_timezone,
)


class SchedulingTests(unittest.TestCase):
    def test_named_weekday_schedule_matches_weekdays_only(self) -> None:
        schedule = CronSchedule("0 14 * * MON-FRI")
        monday = datetime(2026, 3, 16, 14, 0, tzinfo=timezone.utc)
        friday = datetime(2026, 3, 13, 14, 0, tzinfo=timezone.utc)
        saturday = datetime(2026, 3, 14, 14, 0, tzinfo=timezone.utc)

        self.assertTrue(schedule.matches(monday))
        self.assertTrue(schedule.matches(friday))
        self.assertFalse(schedule.matches(saturday))

    def test_latest_due_at_from_weekend_returns_previous_weekday(self) -> None:
        schedule = CronSchedule("30 14 * * MON-FRI")
        saturday_afternoon = datetime(2026, 3, 14, 16, 45, tzinfo=timezone.utc)
        due = schedule.latest_due_at(saturday_afternoon)
        expected = datetime(2026, 3, 13, 14, 30, tzinfo=timezone.utc)
        self.assertEqual(due, expected)

    def test_month_aliases_and_ranges_are_parsed(self) -> None:
        matcher = CronFieldMatcher("Jan-Mar,6", 1, 12, aliases=MONTH_ALIASES)
        self.assertTrue(matcher.matches(1))
        self.assertTrue(matcher.matches(3))
        self.assertTrue(matcher.matches(6))
        self.assertFalse(matcher.matches(4))
        self.assertFalse(matcher.matches(12))

    def test_day_of_week_aliases_support_multiple_names(self) -> None:
        matcher = CronFieldMatcher("Mon,WED-Fri", 0, 6, aliases=DAY_OF_WEEK_ALIASES)
        self.assertTrue(matcher.matches(1))
        self.assertTrue(matcher.matches(5))
        self.assertFalse(matcher.matches(0))

    def test_latest_due_at_in_timezone_uses_local_clock(self) -> None:
        now = datetime(2026, 3, 16, 13, 20, tzinfo=timezone.utc)
        due = latest_due_at_in_timezone("20 9 * * MON-FRI", now, "America/New_York")
        self.assertEqual(due, now)

    def test_latest_due_at_in_timezone_returns_previous_matching_local_slot(self) -> None:
        now = datetime(2026, 3, 16, 13, 40, tzinfo=timezone.utc)
        due = latest_due_at_in_timezone("20 9 * * MON-FRI", now, "America/New_York")
        self.assertEqual(due, datetime(2026, 3, 16, 13, 20, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
