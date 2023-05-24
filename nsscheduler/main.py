import argparse
import asyncio
import contextlib
import logging
import sys
import threading
import time

import uvicorn
import yaml

from nsscheduler.data_models.scheduler_config import Config
from nsscheduler.scheduler import schedule_env
from nsscheduler.updown import kube_init


def read_config(config_file: str) -> Config:
    with open(config_file, "r") as file:
        return Config(**yaml.safe_load(file))


async def _run_scheduling(config: Config):
    logging.debug("Starting scheduling coroutine")
    async with asyncio.TaskGroup() as tg:
        # Run scheduling tasks asynchronously
        for env_name, env in config.envs.items():
            logging.debug(f"Scheduling environment {env_name}")
            tg.create_task(schedule_env(env, env_name, config.schedules[env.schedule]))


async def _run():
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Scheduling server", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--config-file", default="config.yaml", help="path to the config file in YAML format")
    parser.add_argument(
        "--logging-level",
        default="WARNING",
        help="logging level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument("--listen-host", default="127.0.0.1", help="ip address on which REST API server will listen")
    parser.add_argument("--listen-port", default=5001, help="port on which REST API server will listen")
    parser.add_argument(
        "--no-api", help="run only the scheduler, without starting a RestAPI server", action="store_true"
    )
    parser.add_argument("--incluster", help="we run inside kubernetes cluster", default=False, action="store_true")
    parser.add_argument("--context", help="kubernetes config context to use")

    args = parser.parse_args()

    logging.basicConfig(level=args.logging_level, stream=sys.stdout, format="%(levelname)s: [%(asctime)s] %(message)s")

    # Read scheduler config
    # TODO: fail if namespaces specified in config doesn't exist
    logging.debug(f"Reading config from {args.config_file}")
    config = read_config(args.config_file)
    logging.debug(f"Config read: \n{config}")

    # Initialize kubernetes client
    logging.debug("Initializing kubernetes client")
    kube_init(args)
    logging.debug("Kubernetes client initialized")

    # Run API server
    if args.no_api:
        await _run_scheduling(config)
    else:
        # Had to use this instead of `await server.serve()` because otherwise ctrl+c behavior was counterintuitive
        # Credits for this approach: https://github.com/encode/uvicorn/issues/742#issuecomment-674411676
        class Server(uvicorn.Server):
            def install_signal_handlers(self):
                pass

            @contextlib.contextmanager
            def run_in_thread(self):
                thread = threading.Thread(target=self.run)
                thread.start()
                try:
                    while not self.started:
                        time.sleep(1e-3)
                    yield  # why not under the loop?
                finally:
                    self.should_exit = True
                    thread.join()

        uvicorn_config = uvicorn.Config(
            "nsscheduler.api:app",
            host=args.listen_host,
            port=int(args.listen_port),
            log_level=args.logging_level.lower(),
        )
        logging.info(f"Starting API server on {args.listen_host}:{args.listen_port}")
        server = Server(config=uvicorn_config)

        with server.run_in_thread():
            # Server started.
            await _run_scheduling(config)
        # Server stopped.


def main():
    asyncio.run(_run())


if __name__ == "__main__":
    main()
