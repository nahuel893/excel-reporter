"""T-012 + T-013: Tests for contacts schema (pydantic models) and example file.

Verifies:
- configs/contactos_agente.example.json validates against ContactsFile schema
- Invalid JID suffix raises ContactsSchemaError
- Negative daily_message_limit raises ContactsSchemaError
- Missing timezone raises ContactsSchemaError
- Invalid permission string raises ContactsSchemaError
"""
import json
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[3]  # tests/bd_agent/contacts/ -> project root
EXAMPLE_FILE = PROJECT_ROOT / "configs" / "contactos_agente.example.json"


class TestExampleFileValidation:
    def test_example_file_exists(self):
        """The example config file must be present in the repo."""
        assert EXAMPLE_FILE.exists(), f"Missing: {EXAMPLE_FILE}"

    def test_example_file_validates_against_schema(self):
        """The example file must pass ContactsFile pydantic validation."""
        from bd_agent.contacts.schema import ContactsFile
        data = json.loads(EXAMPLE_FILE.read_text())
        # Should not raise
        result = ContactsFile.model_validate(data)
        assert len(result.contacts) >= 1
        assert result.settings.timezone != ""

    def test_example_file_has_valid_jids(self):
        """All JIDs in example file must end with @s.whatsapp.net."""
        from bd_agent.contacts.schema import ContactsFile
        data = json.loads(EXAMPLE_FILE.read_text())
        cf = ContactsFile.model_validate(data)
        for contact in cf.contacts:
            assert contact.jid.endswith("@s.whatsapp.net"), (
                f"JID {contact.jid!r} does not end with @s.whatsapp.net"
            )


class TestContactsSchemaValidation:
    def _make_valid_payload(self):
        return {
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

    def test_valid_payload_parses_correctly(self):
        from bd_agent.contacts.schema import ContactsFile
        payload = self._make_valid_payload()
        cf = ContactsFile.model_validate(payload)
        assert cf.contacts[0].name == "Test User"
        assert cf.settings.timezone == "America/Argentina/Salta"

    def test_negative_daily_limit_raises_contacts_schema_error(self):
        """daily_message_limit: -1 must raise ContactsSchemaError (RF-080/S1)."""
        from bd_agent.contacts.schema import ContactsFile, ContactsSchemaError
        payload = self._make_valid_payload()
        payload["contacts"][0]["daily_message_limit"] = -1
        with pytest.raises(ContactsSchemaError):
            ContactsFile.model_validate(payload)

    def test_missing_timezone_raises_contacts_schema_error(self):
        """Missing settings.timezone must raise ContactsSchemaError (RF-003/S1)."""
        from bd_agent.contacts.schema import ContactsFile, ContactsSchemaError
        payload = self._make_valid_payload()
        del payload["settings"]["timezone"]
        with pytest.raises(ContactsSchemaError):
            ContactsFile.model_validate(payload)

    def test_invalid_jid_suffix_raises_error(self):
        """JID not ending with @s.whatsapp.net must raise ContactsSchemaError."""
        from bd_agent.contacts.schema import ContactsFile, ContactsSchemaError
        payload = self._make_valid_payload()
        payload["contacts"][0]["jid"] = "5493870000001@g.us"  # group JID
        with pytest.raises(ContactsSchemaError):
            ContactsFile.model_validate(payload)

    def test_invalid_permission_raises_error(self):
        """Unknown permission string must raise ContactsSchemaError."""
        from bd_agent.contacts.schema import ContactsFile, ContactsSchemaError
        payload = self._make_valid_payload()
        payload["contacts"][0]["permissions"] = ["ventas", "unknown_perm"]
        with pytest.raises(ContactsSchemaError):
            ContactsFile.model_validate(payload)

    def test_empty_contacts_list_is_valid(self):
        """An empty contacts list is allowed (settings are still required)."""
        from bd_agent.contacts.schema import ContactsFile
        payload = self._make_valid_payload()
        payload["contacts"] = []
        cf = ContactsFile.model_validate(payload)
        assert cf.contacts == []

    def test_zero_daily_limit_is_valid(self):
        """daily_message_limit: 0 is valid (means no messages allowed)."""
        from bd_agent.contacts.schema import ContactsFile
        payload = self._make_valid_payload()
        payload["contacts"][0]["daily_message_limit"] = 0
        cf = ContactsFile.model_validate(payload)
        assert cf.contacts[0].daily_message_limit == 0

    def test_all_permissions_accepted(self):
        """All four allowed permissions must validate without error."""
        from bd_agent.contacts.schema import ContactsFile
        payload = self._make_valid_payload()
        payload["contacts"][0]["permissions"] = ["ventas", "clientes", "cobertura", "stock"]
        cf = ContactsFile.model_validate(payload)
        assert set(cf.contacts[0].permissions) == {"ventas", "clientes", "cobertura", "stock"}

    def test_permissions_stored_as_list(self):
        """Permissions must be returned as a list (not tuple) from pydantic."""
        from bd_agent.contacts.schema import ContactsFile
        payload = self._make_valid_payload()
        cf = ContactsFile.model_validate(payload)
        assert isinstance(cf.contacts[0].permissions, list)
