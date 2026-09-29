"""S3-compatible object storage client (MinIO locally, S3/ADLS/GCS in cloud).

Content (TODO):
- boto3 client factory honouring EDU_S3_ENDPOINT for MinIO.
- ``list_objects(bucket, prefix)``, ``get_object(bucket, key, version_id)``, ``put_object``.
- Version-aware reads (S3 object versioning): the content context requires
  strict versioning of transcripts / slides / exercises.
"""

from __future__ import annotations


class ObjectStorageClient:
    def __init__(
        self, endpoint: str | None, access_key: str | None, secret_key: str | None
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key

    # TODO: implement methods listed in module docstring.
