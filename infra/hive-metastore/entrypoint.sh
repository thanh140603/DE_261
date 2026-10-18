#!/bin/bash
# Start the Hive Metastore thrift service; create the backing schema only on first boot.
set -euo pipefail

export HIVE_CONF_DIR="${HIVE_HOME}/conf"
export HADOOP_CONF_DIR="${HIVE_CONF_DIR}"
if [ -d "${HIVE_CUSTOM_CONF_DIR:-}" ]; then
  find "${HIVE_CUSTOM_CONF_DIR}" -type f -exec ln -sfn {} "${HIVE_CONF_DIR}/" \;
fi
export HADOOP_CLIENT_OPTS="${HADOOP_CLIENT_OPTS:-} -Xmx${METASTORE_HEAP:-512m}"

if "${HIVE_HOME}/bin/schematool" -dbType postgres -info >/dev/null 2>&1; then
  echo "metastore schema present - skipping init"
else
  "${HIVE_HOME}/bin/schematool" -dbType postgres -initSchema
fi

exec "${HIVE_HOME}/bin/hive" --skiphadoopversion --skiphbasecp --service metastore
