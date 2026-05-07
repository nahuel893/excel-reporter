"""bd_agent/safety/allowlist.py — JID allowlist filter using ContactsRepo.

Implements RF-001: only JIDs present in ContactsRepo receive any reply.
Any inbound message from an unlisted JID is silently dropped.

is_allowed(jid: str) -> bool: True iff repo.get(jid) is not None.

Zero imports from src.* (RF-070). Deps: bd_agent.contracts (Protocol only).
"""
from __future__ import annotations

from bd_agent.contracts import ContactsRepo


class AllowlistGuard:
    """Checks whether a JID is in the allowlist via ContactsRepo.

    Args:
        repo: a ContactsRepo implementation (injected; not imported directly).
    """

    def __init__(self, repo: ContactsRepo) -> None:
        self._repo = repo

    def is_allowed(self, jid: str) -> bool:
        """Return True iff *jid* is present in the contacts repo (allowlist).

        The lookup is delegated entirely to the repo, which handles hot-reload
        (RF-002) and schema validation (RF-003) transparently.
        """
        return bool(self._repo.get(jid) is not None)
