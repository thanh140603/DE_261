# Airflow 2.10 on top of the Spark image (orchestration/airflow/dags/_common.py).
#
# Tasks are BashOperators that call the `edu` CLI, so the scheduler (LocalExecutor) needs the
# exact runtime the batch jobs use: Spark 3.5 + Delta + S3A jars and the edu package. Airflow
# itself lives in its own virtualenv so its pinned constraints never change the packages the
# jobs import; only the `airflow` entry point is linked onto PATH.
#
#   docker compose build spark && docker compose --profile airflow build airflow-init
FROM de261/spark:local

ARG AIRFLOW_VERSION=2.10.5
ARG PYTHON_VERSION=3.11

# Spark tasks must keep using the system interpreter that has pyspark + edu installed.
ENV AIRFLOW_HOME=/opt/airflow \
    AIRFLOW_VENV=/opt/airflow-venv \
    PYSPARK_PYTHON=/usr/local/bin/python3 \
    PYSPARK_DRIVER_PYTHON=/usr/local/bin/python3

RUN python -m venv "${AIRFLOW_VENV}" \
 && "${AIRFLOW_VENV}/bin/pip" install --no-cache-dir \
      "apache-airflow[postgres]==${AIRFLOW_VERSION}" \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt" \
 && ln -s "${AIRFLOW_VENV}/bin/airflow" /usr/local/bin/airflow \
 && mkdir -p "${AIRFLOW_HOME}/dags" "${AIRFLOW_HOME}/logs"

WORKDIR ${AIRFLOW_HOME}
CMD ["airflow", "version"]
