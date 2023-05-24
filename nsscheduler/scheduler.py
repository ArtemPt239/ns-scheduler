import asyncio
import logging
import warnings
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from itertools import chain
from threading import Lock

from pytz import timezone

from nsscheduler.data_models.api import (
    EnvironmentState,
    EnvStateResponse,
    NamespaceStateResponse,
    StateAllResponse,
)
from nsscheduler.data_models.internal import Action, ActionDateType, ActionType
from nsscheduler.data_models.scheduler_config import Environment, Schedule
from nsscheduler.updown import down, get_state, up


def get_actions_in_interval(schedule: Schedule, starting_from: datetime, until: datetime) -> list[Action]:
    """
    Returns sorted list of actions, which should happen according to schedule within interval (starting_from, until).

    Both starting_from and until must be timezone-aware timestamps.
    """
    assert starting_from.tzinfo is not None and until.tzinfo is not None

    def lies_within_range(_datetime: datetime) -> bool:
        return starting_from <= _datetime <= until

    actions = []

    for holiday in schedule.holidays:
        if lies_within_range(holiday.stop):
            actions.append(
                Action(
                    action_type=ActionType.STOP,
                    action_date_type=ActionDateType.HOLIDAY,
                    datetime=holiday.stop.replace(tzinfo=timezone(schedule.timezone_str)),
                )
            )
        if lies_within_range(holiday.start):
            actions.append(
                Action(
                    action_type=ActionType.START,
                    action_date_type=ActionDateType.HOLIDAY,
                    datetime=holiday.start.replace(tzinfo=timezone(schedule.timezone_str)),
                )
            )

    def is_datetime_on_holidays(_datetime: datetime):
        # I am pretty sure that this can be done in log(n), but that would make code a bit more complex
        for holiday in schedule.holidays:
            if holiday.stop <= _datetime <= holiday.start:
                return True
        return False

    for weekday_entry in schedule.weekdays:
        for weekday in weekday_entry.days:
            stop_actions = (
                [(ActionType.STOP, time) for time in weekday_entry.stop] if weekday_entry.stop is not None else []
            )
            start_actions = (
                [(ActionType.START, time) for time in weekday_entry.start] if weekday_entry.start is not None else []
            )
            for action_type, action_time in chain(stop_actions, start_actions):
                # we use Monday = 1, Sunday = 7 (while datetime.weekday() returns Monday = 0, Sunday = 6)
                action_date = starting_from.date() - timedelta(days=(starting_from.weekday() + 1 - weekday) % 7)
                while (
                    datetime.combine(
                        action_date, time(hour=0, minute=0, second=0, tzinfo=timezone(schedule.timezone_str))
                    )
                    <= until
                ):
                    candidate_datetime = datetime.combine(action_date, action_time)
                    if lies_within_range(candidate_datetime) and not is_datetime_on_holidays(candidate_datetime):
                        actions.append(
                            Action(
                                action_type=action_type,
                                action_date_type=ActionDateType.WEEKDAY,
                                datetime=candidate_datetime,
                            )
                        )
                    action_date += timedelta(days=7)

    return sorted(actions)


class EnvControllerState(Enum):
    IDLE: int = 0
    ACTION_IN_PROGRESS: int = 1
    MANUAL_ACTION_SCHEDULED: int = 2


class EnvironmentSchedulerException(Exception):
    pass


class EnvironmentIsAlreadyScheduledException(EnvironmentSchedulerException):
    pass


class AnotherActionIsInProgressException(EnvironmentSchedulerException):
    pass


class ManualActionIsAlreadyScheduled(EnvironmentSchedulerException):
    pass


class WrongEnvNameException(EnvironmentSchedulerException):
    pass


@dataclass
class EnvironmentController:
    action_queue: deque[Action]
    env_state: EnvControllerState
    env_state_lock: Lock
    schedule: Schedule
    env: Environment


_env_controllers: dict[str, EnvironmentController] = {}


def _get_env_controller(env_name: str) -> EnvironmentController:
    try:
        return _env_controllers[env_name]
    except KeyError as e:
        raise WrongEnvNameException from e


def add_manual_action_to_queue(env_name: str, action_type: ActionType):
    env_controller = _get_env_controller(env_name)
    with env_controller.env_state_lock:
        if env_controller.env_state == EnvControllerState.ACTION_IN_PROGRESS:
            raise AnotherActionIsInProgressException
        if env_controller.env_state == EnvControllerState.MANUAL_ACTION_SCHEDULED:
            raise ManualActionIsAlreadyScheduled
        action = Action(
            action_type=action_type,
            action_date_type=ActionDateType.MANUAL,
            datetime=datetime.now(tz=timezone(env_controller.schedule.timezone_str)),
        )
        env_controller.action_queue.appendleft(action)
        logging.debug(f"Added action {action} to action queue for env {env_name}")
        env_controller.env_state = EnvControllerState.MANUAL_ACTION_SCHEDULED


