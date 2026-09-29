"""Message encoding/decoding and schema-version negotiation.

Content (TODO):
- ``JsonCodec`` (orjson) for local dev.
- ``AvroSchemaRegistryCodec`` backed by Confluent Schema Registry using the
  contracts under /schemas. Enforces BACKWARD compatibility on registration.
- Attach ``schema_version`` header so consumers can dispatch telemetry
  migrations (contexts/telemetry/infrastructure/schema_migrations).
"""

from __future__ import annotations

from typing import Any, Protocol


class Codec(Protocol):
    def encode(self, payload: dict[str, Any], *, schema_subject: str) -> bytes: ...

    def decode(self, raw: bytes, *, schema_subject: str) -> dict[str, Any]: ...


class JsonCodec:
    def encode(self, payload: dict[str, Any], *, schema_subject: str) -> bytes:
        raise NotImplementedError  # TODO: orjson.dumps with default=str

    def decode(self, raw: bytes, *, schema_subject: str) -> dict[str, Any]:
        raise NotImplementedError  # TODO: orjson.loads + validate against /schemas
