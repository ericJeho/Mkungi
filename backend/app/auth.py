"""Verify Supabase Auth session tokens sent by the web app.

The browser signs in with supabase-js and sends its access token as
``Authorization: Bearer <jwt>``. Tokens signed with an asymmetric key (ES256 /
RS256, Supabase's "JWT signing keys") are verified locally against the
project's published public keys. Tokens signed with the legacy shared secret
can't be checked without that secret, so they are validated by asking
Supabase Auth instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import jwt

ASYMMETRIC = ("ES256", "RS256", "EdDSA")
JWKS_TTL_SECONDS = 600


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class User:
    id: str
    email: str | None = None


class SupabaseAuth:
    def __init__(self, url: str, api_key: str, client: httpx.Client | None = None) -> None:
        self.issuer = f"{url.rstrip('/')}/auth/v1"
        self.api_key = api_key
        self.http = client or httpx.Client(timeout=10)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0

    def _signing_key(self, kid: str | None) -> jwt.PyJWK:
        stale = time.monotonic() - self._fetched_at > JWKS_TTL_SECONDS
        if stale or kid not in self._keys:
            # Refetch on an unknown kid too, so a freshly rotated key works at once.
            r = self.http.get(f"{self.issuer}/.well-known/jwks.json")
            r.raise_for_status()
            keys = {}
            for k in r.json().get("keys", []):
                try:
                    keys[k.get("kid")] = jwt.PyJWK(k)
                except jwt.PyJWKError:
                    continue  # algorithm this library can't use; skip it
            self._keys, self._fetched_at = keys, time.monotonic()
        if kid not in self._keys:
            raise InvalidToken("Unknown signing key")
        return self._keys[kid]

    def verify(self, token: str) -> User:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidToken("Malformed token") from exc

        if header.get("alg") in ASYMMETRIC:
            key = self._signing_key(header.get("kid"))
            try:
                claims = jwt.decode(
                    token,
                    key.key,
                    algorithms=[header["alg"]],
                    audience="authenticated",
                    issuer=self.issuer,
                    options={"require": ["exp", "sub"]},
                )
            except jwt.PyJWTError as exc:
                raise InvalidToken(str(exc)) from exc
            if claims.get("role") != "authenticated":
                raise InvalidToken("Not a signed-in user")
            return User(id=claims["sub"], email=claims.get("email"))

        # Legacy shared-secret token: Supabase Auth checks it for us.
        r = self.http.get(
            f"{self.issuer}/user",
            headers={"apikey": self.api_key, "Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            raise InvalidToken("Session is not valid")
        data = r.json()
        return User(id=data["id"], email=data.get("email"))
