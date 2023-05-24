from collections import defaultdict
from datetime import datetime, time, tzinfo
from typing import Sequence

from dateutil import parser
from pydantic import BaseModel, Field, root_validator, validator
from pytz import timezone

# Config validation data models:

# TODO: validate that there are no stop\start actions of the same date type with the same timestamp in config


class HolidayEntry(BaseModel):
    start: datetime
    stop: datetime

    @validator("start", "stop", pre=True)
    def parse_datetime(cls, obj):
        if isinstance(obj, str):
            parser.parse(obj)
        return obj

    @root_validator(pre=False, skip_on_failure=True)
    def validate_start_is_after_stop(cls, field_values):
        assert field_values["stop"] < field_values["start"], (
            "Stop datetime must precede start datetime for holiday entries. "
            f"Got stop={field_values['stop']} >= start={field_values['start']} instead."
        )
        return field_values


class WeekdayEntry(BaseModel):
    days: list[int]
    start: list[time] | None = None
    stop: list[time] | None = None

    @validator("start", "stop", pre=True)
    def parse_time(cls, obj):
        if isinstance(obj, (str, int)):
            return [obj]
        return obj

    @validator("days", pre=False)
    def validate_days(cls, days):
        for day in days:
            assert 1 <= day <= 7, f"Days must be one of the following: [1,2,3,4,5,6,7], got {day} instead."
        return days


class Schedule(BaseModel):
    timezone_str: str = Field(..., alias="timezone")
    weekdays: Sequence[WeekdayEntry] = tuple()
    holidays: Sequence[HolidayEntry] = tuple()

    class Config:
        arbitrary_types_allowed = True

    @validator("timezone_str", pre=True)
    def validate_timezone(cls, timezone_str: str) -> str:
        timezone(timezone_str)
        return timezone_str

    @root_validator(pre=False, skip_on_failure=True)
    def add_timezone_awareness(cls, field_values):
        holidays: list[HolidayEntry] | None = field_values["holidays"]
        weekdays: list[WeekdayEntry] | None = field_values["weekdays"]
        tz: tzinfo = timezone(field_values["timezone_str"])
        if holidays is not None:
            for holiday in holidays:
                holiday.stop = holiday.stop.replace(tzinfo=tz)
                holiday.start = holiday.start.replace(tzinfo=tz)
        if weekdays is not None:
            for weekday in weekdays:
                if weekday.stop is not None:
                    weekday.stop = [_time.replace(tzinfo=tz) for _time in weekday.stop]
                if weekday.start is not None:
                    weekday.start = [_time.replace(tzinfo=tz) for _time in weekday.start]
        return field_values

    def __str__(self) -> str:
        # Processing weekdays
        weekday_schedule_starts = defaultdict(list)
        weekday_schedule_stops = defaultdict(list)
        for weekday_entry in self.weekdays:
            for day in weekday_entry.days:
                if weekday_entry.start is not None:
                    weekday_schedule_starts[day].extend(weekday_entry.start)
                if weekday_entry.stop is not None:
                    weekday_schedule_stops[day].extend(weekday_entry.stop)

        weekday_str_builder = []
        for day, day_str in zip(range(1, 8), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
            weekday_str_builder.append(f"{day_str}:\n")
            actions = [(_time, "start") for _time in weekday_schedule_starts[day]]
            actions.extend([(_time, "stop") for _time in weekday_schedule_stops[day]])
            weekday_str_builder.extend(
                [f"  - {time.strftime(_time, '%H:%M')}: {action_type}\n" for _time, action_type in sorted(actions)]
            )

        # Processing holidays
        date_format = "%Y-%m-%d, %H:%M"
        holiday_str_builder = [
            (
                f"[{datetime.strftime(holiday_entry.stop, date_format)}] - "
                f"[{datetime.strftime(holiday_entry.start, date_format)}]\n"
            )
            for holiday_entry in sorted(self.holidays, key=lambda holiday: holiday.stop)
        ]

        return (
            f"Timezone: {self.timezone_str}\n"
            f"Weekdays:\n"
            f"{''.join(weekday_str_builder)}"
            f"Holidays:\n"
            f"{''.join(holiday_str_builder)}"
        )


class BatchConfig(BaseModel):
    size: int
    timeout: int


class Environment(BaseModel):
    namespaces: list[str]
    schedule: str
    batch: BatchConfig | None = None

    @validator("namespaces")
    def validate_namespaces(cls, namespaces):
        assert len(namespaces) > 0, "At least one namespace must be specified in each environment."
        return namespaces


class Config(BaseModel):
    schedules: dict[str, Schedule]
    envs: dict[str, Environment]

    @validator("schedules")
    def validate_schedules(cls, schedules):
        assert len(schedules) > 0, "At least one schedule must be specified."
        return schedules

    @validator("envs")
    def validate_envs(cls, envs):
        assert len(envs) > 0, "At least one environment must be specified."
        return envs
