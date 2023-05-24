# import asyncio
import datetime

# import logging
import typing
from dataclasses import dataclass

import pytest
import pytz
import yaml

# from nsscheduler import scheduler, updown
# from nsscheduler.data_models.api import NamespaceState
from nsscheduler.data_models.scheduler_config import Config
from nsscheduler.scheduler import (  # schedule_env,
    Action,
    ActionDateType,
    ActionType,
    get_actions_in_interval,
)


@dataclass
class GetActionsInIntervalTestCase:
    config: str
    starting_from: str
    until: str
    ground_truth: list[Action]


CONFIG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
CONFIG_TIME_FORMAT = "%H:%M:%S"

TEST_CONFIG = """
schedules:
  main:
    timezone: UTC
    weekdays:
      - days: [1,2,3,4]
        start: 08:00
        stop: 01:00
      - days: [5]
        stop: 01:00
      - days: [6]
        start:
          - 03:00
          - 08:00
        stop:
          - 01:00
          - 04:00
    holidays:
      - stop: 2022-12-22 23:00:00
        start: 2023-01-03 08:00:00
      - stop: 2023-01-06 23:00
        start: 2023-01-08 08:00
envs:
  dev-vasya:
    namespaces:
      - vasya-data
      - vasya-apps
    schedule: main
    batch:
      size: 4
      timeout: 30
"""

GET_ACTIONS_IN_INTERVAL_TEST_CASES = [
    GetActionsInIntervalTestCase(
        config=TEST_CONFIG,
        starting_from="2022-12-17 00:00:00",
        until="2022-12-17 05:00:00",
        ground_truth=[
            Action(
                action_type=ActionType.STOP,
                action_date_type=ActionDateType.WEEKDAY,
                datetime=datetime.datetime.strptime("2022-12-17 01:00:00", CONFIG_DATE_FORMAT),
            ),
            Action(
                action_type=ActionType.START,
                action_date_type=ActionDateType.WEEKDAY,
                datetime=datetime.datetime.strptime("2022-12-17 03:00:00", CONFIG_DATE_FORMAT),
            ),
            Action(
                action_type=ActionType.STOP,
                action_date_type=ActionDateType.WEEKDAY,
                datetime=datetime.datetime.strptime("2022-12-17 04:00:00", CONFIG_DATE_FORMAT),
            ),
        ],
    ),
    GetActionsInIntervalTestCase(
        config=TEST_CONFIG,
        starting_from="2022-12-17 00:00:00",
        until="2022-12-17 02:00:00",
        ground_truth=[
            Action(
                action_type=ActionType.STOP,
                action_date_type=ActionDateType.WEEKDAY,
                datetime=datetime.datetime.strptime("2022-12-17 01:00:00", CONFIG_DATE_FORMAT),
            )
        ],
    ),
    GetActionsInIntervalTestCase(
        config=TEST_CONFIG,
        starting_from="2022-12-22 00:00:00",
        until="2022-12-22 02:00:00",
        ground_truth=[
            Action(
                action_type=ActionType.STOP,
                action_date_type=ActionDateType.WEEKDAY,
                datetime=datetime.datetime.strptime("2022-12-22 01:00:00", CONFIG_DATE_FORMAT),
            )
        ],
    ),
    GetActionsInIntervalTestCase(
        config=TEST_CONFIG,
        starting_from="2022-12-22 22:00:00",
        until="2022-12-22 23:59:00",
        ground_truth=[
            Action(
                action_type=ActionType.STOP,
                action_date_type=ActionDateType.HOLIDAY,
                datetime=datetime.datetime.strptime("2022-12-22 23:00:00", CONFIG_DATE_FORMAT),
            )
        ],
    ),
    GetActionsInIntervalTestCase(
        config=TEST_CONFIG,
        starting_from="2022-12-23 23:00:00",
        until="2023-01-03 09:00:00",
        ground_truth=[
            Action(
                action_type=ActionType.START,
                action_date_type=ActionDateType.HOLIDAY,
                datetime=datetime.datetime.strptime("2023-01-03 08:00:00", CONFIG_DATE_FORMAT),
            )
        ],
    ),
]


@pytest.mark.parametrize("case", GET_ACTIONS_IN_INTERVAL_TEST_CASES)
def test_get_actions_in_interval(case: GetActionsInIntervalTestCase):
    config = Config(**yaml.safe_load(case.config))
    schedule = config.schedules["main"]

    result = get_actions_in_interval(
        schedule,
        datetime.datetime.strptime(case.starting_from, CONFIG_DATE_FORMAT).replace(
            tzinfo=pytz.timezone(schedule.timezone_str)
        ),
        datetime.datetime.strptime(case.until, CONFIG_DATE_FORMAT).replace(tzinfo=pytz.timezone(schedule.timezone_str)),
    )

    assert [
        Action(
            action_type=action.action_type,
            action_date_type=action.action_date_type,
            datetime=action.datetime.replace(tzinfo=None),
        )
        for action in result
    ] == case.ground_truth


