#!/usr/bin/env bash
# Copy a stopped verification project and restore it to fresh named volumes.
set -euo pipefail

action=${1:?Usage: cold-volume-copy.sh backup|restore COMPOSE_PROJECT BACKUP_DIR}
project=${2:?Supply the Compose project name}
archive=${3:?Supply the backup directory}
volumes=(postgres-data kafka-data minio-data br45-checkpoints)
image=postgres:16

if [[ ! "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "Invalid Compose project name" >&2
  exit 2
fi
if [[ -n "$(docker ps -q --filter "label=com.docker.compose.project=$project")" ]]; then
  echo "Stop the selected Compose project before copying its volumes" >&2
  exit 1
fi

case "$action" in
  backup)
    for volume in "${volumes[@]}"; do
      docker volume inspect "${project}_$volume" >/dev/null
    done
    mkdir -- "$archive"
    for volume in "${volumes[@]}"; do
      docker run --rm --network none \
        --mount "type=volume,source=${project}_$volume,target=/data,readonly" \
        --entrypoint tar "$image" -C /data -cpf - . >"$archive/$volume.tar"
    done
    (
      cd "$archive"
      sha256sum ./*.tar >SHA256SUMS
    )
    ;;
  restore)
    (
      cd "$archive"
      sha256sum --check SHA256SUMS
    )
    for volume in "${volumes[@]}"; do
      test -s "$archive/$volume.tar"
      if docker volume inspect "${project}_$volume" >/dev/null 2>&1; then
        echo "Refusing to overwrite existing volume ${project}_$volume" >&2
        exit 1
      fi
    done
    for volume in "${volumes[@]}"; do
      docker volume create \
        --label "com.docker.compose.project=$project" \
        --label "com.docker.compose.volume=$volume" "${project}_$volume" >/dev/null
      docker run --rm -i --network none \
        --mount "type=volume,source=${project}_$volume,target=/data" \
        --entrypoint tar "$image" -C /data -xpf - <"$archive/$volume.tar"
    done
    ;;
  *)
    echo "Choose backup or restore" >&2
    exit 2
    ;;
esac
