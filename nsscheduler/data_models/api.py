from enum import Enum

from pydantic import BaseModel

from nsscheduler.data_models.internal import Action, NamespaceState
from nsscheduler.data_models.scheduler_config import Schedule


class EnvironmentState(str, Enum):
    UP = "Up"
    DOWN = "Down"
    ACTION_IN_PROGRESS = "Action in progress"


class NamespaceStateResponse(BaseModel):
    namespace_name: str
    state: NamespaceState


class EnvStateResponse(BaseModel):
    env_name: str
    env_state: EnvironmentState
    env_schedule: Schedule
    next_action: Action | None
    namespaces: list[NamespaceStateResponse]


class StateAllResponse(BaseModel):
    environments: list[EnvStateResponse]
