"""Scoped API identities and browser sessions for staff."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
from collections import deque
from dataclasses import dataclass, field
from getpass import getpass
from secrets import token_urlsafe
from time import monotonic
from typing import Annotated, Literal
from urllib.parse import urlsplit

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from edu_platform.platform.logging import get_logger

from .config import settings

StaffRole = Literal["instructor", "advisor", "admin"]
ROLES = ("instructor", "advisor", "admin")
SESSION_SECONDS = 8 * 60 * 60
ROLE_HEADER = "X-Staff-Role"
bearer = HTTPBearer(auto_error=False)
hasher = PasswordHasher()
log = get_logger(__name__)


@dataclass(frozen=True)
class Principal:
    id: str
    role: str
    courses: list[str]
    organisations: list[str] = field(default_factory=list)


def normalize(username: str) -> str:
    return username.strip().lower()


class StaffAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)

    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    role: StaffRole
    password_hash: str
    courses: list[str] = Field(default_factory=list)
    organisations: list[str] = Field(default_factory=list)

    @field_validator("password_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        try:
            parameters = extract_parameters(value)
        except (InvalidHashError, ValueError) as exc:
            raise ValueError("Invalid Argon2id hash") from exc
        if parameters.type != Type.ID or not re.fullmatch(
            r"\$argon2id\$v=19\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+", value
        ):
            raise ValueError("Expected an Argon2id hash")
        return value

    @field_validator("courses", "organisations")
    @classmethod
    def validate_scope(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Scopes must be nonblank identifiers")
        return list(dict.fromkeys(value.strip() for value in values))

    def principal(self) -> Principal:
        return Principal(self.id, self.role, self.courses, self.organisations)


class StaffIdentity(BaseModel):
    id: str
    name: str
    role: StaffRole
    courses: list[str]
    organisations: list[str]


def account_config(raw: str) -> dict[str, StaffAccount]:
    try:
        accounts = TypeAdapter(list[StaffAccount]).validate_json(raw)
    except ValidationError:
        raise ValueError(
            "EDU_STAFF_ACCOUNTS must be a JSON array of valid staff accounts"
        ) from None
    result = {}
    for account in accounts:
        username = normalize(account.username)
        if username in result:
            raise ValueError("EDU_STAFF_ACCOUNTS contains a duplicate username")
        if account.role == "admin" and (account.courses or not account.organisations):
            raise ValueError("Staff admin accounts require organisation scopes")
        if account.role != "admin" and (account.organisations or not account.courses):
            raise ValueError("Staff instructor and advisor accounts require course scopes")
        result[username] = account
    return result


class StaffSessions:
    def __init__(self) -> None:
        self.accounts = account_config(os.environ.get("EDU_STAFF_ACCOUNTS", "[]"))
        self.origin = os.environ.get("EDU_STAFF_ORIGIN", "").rstrip("/")
        if self.origin:
            origin = urlsplit(self.origin)
            if (
                origin.scheme not in {"http", "https"}
                or not origin.netloc
                or (origin.username or origin.path or origin.query or origin.fragment)
            ):
                raise ValueError("EDU_STAFF_ORIGIN must be an HTTP(S) origin")
        self.active: dict[str, tuple[StaffAccount, float]] = {}
        self.attempts: dict[str, deque[float]] = {}
        self.next_prune = 0.0
        self.verifications = asyncio.Semaphore(2)
        self.dummy_hash = hasher.hash(token_urlsafe(32)) if self.accounts else ""

    def limit(self, peer: str) -> None:
        now = monotonic()
        if now >= self.next_prune:
            self.attempts = {
                key: times for key, times in self.attempts.items() if times[-1] > now - 60
            }
            self.next_prune = now + 60
        attempts = self.attempts.setdefault(peer, deque())
        while attempts and attempts[0] <= now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.")
        attempts.append(now)

    def authenticate(self, username: str, password: str) -> StaffAccount | None:
        if not self.accounts:
            return None
        account = self.accounts.get(normalize(username))
        try:
            hasher.verify(account.password_hash if account else self.dummy_hash, password)
        except (VerificationError, InvalidHashError):
            return None
        return account

    def find(self, role: str, token: str) -> StaffAccount | None:
        current = self.active.get(token)
        if current is None:
            return None
        account, expires = current
        if expires <= monotonic():
            self.active.pop(token, None)
            return None
        return account if account.role == role else None

    def revoke(self, role: str, token: str) -> None:
        if self.find(role, token):
            self.active.pop(token, None)

    def issue(self, account: StaffAccount, current: str) -> str:
        now = monotonic()
        self.revoke(account.role, current)
        self.active = {key: entry for key, entry in self.active.items() if entry[1] > now}
        token = token_urlsafe(32)
        self.active[token] = account, now + SESSION_SECONDS
        return token


def cookie(role: str) -> str:
    return f"de261_staff_{role}_session"


def sessions_for(request: Request) -> StaffSessions | None:
    return getattr(request.app.state, "staff_sessions", None)


def same_origin(request: Request, sessions: StaffSessions) -> None:
    expected = sessions.origin or f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("origin") != expected:
        raise HTTPException(403, "Use the app to perform this action")


def unauthenticated() -> HTTPException:
    return HTTPException(401, "Sign in to continue", headers={"WWW-Authenticate": "Bearer"})


async def principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if "authorization" in request.headers:
        if credentials is None:
            raise unauthenticated()
        try:
            accounts = json.loads(settings().auth)
            if not isinstance(accounts, dict):
                raise ValueError("Expected a mapping")
            for token, account in accounts.items():
                if hmac.compare_digest(token.encode(), credentials.credentials.encode()):
                    return Principal(
                        account["id"],
                        account["role"],
                        account.get("courses", []),
                        account.get("organisations", []),
                    )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, "Analytics authentication is not configured") from exc
        raise unauthenticated()
    role = request.headers.get(ROLE_HEADER, "")
    sessions = sessions_for(request)
    if sessions is None or role not in ROLES:
        raise unauthenticated()
    account = sessions.find(role, request.cookies.get(cookie(role), ""))
    if account is None:
        raise unauthenticated()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        same_origin(request, sessions)
    return account.principal()


User = Annotated[Principal, Depends(principal)]


def require_role(user: Principal, role: StaffRole) -> Principal:
    if user.role != role:
        log.warning("Staff role check rejected", required_role=role)
        raise HTTPException(403, f"{role.capitalize()} access required")
    return user


def instructor(user: User) -> Principal:
    return require_role(user, "instructor")


def advisor(user: User) -> Principal:
    return require_role(user, "advisor")


def admin(user: User) -> Principal:
    return require_role(user, "admin")


Instructor = Annotated[Principal, Depends(instructor)]
Advisor = Annotated[Principal, Depends(advisor)]
Admin = Annotated[Principal, Depends(admin)]


def scope(user: Principal, course_id: str) -> None:
    if course_id not in user.courses:
        raise HTTPException(403, "Course is outside your authorized scope")


def organisation_scope(user: Principal, organisation_id: str) -> None:
    if organisation_id not in user.organisations:
        raise HTTPException(403, "Organisation is outside your authorized scope")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate a pre-provisioned staff account")
    parser.add_argument("role", choices=ROLES)
    parser.add_argument("username")
    parser.add_argument("id")
    parser.add_argument("name")
    parser.add_argument("--course", action="append", default=[])
    parser.add_argument("--organisation", action="append", default=[])
    args = parser.parse_args()
    password = getpass("Password (12-128 characters): ")
    if not 12 <= len(password) <= 128:
        parser.error("Password must contain 12-128 characters")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match")
    raw = json.dumps(
        [
            {
                "username": normalize(args.username),
                "id": args.id,
                "name": args.name,
                "role": args.role,
                "password_hash": hasher.hash(password),
                "courses": args.course,
                "organisations": args.organisation,
            }
        ]
    )
    try:
        account_config(raw)
    except ValueError as exc:
        parser.error(str(exc))
    print(raw)


if __name__ == "__main__":
    main()
