"""CRM integration: a small provider-agnostic interface plus a HubSpot implementation.

Scoped deliberately small for the MVP: push a call's post-call summary as a
standalone Note in the CRM. No contact matching/association yet (we don't have
the prospect's CRM record id), and auth is a HubSpot Private App token (pasted
by the org admin) rather than a full OAuth flow — the simplest thing that lets
a team try this without building an OAuth app registration first. Both are
natural follow-ups, not a ceiling: the interface doesn't assume either choice.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import httpx


class CRMError(Exception):
    """Raised when a CRM API call fails; message is safe to surface to the admin."""


class CRMProvider(ABC):
    @abstractmethod
    async def test_connection(self) -> None:
        """Raise CRMError if the credential is invalid or the API is unreachable."""

    @abstractmethod
    async def push_call_note(self, body: str, call_time: datetime) -> None:
        """Create a note in the CRM summarizing one call. Raise CRMError on failure."""


class HubSpotProvider(CRMProvider):
    BASE_URL = "https://api.hubapi.com"

    def __init__(self, private_app_token: str):
        self.token = private_app_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    async def test_connection(self) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.BASE_URL}/crm/v3/objects/notes?limit=1", headers=self._headers())
        if resp.status_code == 401:
            raise CRMError("HubSpot rejected the token — check it's a valid Private App access token.")
        if resp.status_code >= 400:
            raise CRMError(f"HubSpot connection test failed ({resp.status_code}): {resp.text[:200]}")

    async def push_call_note(self, body: str, call_time: datetime) -> None:
        payload = {
            "properties": {
                "hs_note_body": body,
                "hs_timestamp": int(call_time.timestamp() * 1000),
            }
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.BASE_URL}/crm/v3/objects/notes", headers=self._headers(), json=payload)
        if resp.status_code >= 400:
            raise CRMError(f"HubSpot note creation failed ({resp.status_code}): {resp.text[:200]}")


PROVIDERS: dict[str, type[CRMProvider]] = {"hubspot": HubSpotProvider}


def build_provider(name: str, token: str) -> CRMProvider:
    cls = PROVIDERS.get(name)
    if cls is None:
        raise CRMError(f"Unknown CRM provider '{name}'.")
    return cls(token)
