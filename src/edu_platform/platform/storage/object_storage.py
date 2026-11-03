"""S3-compatible object storage client (MinIO locally, S3 in cloud).

One factory so every service honours ``EDU_S3_ENDPOINT`` (MinIO, path-style addressing)
and the same retry policy. Version-aware reads live in the adapters that need them
(content context: S3DocumentStore), since only they know their key layout.
"""

from __future__ import annotations

from typing import Any

from edu_platform.platform.config import LakehouseSettings


def create_s3_client(settings: LakehouseSettings) -> Any:
    """boto3 S3 client; imported lazily (``content`` / ``demo`` extras)."""
    import boto3
    from botocore.config import Config

    secret = settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=secret,
        region_name="us-east-1",
        config=Config(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=15,
        ),
    )
