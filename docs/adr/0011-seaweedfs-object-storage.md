# ADR 0011: SeaweedFS replaces MinIO as the local S3-compatible object store

Status: accepted - 2026-10-18 (implementation detail of ADR 0005)

## Context
The local stack used `minio/minio` and `minio/mc`. MinIO stopped publishing community images
in October 2025, archived the repository in 2026 and the images were deleted from Docker Hub on
2026-09-11 (`pull access denied ... repository does not exist`); the quay.io mirror is frozen at
the 2025-09 release with no security fixes. `docker compose up` could no longer start storage.

## Decision
Use **SeaweedFS** (Apache-2.0, actively released) in `weed server -s3` mode, pinned to a release
tag. It fills exactly the same role: S3 API for `s3a://lakehouse`, the `corpus` bucket with
**object versioning** (content context requirement), Flink checkpoints. Buckets and versioning
are created with plain S3 API calls (`infra/seaweedfs/init-buckets.sh`), so any S3-compatible
store (AWS S3, a MinIO build, Garage, Ceph RGW) can be swapped back by changing the endpoint.

## Consequences
- Host port 9000 keeps the S3 endpoint stable for host tools; the UI moves to :8888.
- Local credentials are now `lakehouse` / `lakehouse-secret-key` (`infra/seaweedfs/s3.json`).
- Production still targets managed object storage (S3 / ADLS / GCS); nothing above the S3 API
  depends on SeaweedFS.
