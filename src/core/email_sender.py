"""
EmailSender - Envio de emails con adjuntos via SMTP.

Usa exclusivamente la stdlib de Python (smtplib + email.mime).
Soporta TLS (SMTP + starttls) y SSL (SMTP_SSL) segun configuracion.
"""
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from config.settings import SMTP_CONFIG

logger = logging.getLogger(__name__)


class EmailSender:
    """Envia emails con adjuntos opcionales via SMTP."""

    def __init__(self, config: dict | None = None):
        """
        Args:
            config: Diccionario con host, port, user, password, use_ssl.
                    Si es None, usa SMTP_CONFIG de settings.py.
        """
        self._config = config or SMTP_CONFIG

    def send(
        self,
        destinatarios: list[str],
        asunto: str,
        cuerpo: str,
        adjuntos: list[Path] | None = None,
        cc: list[str] | None = None,
    ) -> None:
        """
        Envia un email con adjuntos opcionales.

        Args:
            destinatarios: Lista de direcciones de email
            asunto: Asunto del email
            cuerpo: Cuerpo del email en texto plano
            adjuntos: Lista de paths a archivos para adjuntar
            cc: Lista de direcciones en copia

        Raises:
            smtplib.SMTPException: Si el envio falla (logeado, re-raised)
        """
        msg = MIMEMultipart()
        msg["From"] = self._config["user"]
        msg["To"] = ", ".join(destinatarios)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = asunto
        msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

        for path in (adjuntos or []):
            path = Path(path)
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)

        host = self._config["host"]
        port = self._config["port"]
        user = self._config["user"]
        password = self._config["password"]
        use_ssl = self._config.get("use_ssl", False)

        all_recipients = destinatarios + (cc or [])

        try:
            if use_ssl:
                with smtplib.SMTP_SSL(host, port) as server:
                    server.login(user, password)
                    server.sendmail(user, all_recipients, msg.as_string())
            else:
                with smtplib.SMTP(host, port) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(user, password)
                    server.sendmail(user, all_recipients, msg.as_string())

            logger.info("Email enviado a %s (cc: %s) | asunto: %s", destinatarios, cc or [], asunto)

        except smtplib.SMTPException as exc:
            logger.error("Error al enviar email: %s", exc)
            raise
