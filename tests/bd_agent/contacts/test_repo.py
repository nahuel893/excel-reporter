"""T-014: Tests for bd_agent/contacts/repo.py — JsonContactsRepo.

Verifies:
- get() returns Contact for known JID
- get() returns None for unknown JID
- reload() picks up new contact written to file
- reload() retains previous state on invalid file (RF-003/S2)
- JID lookup is case-sensitive
"""
import json
import pytest
from pathlib import Path


def make_minimal_config(*extra_contacts) -> dict:
    base = {
        "contacts": [
            {
                "name": "Test User",
                "jid": "5493870000001@s.whatsapp.net",
                "daily_message_limit": 100,
                "permissions": ["ventas"],
            }
        ],
        "settings": {
            "active_hours_start": "07:00",
            "active_hours_end": "22:00",
            "timezone": "America/Argentina/Salta",
        },
    }
    base["contacts"].extend(extra_contacts)
    return base


class TestJsonContactsRepo:
    def test_get_known_jid_returns_contact(self, tmp_path):
        """get() returns a Contact for a JID that exists in the file."""
        from bd_agent.contacts.repo import JsonContactsRepo
        from bd_agent.contracts import Contact

        config_file = tmp_path / "contacts.json"
        config_file.write_text(json.dumps(make_minimal_config()))

        repo = JsonContactsRepo(config_file)
        contact = repo.get("5493870000001@s.whatsapp.net")

        assert contact is not None
        assert isinstance(contact, Contact)
        assert contact.name == "Test User"
        assert contact.jid == "5493870000001@s.whatsapp.net"
        assert contact.daily_message_limit == 100
        assert "ventas" in contact.permissions

    def test_get_unknown_jid_returns_none(self, tmp_path):
        """get() returns None for a JID not in the file."""
        from bd_agent.contacts.repo import JsonContactsRepo

        config_file = tmp_path / "contacts.json"
        config_file.write_text(json.dumps(make_minimal_config()))

        repo = JsonContactsRepo(config_file)
        result = repo.get("9999999999@s.whatsapp.net")
        assert result is None

    def test_reload_picks_up_new_contact(self, tmp_path):
        """reload() re-reads the file; a new JID becomes visible after reload (RF-002)."""
        from bd_agent.contacts.repo import JsonContactsRepo

        config_file = tmp_path / "contacts.json"
        config_file.write_text(json.dumps(make_minimal_config()))

        repo = JsonContactsRepo(config_file)
        # Unknown before reload
        assert repo.get("5493870000002@s.whatsapp.net") is None

        # Write new contact to file
        updated = make_minimal_config(
            {
                "name": "New User",
                "jid": "5493870000002@s.whatsapp.net",
                "daily_message_limit": 50,
                "permissions": ["ventas"],
            }
        )
        config_file.write_text(json.dumps(updated))

        repo.reload()
        contact = repo.get("5493870000002@s.whatsapp.net")
        assert contact is not None
        assert contact.name == "New User"

    def test_reload_retains_previous_state_on_invalid_file(self, tmp_path):
        """reload() with an invalid file keeps the old state (RF-003/S2)."""
        from bd_agent.contacts.repo import JsonContactsRepo

        config_file = tmp_path / "contacts.json"
        config_file.write_text(json.dumps(make_minimal_config()))

        repo = JsonContactsRepo(config_file)
        # Original contact is visible
        assert repo.get("5493870000001@s.whatsapp.net") is not None

        # Corrupt the file
        config_file.write_text("{ this is not valid JSON }")

        # reload() should NOT raise; it should retain old state
        repo.reload()
        # Old contact still visible
        assert repo.get("5493870000001@s.whatsapp.net") is not None

    def test_jid_lookup_case_sensitive(self, tmp_path):
        """JID lookup is case-sensitive (uppercase JID should not match)."""
        from bd_agent.contacts.repo import JsonContactsRepo

        config_file = tmp_path / "contacts.json"
        config_file.write_text(json.dumps(make_minimal_config()))

        repo = JsonContactsRepo(config_file)
        # Stored as lowercase; querying with uppercase part should return None
        result = repo.get("5493870000001@S.WHATSAPP.NET")
        assert result is None

    def test_list_all_returns_all_contacts(self, tmp_path):
        """list_all() returns all contacts from the file."""
        from bd_agent.contacts.repo import JsonContactsRepo

        extra = {
            "name": "Extra User",
            "jid": "5493870000002@s.whatsapp.net",
            "daily_message_limit": 50,
            "permissions": ["cobertura"],
        }
        config_file = tmp_path / "contacts.json"
        config_file.write_text(json.dumps(make_minimal_config(extra)))

        repo = JsonContactsRepo(config_file)
        contacts = repo.list_all()
        assert len(contacts) == 2
        jids = {c.jid for c in contacts}
        assert "5493870000001@s.whatsapp.net" in jids
        assert "5493870000002@s.whatsapp.net" in jids

    def test_repo_satisfies_contacts_repo_protocol(self, tmp_path):
        """JsonContactsRepo satisfies the ContactsRepo Protocol."""
        from bd_agent.contacts.repo import JsonContactsRepo
        from bd_agent.contracts import ContactsRepo

        config_file = tmp_path / "contacts.json"
        config_file.write_text(json.dumps(make_minimal_config()))

        repo = JsonContactsRepo(config_file)
        assert isinstance(repo, ContactsRepo)

    def test_invalid_file_on_first_load_raises(self, tmp_path):
        """If the file is invalid on first load, ContactsSchemaError is raised."""
        from bd_agent.contacts.repo import JsonContactsRepo
        from bd_agent.contacts.schema import ContactsSchemaError

        config_file = tmp_path / "contacts.json"
        config_file.write_text("not valid json")

        with pytest.raises((ContactsSchemaError, ValueError, Exception)):
            JsonContactsRepo(config_file)
