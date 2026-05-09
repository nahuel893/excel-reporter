"""bd_agent/contacts/schema.py — Pydantic models for contactos_agente.json.

Schema validated per RF-080. Raises ContactsSchemaError on any violation
so callers get a single exception type to catch (RF-003).
"""
from __future__ import annotations

from typing import Literal

import pydantic
from pydantic import BaseModel, field_validator, model_validator


Permission = Literal["ventas", "clientes", "cobertura", "stock"]


class ContactsSchemaError(ValueError):
    """Raised when contactos_agente.json fails schema validation (RF-003)."""


def _wrap_validation_error(exc: pydantic.ValidationError) -> ContactsSchemaError:
    """Convert a pydantic ValidationError into a ContactsSchemaError."""
    return ContactsSchemaError(str(exc))


class ContactModel(BaseModel):
    """A single contact entry — RF-080."""

    name: str
    jid: str
    daily_message_limit: int
    permissions: list[Permission]
    cargo: str | None = None

    @field_validator("jid")
    @classmethod
    def jid_must_be_whatsapp_net(cls, v: str) -> str:
        if not v.endswith("@s.whatsapp.net"):
            raise ValueError(
                f"JID must end with @s.whatsapp.net, got: {v!r}"
            )
        return v

    @field_validator("daily_message_limit")
    @classmethod
    def daily_limit_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                f"daily_message_limit must be >= 0, got: {v}"
            )
        return v


class SettingsModel(BaseModel):
    """Global settings block — RF-080."""

    active_hours_start: str
    active_hours_end: str
    timezone: str

    @field_validator("timezone")
    @classmethod
    def timezone_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("timezone must not be empty")
        return v


class ContactsFile(BaseModel):
    """Root model for contactos_agente.json — RF-080.

    Wraps pydantic ValidationError into ContactsSchemaError so callers
    have a single exception type to catch (RF-003).
    """

    contacts: list[ContactModel]
    settings: SettingsModel

    @model_validator(mode="before")
    @classmethod
    def coerce_and_validate(cls, values: object) -> object:
        # Pre-validation hook; pass through — actual coercion handled by fields.
        return values

    @classmethod
    def model_validate(cls, obj: object, **kwargs) -> "ContactsFile":  # type: ignore[override]
        """Override to raise ContactsSchemaError instead of pydantic.ValidationError."""
        try:
            return super().model_validate(obj, **kwargs)
        except pydantic.ValidationError as exc:
            raise _wrap_validation_error(exc) from exc
