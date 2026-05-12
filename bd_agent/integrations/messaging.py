"""bd_agent/integrations/messaging.py — WhatsAppMessagingGateway (T-071, T-101).

Concrete implementation of MessagingGateway that delivers outbound messages via
the local Baileys Node service (whatsapp-service/index.js).

Design rules:
  - Posts to ``{base_url}/send-text`` with JSON body ``{jid, text}``.
  - Posts to ``{base_url}/send-file-dm`` with multipart form-data for file delivery.
  - Uses httpx for HTTP transport; caller can inject a custom client for testing.
  - Raises RuntimeError on non-2xx responses (caller decides retry strategy).
  - Zero imports from src.* (RF-070).
  - Self-contained — no dependency on src.core.whatsapp_client.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class WhatsAppMessagingGateway:
    """Outbound WhatsApp message transport via the local Baileys HTTP service.

    Args:
        base_url: Base URL of the Baileys Node service
            (e.g. ``"http://localhost:3001"``).
        http_client: Optional injected httpx.Client (for testing / reuse).
            If ``None``, a new client is created with a 15-second timeout.
    """

    _SEND_TEXT_PATH = "/send-text"
    _SEND_FILE_DM_PATH = "/send-file-dm"

    def __init__(
        self,
        base_url: str,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client: httpx.Client = (
            http_client
            if http_client is not None
            else httpx.Client(timeout=30.0)
        )

    # ------------------------------------------------------------------
    # MessagingGateway Protocol
    # ------------------------------------------------------------------

    def send_text(self, jid: str, text: str) -> None:
        """Send a plain-text message to *jid* via the Baileys service.

        Args:
            jid: WhatsApp JID of the recipient (``XXXXXXXXXX@s.whatsapp.net``).
            text: Plain-text message body.

        Raises:
            RuntimeError: If the service returns a non-2xx HTTP status.
            httpx.HTTPError: On network-level failures (connection refused, timeout, etc.).
        """
        url = f"{self._base_url}{self._SEND_TEXT_PATH}"
        payload = {"to": jid, "text": text}

        logger.debug("send_text: posting to %s for jid_prefix=%s", url, jid[:12])
        response = self._client.post(url, json=payload)

        if not (200 <= response.status_code < 300):
            raise RuntimeError(
                f"WhatsApp service returned HTTP {response.status_code} "
                f"when sending to jid_prefix={jid[:12]}. Body: {response.text[:200]}"
            )

    def send_file(
        self,
        jid: str,
        file_path: Path,
        caption: str | None = None,
    ) -> None:
        """Send a binary file as a WhatsApp DM document to *jid*.

        Delivers the file via multipart POST to the Baileys ``/send-file-dm``
        endpoint.

        Args:
            jid: WhatsApp JID of the recipient (``XXXXXXXXXX@s.whatsapp.net``).
            file_path: Local path to the file to send.
            caption: Optional caption to display below the document.

        Raises:
            RuntimeError: If the service returns a non-2xx HTTP status.
            httpx.HTTPError: On network-level failures.
        """
        url = f"{self._base_url}{self._SEND_FILE_DM_PATH}"

        logger.debug(
            "send_file: posting %s to %s for jid_prefix=%s",
            file_path.name,
            url,
            jid[:12],
        )

        file_path = Path(file_path)
        with file_path.open("rb") as fh:
            file_bytes = fh.read()

        # Build multipart form data
        form_data: dict = {"to": (None, jid)}
        if caption is not None:
            form_data["caption"] = (None, caption)
        form_data["file"] = (file_path.name, file_bytes)

        response = self._client.post(url, files=form_data)

        if not (200 <= response.status_code < 300):
            raise RuntimeError(
                f"WhatsApp service returned HTTP {response.status_code} "
                f"when sending file to jid_prefix={jid[:12]}. Body: {response.text[:200]}"
            )
