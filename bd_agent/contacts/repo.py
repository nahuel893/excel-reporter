"""bd_agent/contacts/repo.py — JsonContactsRepo: implements ContactsRepo Protocol.

Loads and validates contacts from a JSON file. Supports hot-reload (RF-002).
On reload failure, retains the previous valid state (RF-003/S2).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from bd_agent.contacts.schema import ContactsFile, ContactsSchemaError
from bd_agent.contracts import Contact, Permission

logger = logging.getLogger(__name__)


def _parse_contact(model) -> Contact:
    """Convert a ContactModel pydantic instance to a Contact frozen dataclass."""
    return Contact(
        name=model.name,
        jid=model.jid,
        daily_message_limit=model.daily_message_limit,
        permissions=tuple(model.permissions),
        cargo=model.cargo,
    )


class JsonContactsRepo:
    """ContactsRepo implementation backed by a JSON file.

    - First load happens in __init__ and raises if invalid.
    - reload() re-reads the file; on error, logs and retains the previous state.
    - All lookups operate on an in-memory dict for O(1) access.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._contacts: dict[str, Contact] = {}
        # First load — raise if invalid (no previous state to fall back to)
        self._load_or_raise()

    # ------------------------------------------------------------------
    # Public API — satisfies ContactsRepo Protocol
    # ------------------------------------------------------------------

    def get(self, jid: str) -> Optional[Contact]:
        """Return the Contact for a given JID, or None if not found (RF-001)."""
        return self._contacts.get(jid)

    def list_all(self) -> list[Contact]:
        """Return all contacts (used by greeting scheduler)."""
        return list(self._contacts.values())

    def reload(self) -> None:
        """Re-read the JSON file and atomically swap the contact dict (RF-002).

        If the file is invalid, logs the error and keeps the previous state (RF-003/S2).
        """
        try:
            new_contacts = self._read_and_parse()
            self._contacts = new_contacts
            logger.info("contacts.reload: loaded %d contacts from %s", len(new_contacts), self._path)
        except Exception as exc:
            logger.error(
                "contacts.reload: failed to reload %s — retaining previous state. Error: %s",
                self._path,
                exc,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_or_raise(self) -> None:
        """Load contacts on first init; raises on any error (no fallback state yet)."""
        self._contacts = self._read_and_parse()
        logger.info("contacts: loaded %d contacts from %s", len(self._contacts), self._path)

    def _read_and_parse(self) -> dict[str, Contact]:
        """Read, JSON-parse, schema-validate, and return a JID → Contact dict.

        Raises ContactsSchemaError or json.JSONDecodeError on failure.
        """
        raw = self._path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContactsSchemaError(
                f"contactos_agente.json is not valid JSON: {exc}"
            ) from exc

        contacts_file = ContactsFile.model_validate(data)
        return {
            model.jid: _parse_contact(model)
            for model in contacts_file.contacts
        }
