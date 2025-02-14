import argparse
import asyncio
import logging
import sys
from itertools import chain

import dash_bootstrap_components as dbc
import requests
from dash import MATCH, Dash, Input, Output, State, ctx, dcc, html
from gevent.pywsgi import WSGIServer

from nsscheduler.data_models.api import (
    EnvironmentState,
    EnvStateResponse,
    StateAllResponse,
)

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], title="ns-scheduler dashboard")


# Layout:


def generate_env_subtable(env_state_response: EnvStateResponse) -> list[html.Tr]:
    rows = [
        dbc.Alert(
            "Oh uh. Alert!",
            id={"type": "alert", "id": env_state_response.env_name},
            className="alert",
            is_open=False,
            color="danger",
        )
    ]  # Cringe TODO: fix me

    for namespace_index, namespace_status_response in enumerate(env_state_response.namespaces):
        row = []
        _id = hash((env_state_response.env_name, len(rows)))

        # Environment-level columns:
        if namespace_index == 0:
            row.append(
                html.Td(
                    [
                        html.Div(
                            env_state_response.env_name, id={"type": "env_name_div", "id": env_state_response.env_name}
                        ),
                        dbc.Popover(
                            [
                                dbc.PopoverHeader("Schedule:"),
                                dbc.PopoverBody(
                                    list(
                                        chain(
                                            *[
                                                (line, html.Br())
                                                for line in str(env_state_response.env_schedule).split("\n")
                                            ]
                                        )
                                    )
                                ),
                            ],
                            id={"type": "env_name_popover", "id": env_state_response.env_name},
                            target={"type": "env_name_div", "id": env_state_response.env_name},
                            body=True,
                            trigger="hover",
                        ),
                    ],
                    rowSpan=len(env_state_response.namespaces),
                )
            )
            row.append(
                html.Td(
                    html.Div(
                        env_state_response.env_state, id={"type": "env_state_div", "id": env_state_response.env_name}
                    ),
                    rowSpan=len(env_state_response.namespaces),
                )
            )
            row.append(
                html.Td(
                    [
                        html.Button(
                            children="Up",
                            id={"type": "manual_action_up_button", "id": env_state_response.env_name},
                            disabled=not (env_state_response.env_state == EnvironmentState.DOWN),
                        ),
                        html.Button(
                            children="Down",
                            id={"type": "manual_action_down_button", "id": env_state_response.env_name},
                            disabled=not (env_state_response.env_state == EnvironmentState.UP),
                        ),
                    ],
                    rowSpan=len(env_state_response.namespaces),
                )
            )
            row.append(
                html.Td(html.Div(str(env_state_response.next_action)), rowSpan=len(env_state_response.namespaces))
            )

        # Namespace-level columns:
        row.append(
            html.Td(
                html.Div(namespace_status_response.namespace_name, id={"type": "namespace_name_div", "id": _id}),
                className="namespace-td",
            )
        )
        row.append(html.Td(html.Div(namespace_status_response.state.pods), className="namespace-td"))
        row.append(html.Td(html.Div(f"{namespace_status_response.state.cpu:.2f}"), className="namespace-td"))
        row.append(
            html.Td(
                html.Div(f"{namespace_status_response.state.memory / 1_073_741_824:.2f}G"), className="namespace-td"
            )
        )
        rows.append(html.Tr(row))
    return rows


async def generate_table(base_url: str):
    response = StateAllResponse(**requests.get(f"{base_url}/state_all").json())

    subtables = []
    for env_state_response in response.environments:
        subtables.append(
            html.Tbody(
                children=generate_env_subtable(env_state_response),
                id={"type": "environment_tbody", "id": env_state_response.env_name},
            )
        )

    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Environment", className="env-th-name"),
                        html.Th("State", className="env-th-state"),
                        html.Th(""),
                        html.Th("Next action"),
                        html.Th("Namespaces", className="namespace-th-name"),
                        html.Th("Pods"),
                        html.Th("Cpu"),
                        html.Th("Mem"),
                    ]
                )
            ),
            *subtables,
        ],
        className="styled-table",
    )


