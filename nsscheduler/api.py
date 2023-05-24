from fastapi import FastAPI, HTTPException

from nsscheduler import scheduler
from nsscheduler.data_models.api import EnvStateResponse, StateAllResponse
from nsscheduler.scheduler import (
    ActionType,
    AnotherActionIsInProgressException,
    ManualActionIsAlreadyScheduled,
    WrongEnvNameException,
)

app = FastAPI()


@app.get("/state_all", response_model=StateAllResponse, tags=["state"])
async def get_state_of_namespaces_in_all_env():
    return await scheduler.get_all_env_states()


@app.get("/state/{env_name}", response_model=EnvStateResponse, tags=["state"])
async def get_state_of_namespaces_in_env(env_name: str):
    try:
        return await scheduler.get_env_state(env_name)
    except WrongEnvNameException:
        raise HTTPException(status_code=422, detail="There are no environments with such name")


# TODO:
#   Maybe addd smart system for queueing ups and downs for spam protection.
#   Probably can instead add non-200 responses to indicate that namespace\env is in process of shutting down\starting up
#   and can't be acted upon right now
def process_action_request(env_name: str, action_type: scheduler.ActionType):
    try:
        scheduler.add_manual_action_to_queue(env_name, action_type)
    except WrongEnvNameException:
        raise HTTPException(status_code=422, detail="There are no environments with such name")
    except AnotherActionIsInProgressException:
        raise HTTPException(
            status_code=409,
            detail="Another action is in progress. "
            "Can't schedule manual actions while another action is in progress",
        )
    except ManualActionIsAlreadyScheduled:
        raise HTTPException(
            status_code=409,
            detail="Manual action is already scheduled but not completed. "
            "Can't schedule more then one manual action",
        )


@app.post("/up/{env_name}", tags=["action"])
async def start_up_the_environment(env_name: str):
    process_action_request(env_name, ActionType.START)


@app.post("/down/{env_name}", tags=["action"])
async def shut_down_the_environment(env_name: str):
    process_action_request(env_name, ActionType.STOP)
