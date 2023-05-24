FROM python:3.11.1

WORKDIR /usr/src/app

COPY nsscheduler nsscheduler
COPY pyproject.toml setup.cfg README.md ./

RUN pip install -e .

CMD ["ns-scheduler", "--listen-host", "0.0.0.0", "--listen-port", "5001", "--logging-level", "INFO"]

EXPOSE 5001
