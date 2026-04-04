"""Tests para EmailSender."""
import smtplib
from email import message_from_string
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.core.email_sender import EmailSender

SMTP_CONFIG_TLS = {
    "host": "smtp.example.com",
    "port": 587,
    "user": "user@example.com",
    "password": "secret",
    "use_ssl": False,
}

SMTP_CONFIG_SSL = {
    "host": "smtp.example.com",
    "port": 465,
    "user": "user@example.com",
    "password": "secret",
    "use_ssl": True,
}


class TestEmailSenderTLS:
    def test_sends_via_starttls_when_use_ssl_false(self, tmp_path):
        sender = EmailSender(config=SMTP_CONFIG_TLS)

        mock_smtp = MagicMock()
        mock_smtp_instance = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", mock_smtp):
            sender.send(["dest@example.com"], "Asunto", "Cuerpo")

        mock_smtp.assert_called_once_with("smtp.example.com", 587)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("user@example.com", "secret")
        mock_smtp_instance.sendmail.assert_called_once()

    def test_sends_via_smtp_ssl_when_use_ssl_true(self):
        sender = EmailSender(config=SMTP_CONFIG_SSL)

        mock_smtp_ssl = MagicMock()
        mock_ssl_instance = MagicMock()
        mock_smtp_ssl.return_value.__enter__ = MagicMock(return_value=mock_ssl_instance)
        mock_smtp_ssl.return_value.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP_SSL", mock_smtp_ssl):
            sender.send(["dest@example.com"], "Asunto", "Cuerpo")

        mock_smtp_ssl.assert_called_once_with("smtp.example.com", 465)
        mock_ssl_instance.login.assert_called_once_with("user@example.com", "secret")
        mock_ssl_instance.sendmail.assert_called_once()
        # starttls NO debe llamarse en modo SSL
        mock_ssl_instance.starttls.assert_not_called()


class TestEmailSenderMIME:
    def test_mime_multipart_with_attachment(self, tmp_path):
        """Verifica que el email tiene estructura MIME correcta con adjunto."""
        sender = EmailSender(config=SMTP_CONFIG_TLS)

        adjunto = tmp_path / "reporte.xlsx"
        adjunto.write_bytes(b"fake-excel-content")

        captured_messages = []

        def fake_sendmail(from_addr, to_addrs, msg_string):
            captured_messages.append(msg_string)

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.side_effect = fake_sendmail

        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            sender.send(["dest@example.com"], "Mi Asunto", "Mi Cuerpo", adjuntos=[adjunto])

        assert len(captured_messages) == 1
        msg = message_from_string(captured_messages[0])

        assert msg["Subject"] == "Mi Asunto"
        assert msg["To"] == "dest@example.com"
        assert msg.is_multipart()

        payloads = msg.get_payload()
        assert len(payloads) == 2  # texto + adjunto

        body_part = payloads[0]
        assert body_part.get_content_type() == "text/plain"

        attachment_part = payloads[1]
        assert 'filename="reporte.xlsx"' in attachment_part.get("Content-Disposition", "")

    def test_to_field_has_multiple_recipients(self, tmp_path):
        sender = EmailSender(config=SMTP_CONFIG_TLS)
        captured_messages = []

        def fake_sendmail(from_addr, to_addrs, msg_string):
            captured_messages.append(msg_string)

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.side_effect = fake_sendmail

        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            sender.send(["a@b.com", "c@d.com"], "Asunto", "Cuerpo")

        msg = message_from_string(captured_messages[0])
        assert "a@b.com" in msg["To"]
        assert "c@d.com" in msg["To"]


class TestEmailSenderErrorHandling:
    def test_smtp_auth_failure_logs_and_reraises(self, caplog):
        sender = EmailSender(config=SMTP_CONFIG_TLS)

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.login.side_effect = smtplib.SMTPAuthenticationError(535, "auth failed")

        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(smtplib.SMTPAuthenticationError):
                sender.send(["dest@example.com"], "Asunto", "Cuerpo")
