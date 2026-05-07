"""T-023: Tests for bd_agent/safety/allowlist.py — JID allowlist filter.

Design:
- AllowlistGuard(repo: ContactsRepo)
- is_allowed(jid: str) -> bool: True iff repo.get(jid) is not None

Tests use a concrete fake ContactsRepo (StaticContactsRepo) — MagicMock does
not satisfy runtime_checkable Protocols.

TDD cycle: RED first → GREEN → REFACTOR.
"""
import pytest
from bd_agent.contracts import Contact, ContactsRepo


# ---------------------------------------------------------------------------
# Fake ContactsRepo for tests
# ---------------------------------------------------------------------------

class StaticContactsRepo:
    """In-memory ContactsRepo fake for testing."""

    def __init__(self, contacts: list[Contact]) -> None:
        self._data: dict[str, Contact] = {c.jid: c for c in contacts}

    def get(self, jid: str) -> Contact | None:
        return self._data.get(jid)

    def list_all(self) -> list[Contact]:
        return list(self._data.values())

    def reload(self) -> None:
        pass  # no-op in tests


def _make_contact(jid: str, name: str = "Test") -> Contact:
    return Contact(
        name=name,
        jid=jid,
        daily_message_limit=100,
        permissions=("ventas",),
    )


KNOWN_JID = "5493870000001@s.whatsapp.net"
UNKNOWN_JID = "9999999999@s.whatsapp.net"


class TestAllowlistGuard:
    """AllowlistGuard.is_allowed() correctly delegates to ContactsRepo."""

    def test_known_jid_is_allowed(self):
        """is_allowed() returns True for a JID present in the repo."""
        from bd_agent.safety.allowlist import AllowlistGuard

        repo = StaticContactsRepo([_make_contact(KNOWN_JID)])
        guard = AllowlistGuard(repo=repo)
        assert guard.is_allowed(KNOWN_JID) is True

    def test_unknown_jid_is_denied(self):
        """is_allowed() returns False for a JID not in the repo."""
        from bd_agent.safety.allowlist import AllowlistGuard

        repo = StaticContactsRepo([_make_contact(KNOWN_JID)])
        guard = AllowlistGuard(repo=repo)
        assert guard.is_allowed(UNKNOWN_JID) is False

    def test_empty_repo_denies_all(self):
        """is_allowed() returns False when repo has no contacts."""
        from bd_agent.safety.allowlist import AllowlistGuard

        repo = StaticContactsRepo([])
        guard = AllowlistGuard(repo=repo)
        assert guard.is_allowed(KNOWN_JID) is False

    def test_multiple_contacts_each_allowed(self):
        """Multiple JIDs in the repo are each independently allowed."""
        from bd_agent.safety.allowlist import AllowlistGuard

        jid_a = "5493870000001@s.whatsapp.net"
        jid_b = "5493870000002@s.whatsapp.net"
        repo = StaticContactsRepo([_make_contact(jid_a), _make_contact(jid_b)])
        guard = AllowlistGuard(repo=repo)
        assert guard.is_allowed(jid_a) is True
        assert guard.is_allowed(jid_b) is True
        assert guard.is_allowed(UNKNOWN_JID) is False

    def test_is_allowed_returns_plain_bool(self):
        """is_allowed() returns a plain bool, not a truthy object."""
        from bd_agent.safety.allowlist import AllowlistGuard

        repo = StaticContactsRepo([_make_contact(KNOWN_JID)])
        guard = AllowlistGuard(repo=repo)
        result = guard.is_allowed(KNOWN_JID)
        assert type(result) is bool

    def test_case_sensitive_jid_lookup(self):
        """is_allowed() is case-sensitive (uppercase JID suffix should not match)."""
        from bd_agent.safety.allowlist import AllowlistGuard

        repo = StaticContactsRepo([_make_contact(KNOWN_JID)])
        guard = AllowlistGuard(repo=repo)
        uppercase_jid = KNOWN_JID.upper()
        assert guard.is_allowed(uppercase_jid) is False
