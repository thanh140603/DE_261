# Hive Metastore 3.1.3 = the lakehouse catalog shared by Spark (writer) and Trino (SQL warehouse).
#
# Why 3.1.x and not 4.x: Spark 3.5's built-in Hive client fails against a Hive 4 metastore
# ("Invalid method name: 'get_table'"); see ADR 0010. The image adds what the stock one lacks:
#   - a Postgres JDBC driver new enough for SCRAM auth (Postgres 14+ default)
#   - hadoop-aws + AWS SDK matching the bundled Hadoop 3.1.0, so s3a:// table locations resolve
#   - an idempotent entrypoint (the stock one re-runs initSchema and fails on restart)
FROM apache/hive:3.1.3

ARG POSTGRES_JDBC_VERSION=42.7.4
ARG HADOOP_AWS_VERSION=3.1.0
ARG AWS_SDK_BUNDLE_VERSION=1.11.271

USER root
RUN rm -f /opt/hive/lib/postgresql-9.4.1208.jre7.jar
ADD https://repo1.maven.org/maven2/org/postgresql/postgresql/${POSTGRES_JDBC_VERSION}/postgresql-${POSTGRES_JDBC_VERSION}.jar \
    https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/${HADOOP_AWS_VERSION}/hadoop-aws-${HADOOP_AWS_VERSION}.jar \
    https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/${AWS_SDK_BUNDLE_VERSION}/aws-java-sdk-bundle-${AWS_SDK_BUNDLE_VERSION}.jar \
    /opt/hive/lib/
COPY entrypoint.sh /usr/local/bin/metastore-entrypoint.sh
RUN chmod 644 /opt/hive/lib/*.jar && chmod 755 /usr/local/bin/metastore-entrypoint.sh
USER hive

EXPOSE 9083
ENTRYPOINT ["/usr/local/bin/metastore-entrypoint.sh"]
