from datetime import datetime
from enum import Enum
from functools import total_ordering

from pydantic import BaseModel


@total_ordering
class OrderedEnum(Enum):
    def __eq__(self, other):
        if self.__class__ is other.__class__:
            return self.value == other.value
        raise NotImplementedError

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        raise NotImplementedError


class ActionType(OrderedEnum):
    # TODO: check that order of these is semantically correct
    STOP: int = 0
    START: int = 1


class ActionDateType(OrderedEnum):
    # TODO: check that order of these is semantically correct
    MANUAL: int = 0
    HOLIDAY: int = 1
    WEEKDAY: int = 2


@total_ordering
class Action(BaseModel):
    action_type: ActionType
    action_date_type: ActionDateType
    datetime: datetime

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Action):
            raise NotImplementedError
        return (
            self.action_type == other.action_type
            and self.action_date_type == other.action_date_type
            and self.datetime == other.datetime
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Action):
            raise NotImplementedError
        if self.datetime < other.datetime:
            return True
        elif self.datetime == other.datetime:
            if self.action_date_type < other.action_date_type:
                return True
            elif self.action_date_type == other.action_date_type:
                if self.action_type < other.action_type:
                    return True

        return False

    def __str__(self) -> str:
        return f"{self.datetime.strftime('%Y-%m-%d %H:%M:%S')} {self.action_type.name}"


class NamespaceState(BaseModel):
    pods: int
    cpu: float
    memory: float

    def is_up(self) -> bool:
        return self.pods > 0

    def __str__(self) -> str:
        return f"replicas: {self.pods}, cpu: {self.cpu:.2f}, mem: {self.memory / 1_073_741_824:.2f}G"