async def get_env_state(env_name: str) -> EnvStateResponse:
    env_controller = _get_env_controller(env_name)
    ns_states = await get_state(env_controller.env.namespaces)

    # TODO: should this be behind env_state_lock?
    if env_controller.env_state == EnvControllerState.ACTION_IN_PROGRESS:
        env_state = EnvironmentState.ACTION_IN_PROGRESS
    elif any([ns_state.is_up() for ns_state in ns_states.values()]):
        env_state = EnvironmentState.UP
    else:
        env_state = EnvironmentState.DOWN

    return EnvStateResponse(
        env_name=env_name,
        env_state=env_state,
        env_schedule=env_controller.schedule,
        next_action=env_controller.action_queue[0] if env_controller.action_queue else None,
        namespaces=[NamespaceStateResponse(namespace_name=name, state=state) for name, state in ns_states.items()],
    )


async def get_all_env_states() -> StateAllResponse:
    tasks = [asyncio.create_task(get_env_state(env_name)) for env_name in _env_controllers.keys()]
    return StateAllResponse(environments=[await task for task in tasks])


async def run_action(env_controller: EnvironmentController):
    """Executes next action in the env_controller.action_queue"""
    with env_controller.env_state_lock:
        if env_controller.env_state == EnvControllerState.ACTION_IN_PROGRESS:
            raise AnotherActionIsInProgressException
        env_controller.env_state = EnvControllerState.ACTION_IN_PROGRESS

    action = env_controller.action_queue.popleft()
    env = env_controller.env

    if action.action_type == ActionType.STOP:
        await down(env.namespaces)
    elif action.action_type == ActionType.START:
        if env.batch is not None:
            await up(env.namespaces, env.batch.size, env.batch.timeout)
        else:
            await up(env.namespaces)
    else:
        assert False, "Not Reachable"

    with env_controller.env_state_lock:
        env_controller.env_state = EnvControllerState.IDLE


async def schedule_env(
    env: Environment,
    env_name: str,
    schedule: Schedule,
    queue_recalculation_period: timedelta = timedelta(days=30),
    _tick_period: float = 3,
):
    """
    Manage environment according to a schedule.

    :param env: environment to manage
    :param env_name: name of the environment
    :param schedule: schedule to use
    :param queue_recalculation_period:
    :param _tick_period: sleep this number of seconds
    """
    global _env_controllers

    assert queue_recalculation_period > timedelta(seconds=0), "queue_recalculation_period must be positive"
    if queue_recalculation_period < timedelta(days=1):
        warnings.warn(
            f"queue_recalculation_period is too short (got {queue_recalculation_period}). "
            "Values bigger than 1 day are recommended for a stable performance"
        )

    if env_name in _env_controllers:
        raise EnvironmentIsAlreadyScheduledException(f"Environment {env_name} is already scheduled")

    # Initial queue population
    logging.debug(f"Initialising action_queue for env={env_name}")
    _env_controllers[env_name] = EnvironmentController(
        action_queue=deque(), env_state=EnvControllerState.IDLE, env_state_lock=Lock(), schedule=schedule, env=env
    )
    env_controller = _env_controllers[env_name]
    next_queue_recalculation_date = datetime.now(tz=timezone(schedule.timezone_str))
    for action in get_actions_in_interval(
        schedule, next_queue_recalculation_date, next_queue_recalculation_date + 2 * queue_recalculation_period
    ):
        env_controller.action_queue.append(action)
    next_queue_recalculation_date += queue_recalculation_period

    # Main loop
    while True:
        if datetime.now(tz=timezone(schedule.timezone_str)) >= next_queue_recalculation_date:
            # Queue repopulation
            logging.debug(f"Repopulating action_queue for env={env_name}")
            for action in get_actions_in_interval(
                schedule,
                next_queue_recalculation_date + queue_recalculation_period,
                next_queue_recalculation_date + 2 * queue_recalculation_period,
            ):
                env_controller.action_queue.append(action)
            next_queue_recalculation_date += queue_recalculation_period

        if not len(env_controller.action_queue) == 0:
            next_action = env_controller.action_queue[0]
            if next_action.datetime <= datetime.now(tz=timezone(schedule.timezone_str)):
                await run_action(env_controller)

        await asyncio.sleep(_tick_period)


def _reset_all_env_controllers():
    global _env_controllers
    _env_controllers = {}
