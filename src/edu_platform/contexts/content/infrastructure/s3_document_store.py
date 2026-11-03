"""DocumentStore adapter on S3-compatible object storage (MinIO locally).

The corpus bucket has versioning enabled (minio-init), so ``put`` returns the S3 version id
and ``fetch`` can read an exact version even if a key is ever overwritten. LMS content uses
one key per version (``courses/<course>/<content>/v<n>.<ext>``), so ``version_id=None``
(latest) is unambiguous for it.
"""

from __future__ import annotations

from typing import Any


class DocumentNotFound(Exception):
    pass


class S3DocumentStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, object_key: str, body: str) -> str:
        response = self._client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=body.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        return str(response.get("VersionId") or "null")  # "null" = bucket not versioned

    def fetch(self, object_key: str, version_id: str | None) -> str:
        args: dict[str, Any] = {"Bucket": self._bucket, "Key": object_key}
        if version_id and version_id not in ("null", "latest"):
            args["VersionId"] = version_id
        try:
            response = self._client.get_object(**args)
        except self._client.exceptions.NoSuchKey as exc:
            raise DocumentNotFound(f"s3://{self._bucket}/{object_key} does not exist") from exc
        return str(response["Body"].read().decode("utf-8"))
