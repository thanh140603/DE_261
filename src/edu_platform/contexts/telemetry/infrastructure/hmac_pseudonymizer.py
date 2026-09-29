"""Keyed-hash (HMAC-SHA256) Pseudonymizer adapter, key-versioned for rotation."""

from __future__ import annotations

import hashlib
import hmac


class HmacPseudonymizer:
    def __init__(self, secret: bytes, key_version: int = 1) -> None:
        self._secret = secret
        self._key_version = key_version

    def pseudonymize(self, raw_identifier: str) -> str:
        digest = hmac.new(self._secret, raw_identifier.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"k{self._key_version}_{digest[:24]}"