T = typing.TypeVar("T")


def does_list_contains_elements_in_order(_list: list[T], elements: list[T]) -> bool:
    next_element_index = 0
    for item in _list:
        if item == elements[next_element_index]:
            next_element_index += 1
        if next_element_index == len(elements):
            return True
    return False


# TODO: Change test to use custom nsscheduler mocking
# @pytest.mark.timeout(4 * 3)
# @pytest.mark.asyncio
# async def test_schedule_env(caplog, monkeypatch):
#     # Monkey-patching nsscheduler.updown:
#     scheduler.logging.getLogger().setLevel(logging.DEBUG)

#     async def mock_up(namespaces: list, batch_size: int = 0, batch_timeout: int = 0) -> None:
#         await asyncio.sleep(0.1)

#         if batch_size > 0 and batch_timeout > 0:
#             batch_msg = f" in batches of {batch_size}"
#         else:
#             batch_msg = ""

#         for ns in namespaces:
#             logging.info(f"Start up namespace '{ns}'{batch_msg}")
#             updown.namespace_states[ns] = NamespaceState.UP

#     async def mock_down(namespaces: list) -> None:
#         await asyncio.sleep(0.1)

#         for ns in reversed(namespaces):
#             logging.info(f"Shut down namespace '{ns}'")
#             updown.namespace_states[ns] = NamespaceState.DOWN

#     # Because these methods actually imported as `from updown import up, down` in scheduler, we monkeypatch scheduler
#     # and not updown itself
#     monkeypatch.setattr(scheduler, "up", mock_up)
#     monkeypatch.setattr(scheduler, "down", mock_down)

#     # Define helper function

#     async def run_test(_config_substring: str, log_messages: list[str], timeout: int, case_name: str) -> None:
#         _config_str = """
# schedules:
#   main:
#     timezone: UTC
# {}
# envs:
#   test-env:
#     namespaces:
#       - test-namespace
#     schedule: main
#     """.format(
#             _config_substring
#         )

#         config = Config(**yaml.safe_load(_config_str))

#         try:
#             _timeout = asyncio.timeout(timeout)
#             async with _timeout:
#                 async with asyncio.TaskGroup() as tg:
#                     # Run scheduling tasks asynchronously
#                     scheduler._reset_all_env_controllers()
#                     for env_name, env in config.envs.items():
#                         tg.create_task(schedule_env(env, env_name, config.schedules[env.schedule], _tick_period=0.01))
#                         break

#         except TimeoutError:
#             pass

#         assert does_list_contains_elements_in_order(
#             caplog.record_tuples, [("root", logging.INFO, msg) for msg in log_messages]
#         ), (
#             f"Testcase [{case_name}]: Expected to find {log_messages} in log in that order, but could not.\n"
#             f"Log: {caplog.record_tuples}"
#         )

#         caplog.clear()

#     # Run tests

#     def timestamp_seconds_ahead(seconds: int) -> datetime:
#         return datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(seconds=seconds)

#     await run_test(
#         f"""
#     holidays:
#       - stop: {timestamp_seconds_ahead(1).strftime(CONFIG_DATE_FORMAT)}
#         start: {timestamp_seconds_ahead(2).strftime(CONFIG_DATE_FORMAT)}
# """,
#         log_messages=["Shut down namespace 'test-namespace'", "Start up namespace 'test-namespace'"],
#         timeout=3,
#         case_name="holidays",
#     )

#     await run_test(
#         f"""
#     weekdays:
#       - days: [1,2,3,4,5,6,7]
#         stop: {timestamp_seconds_ahead(1).strftime(CONFIG_TIME_FORMAT)}
#         start: {timestamp_seconds_ahead(2).strftime(CONFIG_TIME_FORMAT)}
# """,
#         log_messages=["Shut down namespace 'test-namespace'", "Start up namespace 'test-namespace'"],
#         timeout=3,
#         case_name="weekdays",
#     )

#     await run_test(
#         f"""
#     weekdays:
#       - days: [1,2,3,4,5,6,7]
#         start: {timestamp_seconds_ahead(3).strftime(CONFIG_TIME_FORMAT)}
#         stop: {timestamp_seconds_ahead(1).strftime(CONFIG_TIME_FORMAT)}
#     holidays:
#       - stop: {timestamp_seconds_ahead(2).strftime(CONFIG_DATE_FORMAT)}
#         start: {timestamp_seconds_ahead(4).strftime(CONFIG_DATE_FORMAT)}
# """,
#         log_messages=[
#             "Shut down namespace 'test-namespace'",
#             "Shut down namespace 'test-namespace'",
#             "Start up namespace 'test-namespace'",
#         ],
#         timeout=5,
#         case_name="mixed",
#     )


# TODO: rename "stop" and "start" everywhere. I believe it may be confusing to understand that holidays begin with stop
#   and end with start

# TODO: add test for empty fields in config
