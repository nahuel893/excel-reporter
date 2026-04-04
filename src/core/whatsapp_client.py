"""
WhatsAppClient - Cliente HTTP para el microservicio Baileys.

Envia mensajes de WhatsApp a grupos o contactos individuales
a traves del microservicio Node.js + Baileys en whatsapp-service/.

Usa httpx si esta disponible, con fallback a urllib.request (stdlib).
"""
import io
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class WhatsAppClient:
    """Cliente HTTP para el microservicio Baileys de WhatsApp."""

    def __init__(self, base_url: str):
        """
        Args:
            base_url: URL base del microservicio (ej: "http://localhost:3000")
        """
        self.base_url = base_url.rstrip("/")

    def send_image(
        self,
        group_name: str,
        image_path: Path,
        caption: str = "",
    ) -> dict:
        """
        Envia una imagen a un grupo o contacto de WhatsApp.

        Args:
            group_name: Nombre del grupo o contacto
            image_path: Path a la imagen PNG/JPG
            caption: Texto opcional que acompana la imagen

        Returns:
            Dict con { "success": bool, "message": str }

        Raises:
            ConnectionError: Si el microservicio no esta disponible
        """
        return self._post_multipart(
            endpoint="/send-image",
            group_name=group_name,
            file_path=Path(image_path),
            file_field="image",
            caption=caption,
        )

    def send_file(
        self,
        group_name: str,
        file_path: Path,
        caption: str = "",
    ) -> dict:
        """
        Envia un archivo a un grupo o contacto de WhatsApp.

        Args:
            group_name: Nombre del grupo o contacto
            file_path: Path al archivo (xlsx, pdf, etc.)
            caption: Texto opcional que acompana el archivo

        Returns:
            Dict con { "success": bool, "message": str }

        Raises:
            ConnectionError: Si el microservicio no esta disponible
        """
        return self._post_multipart(
            endpoint="/send-file",
            group_name=group_name,
            file_path=Path(file_path),
            file_field="file",
            caption=caption,
        )

    def _post_multipart(
        self,
        endpoint: str,
        group_name: str,
        file_path: Path,
        file_field: str,
        caption: str,
    ) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            return self._post_with_httpx(url, group_name, file_path, file_field, caption)
        except ImportError:
            return self._post_with_urllib(url, group_name, file_path, file_field, caption)

    def _post_with_httpx(
        self,
        url: str,
        group_name: str,
        file_path: Path,
        file_field: str,
        caption: str,
    ) -> dict:
        import httpx

        with open(file_path, "rb") as f:
            file_content = f.read()

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    url,
                    data={"group_name": group_name, "caption": caption},
                    files={file_field: (file_path.name, file_content)},
                )
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError as exc:
            raise ConnectionError(
                f"No se pudo conectar al microservicio WhatsApp en {self.base_url}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Error HTTP al enviar WhatsApp: {exc}") from exc

    def _post_with_urllib(
        self,
        url: str,
        group_name: str,
        file_path: Path,
        file_field: str,
        caption: str,
    ) -> dict:
        import urllib.error
        import urllib.request

        boundary = "----FormBoundary7MA4YWxkTrZu0gW"

        with open(file_path, "rb") as f:
            file_content = f.read()

        body_parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"group_name\"\r\n\r\n{group_name}".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}".encode(),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{file_field}"; filename="{file_path.name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode() + file_content,
            f"--{boundary}--".encode(),
        ]
        body = b"\r\n".join(body_parts)

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.URLError as exc:
            raise ConnectionError(
                f"No se pudo conectar al microservicio WhatsApp en {self.base_url}: {exc}"
            ) from exc
