"""Message encoding/decoding.

``JsonCodec`` is the local-dev codec (orjson when available, stdlib json
otherwise). ``AvroSchemaRegistryCodec`` remains a documented TODO; the
``schema_subject`` argument is carried through so the two codecs share one
interface and an Avro swap does not touch callers.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, cast


class Codec(Protocol):
    def encode(self, payload: dict[str, Any], *, schema_subject: str) -> bytes: ...

    def decode(self, raw: bytes, *, schema_subject: str) -> dict[str, Any]: ...


class JsonCodec:
    def encode(self, payload: dict[str, Any], *, schema_subject: str) -> bytes:
        try:
            import orjson

            return orjson.dumps(payload, default=str)
        except ImportError:
            return json.dumps(payload, default=str).encode("utf-8")

    def decode(self, raw: bytes, *, schema_subject: str) -> dict[str, Any]:
        try:
            import orjson

            return cast(dict[str, Any], orjson.loads(raw))
        except ImportError:
            return cast(dict[str, Any], json.loads(raw.decode("utf-8")))
