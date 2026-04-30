"""
Script para testear la conexion SMTP y enviar un correo de prueba.

Uso:
    python scripts/test_email.py

Requiere las variables SMTP_* en el archivo .env
"""
import sys
from pathlib import Path

# Agregar el directorio raiz al path para imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SMTP_CONFIG
from src.core.email_sender import EmailSender


def main():
    user = SMTP_CONFIG["user"]
    host = SMTP_CONFIG["host"]
    port = SMTP_CONFIG["port"]
    use_ssl = SMTP_CONFIG.get("use_ssl", False)
    mode = "SSL" if use_ssl else "TLS"

    if not user:
        print("Error: SMTP_USER no configurado en .env")
        return 1

    if not SMTP_CONFIG.get("password"):
        print("Error: SMTP_PASSWORD no configurado en .env")
        return 1

    print(f"Configuracion SMTP:")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  User: {user}")
    print(f"  Mode: {mode}")
    print()

    print(f"Enviando correo de prueba a {user}...")

    try:
        sender = EmailSender()
        sender.send(
            destinatarios=[user],
            asunto="[Test] Conexion SMTP - Informes Badie",
            cuerpo=(
                "Este es un correo de prueba automatico.\n\n"
                "Si recibis este mail, la configuracion SMTP esta funcionando correctamente.\n\n"
                "-- Informes Badie"
            ),
        )
        print(f"OK: correo enviado a {user}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