def build_app_layout() -> html.Div:
    return html.Div(
        className="root-div",
        children=[
            html.H1(children="nsscheduler dashboard"),
            html.Div(id="table_loading", children=dbc.Spinner()),
            html.Div(id="dummy_div_for_callbacks_on_page_load"),
            dcc.Interval(id="state_lookup_timer", interval=5 * 1000, n_intervals=0),  # in milliseconds
            dbc.Alert("Oh uh. Alert!", id="alert", className="alert", is_open=False, color="danger"),
        ],
    )


# Cache env states
env_state_lifetime = float(4)
env_states = {}
env_state_times = {}
def get_env_state(env_name: str) -> EnvStateResponse:
    global env_states, env_state_times, env_state_lifetime
    if env_state_times.get(env_name, 10e30) + env_state_lifetime > time.time():
        logging.debug(f"Requesting current state for env '{env_name}'")
        env_states[env_name] = EnvStateResponse(**requests.get(f"{base_url}/state/{env_name}").json())
        env_state_times[env_name] = time.time()
    else:
        logging.debug(f"Returning cached state for env '{env_name}'")

    return env_states[env_name]


# Callbacks:


@app.callback(
    Output({"type": "environment_tbody", "id": MATCH}, "children"),
    Output({"type": "alert", "id": MATCH}, "is_open"),
    Output({"type": "alert", "id": MATCH}, "children"),
    Input("state_lookup_timer", "n_intervals"),
    Input({"type": "manual_action_up_button", "id": MATCH}, "n_clicks"),
    Input({"type": "manual_action_down_button", "id": MATCH}, "n_clicks"),
    State({"type": "environment_tbody", "id": MATCH}, "children"),
    State({"type": "env_name_div", "id": MATCH}, "children"),
)
def get_state_of_env(n_interval: int, up_n_clicks: int, down_n_clicks: int, current_tbody_children, env_name: str):
    def execute_action(action: str):
        response = requests.post(f"{base_url}/{action}/{env_name}")
        if response.status_code == 200:
            return current_tbody_children, False, ""
        else:
            return current_tbody_children, True, f"{response.json()['detail']}"

    try:
        if ctx.triggered_id is None:
            return current_tbody_children, False, ""
        if ctx.triggered_id == "state_lookup_timer":
            return (
                generate_env_subtable(get_env_state(env_name)),
                False,
                "",
            )
        if ctx.triggered_id["type"] == "manual_action_up_button":
            return execute_action("up")
        if ctx.triggered_id["type"] == "manual_action_down_button":
            return execute_action("down")
    except requests.RequestException as e:
        logging.error(f"Connection error: {e}")
        return current_tbody_children, True, f"Connection error: {e}"


@app.callback(
    Output("table_loading", "children"),
    Output("alert", "is_open"),
    Output("alert", "children"),
    Input("dummy_div_for_callbacks_on_page_load", "children"),
)
def initial_table_build(_):
    try:
        return asyncio.run(generate_table(base_url)), False, ""
    except requests.RequestException as e:
        logging.error(f"Connection error: {e}")
        return "", True, f"Connection error: {e}"


base_url = "http://127.0.0.1:5001"


def main():
    global base_url

    parser = argparse.ArgumentParser(
        description="Dashboard web server", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--scheduler-api-url", default="http://127.0.0.1:5001", help="location of scheduler api server")
    parser.add_argument("--listen-host", default="127.0.0.1", help="ip address for this dashboard server")
    parser.add_argument("--listen-port", default=8050, help="port for this dashboard server")
    parser.add_argument(
        "--logging-level",
        default="WARNING",
        help="logging level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )

    args = parser.parse_args()

    logging.basicConfig(level=args.logging_level, stream=sys.stdout, format="%(levelname)s: [%(asctime)s] %(message)s")

    base_url = args.scheduler_api_url
    app.layout = build_app_layout()

    # For development:
    # app.run(host=args.listen_host, port=args.listen_port, debug=True)

    # For deployment:
    http_server = WSGIServer((args.listen_host, int(args.listen_port)), app.server, log=logging, error_log=logging)
    logging.info(f"Starting dashboard server on {args.listen_host}:{args.listen_port}")
    http_server.serve_forever()


if __name__ == "__main__":
    main()
