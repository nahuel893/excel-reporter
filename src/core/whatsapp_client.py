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

    def send_text(
        self,
        target: str = "",
        text: str = "",
        group_name: str | None = None,
    ) -> dict:
        """Envia un mensaje de texto a un grupo o contacto."""
        import httpx

        data = {}
        if group_name:
            data["group_name"] = group_name
        else:
            data["to"] = self._normalize_dm_jid(target)
        data["text"] = text

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(f"{self.base_url}/send-text", json=data)
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError as exc:
            raise ConnectionError(
                f"No se pudo conectar al microservicio WhatsApp en {self.base_url}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Error HTTP al enviar WhatsApp: {exc}") from exc

    @staticmethod
    def _normalize_dm_jid(target: str) -> str:
        """Append the DM JID domain to a bare phone number.

        The /send-text endpoint rejects with 400 any `to` that does not end in
        '@s.whatsapp.net' (whatsapp-service lib/api.js). Callers naturally pass
        the bare number from the contacts catalog, so normalize here. Targets
        that already carry a JID domain (including group '@g.us') pass through
        untouched.
        """
        if target and "@" not in target:
            return f"{target}@s.whatsapp.net"
        return target

    def send_image(
        self,
        target: str,
        image_path: Path | str,
        caption: str = "",
        group_name: str | None = None,
    ) -> dict:
        """
        Envia una imagen a un grupo o contacto de WhatsApp.

        Args:
            target: Nombre del grupo o numero de contacto
            image_path: Path a la imagen PNG/JPG
            caption: Texto opcional que acompana la imagen
            group_name: Si se pasa, se envia al grupo por nombre en vez de DM

        Returns:
            Dict con { "success": bool, "message": str }

        Raises:
            ConnectionError: Si el microservicio no esta disponible
        """
        return self._post_multipart(
            endpoint="/send-image",
            target=target,
            file_path=Path(image_path),
            file_field="image",
            caption=caption,
            group_name=group_name,
        )

    def send_file(
        self,
        target: str,
        file_path: Path,
        caption: str = "",
        group_name: str | None = None,
    ) -> dict:
        """
        Envia un archivo a un grupo o contacto de WhatsApp.

        Args:
            target: Nombre del grupo o numero de contacto
            file_path: Path al archivo (xlsx, pdf, etc.)
            caption: Texto opcional que acompana el archivo
            group_name: Si se pasa, se envia al grupo por nombre en vez de DM

        Returns:
            Dict con { "success": bool, "message": str }

        Raises:
            ConnectionError: Si el microservicio no esta disponible
        """
        return self._post_multipart(
            endpoint="/send-file",
            target=target,
            file_path=Path(file_path),
            file_field="file",
            caption=caption,
            group_name=group_name,
        )

    @staticmethod
    def _guess_mimetype(file_path: Path) -> str:
        """Guess MIME type from file extension."""
        suffix = Path(file_path).suffix.lower()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pdf": "application/pdf",
        }.get(suffix, "application/octet-stream")

    def _post_multipart(
        self,
        endpoint: str,
        target: str,
        file_path: Path,
        file_field: str,
        caption: str,
        group_name: str | None = None,
    ) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            return self._post_with_httpx(url, target, file_path, file_field, caption, group_name=group_name)
        except ImportError:
            return self._post_with_urllib(url, target, file_path, file_field, caption, group_name=group_name)

    def _post_with_httpx(
        self,
        url: str,
        target: str,
        file_path: Path,
        file_field: str,
        caption: str,
        group_name: str | None = None,
    ) -> dict:
        import httpx

        with open(file_path, "rb") as f:
            file_content = f.read()

        try:
            with httpx.Client(timeout=30) as client:
                data = {"caption": caption}
                if group_name:
                    data["group_name"] = group_name
                else:
                    data["to"] = target
                response = client.post(
                    url,
                    data=data,
                    files={file_field: (file_path.name, file_content, self._guess_mimetype(file_path))},
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
        target: str,
        file_path: Path,
        file_field: str,
        caption: str,
        group_name: str | None = None,
    ) -> dict:
        import urllib.error
        import urllib.request

        boundary = "----FormBoundary7MA4YWxkTrZu0gW"

        with open(file_path, "rb") as f:
            file_content = f.read()

        target_field = f"group_name" if group_name else "to"
        target_value = group_name if group_name else target

        body_parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{target_field}\"\r\n\r\n{target_value}".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}".encode(),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{file_field}"; filename="{file_path.name}"\r\n'
                f"Content-Type: {self._guess_mimetype(file_path)}\r\n\r\n"
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
