FROM apache/spark:3.5.1 AS spark-dist
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*
COPY --from=spark-dist /opt/spark /opt/spark
ENV SPARK_HOME=/opt/spark
WORKDIR /app
COPY pyproject.toml README.md ./
RUN python -c "import tomllib,subprocess; p=tomllib.load(open('pyproject.toml','rb'))['project']; subprocess.check_call(['pip','install','--no-cache-dir','hatchling',*p['dependencies']])"
RUN pip install --no-cache-dir editables
COPY src ./src
COPY infra/br45/stream.py ./infra/br45/stream.py
RUN pip install --no-deps --no-build-isolation -e .
# Pin the Kafka connector to the existing Spark/Scala versions. Cache at image build.
RUN mkdir -p /tmp/br45-ivy && /opt/spark/bin/spark-submit \
    --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1 \
    --conf spark.jars.ivy=/tmp/br45-ivy \
    /opt/spark/examples/src/main/python/pi.py 1
RUN useradd --uid 185 --create-home spark && mkdir -p /checkpoints \
    && chown -R 185:0 /app /checkpoints /tmp/br45-ivy /opt/spark
USER 185
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
ENTRYPOINT ["/opt/spark/bin/spark-submit", "--master", "local[2]", "--driver-memory", "1g", "--conf", "spark.jars.ivy=/tmp/br45-ivy", "--packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1", "/app/infra/br45/stream.py"]
