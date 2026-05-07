"""bd_agent/integrations/messaging.py — WhatsAppMessagingGateway (T-071).

Concrete implementation of MessagingGateway that delivers outbound messages via
the local Baileys Node service (whatsapp-service/index.js).

Design rules:
  - Posts to ``{base_url}/send-text`` with JSON body ``{jid, text}``.
  - Uses httpx for HTTP transport; caller can inject a custom client for testing.
  - Raises RuntimeError on non-2xx responses (caller decides retry strategy).
  - Zero imports from src.* (RF-070).
  - Self-contained — no dependency on src.core.whatsapp_client.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class WhatsAppMessagingGateway:
    """Outbound WhatsApp message transport via the local Baileys HTTP service.

    Args:
        base_url: Base URL of the Baileys Node service
            (e.g. ``"http://localhost:3000"``).
        http_client: Optional injected httpx.Client (for testing / reuse).
            If ``None``, a new client is created with a 15-second timeout.
    """

    _SEND_PATH = "/send-text"

    def __init__(
        self,
        base_url: str,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client: httpx.Client = (
            http_client
            if http_client is not None
            else httpx.Client(timeout=15.0)
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
        url = f"{self._base_url}{self._SEND_PATH}"
        payload = {"jid": jid, "text": text}

        logger.debug("send_text: posting to %s for jid_prefix=%s", url, jid[:12])
        response = self._client.post(url, json=payload)

        if not (200 <= response.status_code < 300):
            raise RuntimeError(
                f"WhatsApp service returned HTTP {response.status_code} "
                f"when sending to jid_prefix={jid[:12]}. Body: {response.text[:200]}"
            )
