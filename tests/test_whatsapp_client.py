"""Tests para WhatsAppClient."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.whatsapp_client import WhatsAppClient


BASE_URL = "http://localhost:3000"


class TestWhatsAppClientSendImage:
    def test_send_image_uses_httpx_when_available(self, tmp_path):
        img = tmp_path / "captura.png"
        img.write_bytes(b"fake-png")

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True, "message": "ok"}

        mock_client_instance = MagicMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.Client.return_value = mock_client_instance
        mock_httpx.ConnectError = ConnectionError
        mock_httpx.HTTPError = Exception

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            client = WhatsAppClient(BASE_URL)
            result = client.send_image("Grupo Ventas", img, caption="Hola")

        assert result["success"] is True

        call_args = mock_client_instance.post.call_args
        assert call_args[0][0] == f"{BASE_URL}/send-image"
        assert call_args[1]["data"]["group_name"] == "Grupo Ventas"
        assert call_args[1]["data"]["caption"] == "Hola"
        assert "image" in call_args[1]["files"]

    def test_send_file_uses_correct_endpoint(self, tmp_path):
        xlsx = tmp_path / "reporte.xlsx"
        xlsx.write_bytes(b"fake-xlsx")

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True, "message": "ok"}

        mock_client_instance = MagicMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.Client.return_value = mock_client_instance
        mock_httpx.ConnectError = ConnectionError
        mock_httpx.HTTPError = Exception

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            client = WhatsAppClient(BASE_URL)
            result = client.send_file("Grupo Test", xlsx)

        call_args = mock_client_instance.post.call_args
        assert call_args[0][0] == f"{BASE_URL}/send-file"
        assert "file" in call_args[1]["files"]

    def test_connection_error_raised_on_connect_failure(self, tmp_path):
        img = tmp_path / "img.png"
        img.write_bytes(b"x")

        class FakeConnectError(Exception):
            pass

        mock_httpx = MagicMock()
        mock_httpx.ConnectError = FakeConnectError
        mock_httpx.HTTPError = Exception

        mock_client_instance = MagicMock()
        mock_client_instance.post.side_effect = FakeConnectError("refused")
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_httpx.Client.return_value = mock_client_instance

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            client = WhatsAppClient(BASE_URL)
            with pytest.raises(ConnectionError, match="No se pudo conectar"):
                client.send_image("Grupo", img)


class TestWhatsAppClientUrllibFallback:
    def test_falls_back_to_urllib_when_httpx_missing(self, tmp_path):
        img = tmp_path / "img.png"
        img.write_bytes(b"fake-png")

        import json
        fake_response_body = json.dumps({"success": True, "message": "ok"}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.dict("sys.modules", {"httpx": None}),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            client = WhatsAppClient(BASE_URL)
            result = client._post_with_urllib(
                url=f"{BASE_URL}/send-image",
                group_name="Grupo",
                file_path=img,
                file_field="image",
                caption="",
            )

        assert result["success"] is True

    def test_urllib_raises_connection_error_on_url_error(self, tmp_path):
        img = tmp_path / "img.png"
        img.write_bytes(b"x")

        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            client = WhatsAppClient(BASE_URL)
            with pytest.raises(ConnectionError):
                client._post_with_urllib(
                    url=f"{BASE_URL}/send-image",
                    group_name="Grupo",
                    file_path=img,
                    file_field="image",
                    caption="",
                )


class TestWhatsAppClientBaseUrl:
    def test_trailing_slash_stripped(self):
        client = WhatsAppClient("http://localhost:3000/")
        assert client.base_url == "http://localhost:3000"


class TestWhatsAppClientSendText:
    """The /send-text endpoint rejects (400) any `to` that does not end in
    '@s.whatsapp.net' (see whatsapp-service lib/api.js). send_text must
    normalize bare phone numbers so callers can pass either form."""

    @staticmethod
    def _mock_httpx():
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_client_instance = MagicMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_httpx = MagicMock()
        mock_httpx.Client.return_value = mock_client_instance
        mock_httpx.ConnectError = ConnectionError
        mock_httpx.HTTPError = Exception
        return mock_httpx, mock_client_instance

    def test_bare_phone_number_gets_jid_suffix(self):
        """REGRESSION: a bare number used to 400 — the RAM-guard alert never
        reached Nahuel on 2026-07-28 because of this."""
        mock_httpx, mock_client = self._mock_httpx()
        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            WhatsAppClient(BASE_URL).send_text(target="5493876008331", text="hola")

        body = mock_client.post.call_args[1]["json"]
        assert body["to"] == "5493876008331@s.whatsapp.net"
        assert body["text"] == "hola"

    def test_existing_jid_is_not_double_suffixed(self):
        mock_httpx, mock_client = self._mock_httpx()
        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            WhatsAppClient(BASE_URL).send_text(
                target="5493876008331@s.whatsapp.net", text="hola"
            )

        assert mock_client.post.call_args[1]["json"]["to"] == "5493876008331@s.whatsapp.net"

    def test_group_name_path_is_untouched(self):
        mock_httpx, mock_client = self._mock_httpx()
        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            WhatsAppClient(BASE_URL).send_text(text="hola", group_name="Preventa Salta")

        body = mock_client.post.call_args[1]["json"]
        assert body["group_name"] == "Preventa Salta"
        assert "to" not in body


class TestMimetype:
    """El deck mensual va en .pptx y sin su mimetype el celular lo muestra como
    archivo generico en vez de PowerPoint."""

    def test_pptx_va_como_powerpoint(self):
        assert WhatsAppClient._guess_mimetype(Path("deck.pptx")) == (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )

    def test_una_extension_desconocida_cae_en_octet_stream(self):
        assert WhatsAppClient._guess_mimetype(Path("cosa.raro")) == "application/octet-stream"
