# Spark 3.5 + Delta Lake 3.3 + S3A image for every Spark process (master, worker, jobs).
#
# One image for driver and executors so the Python version always matches (PySpark refuses
# mismatched driver/worker interpreters) and the project's UDFs (pseudonymise, NormalizeEvents)
# are importable on executors. Python 3.11 matches pyproject `requires-python`.
#
#   docker compose build spark          # built from the repo root (see docker-compose.yml)
FROM python:3.11-slim-bookworm

ARG SPARK_VERSION=3.5.5
ARG DELTA_VERSION=3.3.2
# Must match the Hadoop client bundled with pyspark 3.5.x (3.3.4).
ARG HADOOP_AWS_VERSION=3.3.4
ARG AWS_SDK_BUNDLE_VERSION=1.12.262

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps tini \
 && rm -rf /var/lib/apt/lists/* \
 && ln -s "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java

ENV JAVA_HOME=/opt/java \
    SPARK_HOME=/usr/local/lib/python3.11/site-packages/pyspark \
    PYSPARK_PYTHON=python3 \
    PYSPARK_DRIVER_PYTHON=python3
ENV PATH="${SPARK_HOME}/bin:${PATH}"

RUN pip install "pyspark==${SPARK_VERSION}" "delta-spark==${DELTA_VERSION}"

# Bake the JVM dependencies in instead of `--packages`, so jobs start without Ivy downloads.
ADD https://repo1.maven.org/maven2/io/delta/delta-spark_2.12/${DELTA_VERSION}/delta-spark_2.12-${DELTA_VERSION}.jar \
    https://repo1.maven.org/maven2/io/delta/delta-storage/${DELTA_VERSION}/delta-storage-${DELTA_VERSION}.jar \
    https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/${HADOOP_AWS_VERSION}/hadoop-aws-${HADOOP_AWS_VERSION}.jar \
    https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/${AWS_SDK_BUNDLE_VERSION}/aws-java-sdk-bundle-${AWS_SDK_BUNDLE_VERSION}.jar \
    ${SPARK_HOME}/jars/
# Kafka source for the Structured Streaming landing job (Kafka -> bronze).
ADD https://repo1.maven.org/maven2/org/apache/spark/spark-sql-kafka-0-10_2.12/${SPARK_VERSION}/spark-sql-kafka-0-10_2.12-${SPARK_VERSION}.jar \
    https://repo1.maven.org/maven2/org/apache/spark/spark-token-provider-kafka-0-10_2.12/${SPARK_VERSION}/spark-token-provider-kafka-0-10_2.12-${SPARK_VERSION}.jar \
    https://repo1.maven.org/maven2/org/apache/kafka/kafka-clients/3.4.1/kafka-clients-3.4.1.jar \
    https://repo1.maven.org/maven2/org/apache/commons/commons-pool2/2.11.1/commons-pool2-2.11.1.jar \
    ${SPARK_HOME}/jars/

WORKDIR /app
# Dependencies first so source edits do not invalidate the layer above.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[spark]"
COPY warehouse ./warehouse
COPY schemas ./schemas

ENV EDU_WAREHOUSE_DIR=/app/warehouse
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["edu", "--help"]
