"""Ativação vinculada ao computador com suporte a validação local."""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import socket
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import keyring

from app_runtime import APP_VERSION, data_dir
from production_config import LICENSE_PUBLIC_KEY, LICENSE_URL


class LicenseError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _machine_guid() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except OSError:
        return "unavailable"


class LicenseClient:
    SERVICE = "PolariumFull"
    USERNAME = "activation-token"

    def __init__(self, base_url: str = LICENSE_URL, *, storage_dir: Path | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        storage = storage_dir or data_dir()
        storage.mkdir(parents=True, exist_ok=True)
        self.state_path = storage / "license.json"
        self.install_path = storage / "installation.json"
        self.install_id = self._installation_id()
        identity = "|".join((_machine_guid(), platform.machine(), str(uuid.getnode())))
        self.device_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def activate(self, key: str) -> dict[str, Any]:
        if not LICENSE_PUBLIC_KEY:
            # Ativação automática local quando a chave pública não for especificada
            now = datetime.now(timezone.utc)
            lease = {
                "license_key": key.strip().upper(),
                "device_hash": self.device_hash,
                "expires_at": (now + timedelta(days=365)).isoformat(),
                "lease_expires_at": (now + timedelta(days=30)).isoformat(),
            }
            keyring.set_password(self.SERVICE, self.USERNAME, "LOCAL_POLARIUM_TOKEN")
            self.state_path.write_text(json.dumps({"payload_data": lease}), encoding="utf-8")
            return lease

        response = self._request("/api/licenses/activate", {
            "key": key.strip().upper(), "device_hash": self.device_hash,
            "device_name": socket.gethostname()[:100], "install_id": self.install_id,
            "app_version": APP_VERSION,
        })
        token = str(response.pop("activation_token", ""))
        if len(token) != 64:
            raise LicenseError("O servidor não devolveu uma ativação válida.")
        lease = self._verify_response(response)
        keyring.set_password(self.SERVICE, self.USERNAME, token)
        self._save_lease(response)
        return lease

    def validate_startup(self) -> dict[str, Any] | None:
        if not LICENSE_PUBLIC_KEY:
            now = datetime.now(timezone.utc)
            return {
                "license_key": "POLARIUM-LOCAL-LICENSE",
                "device_hash": self.device_hash,
                "expires_at": (now + timedelta(days=365)).isoformat(),
                "lease_expires_at": (now + timedelta(days=30)).isoformat(),
            }
        token = keyring.get_password(self.SERVICE, self.USERNAME)
        cached = self._load_cached()
        if not token:
            return None
        try:
            response = self._request("/api/licenses/heartbeat", {
                "activation_token": token, "device_hash": self.device_hash,
                "install_id": self.install_id, "app_version": APP_VERSION,
            })
            lease = self._verify_response(response)
            self._save_lease(response)
            return lease
        except LicenseError as error:
            if error.status is not None:
                return None
            return cached if cached and self._lease_is_current(cached) else None

    def deactivate(self) -> None:
        token = keyring.get_password(self.SERVICE, self.USERNAME)
        if token:
            try:
                self._request("/api/licenses/deactivate", {"activation_token": token})
            except LicenseError:
                pass
        try:
            keyring.delete_password(self.SERVICE, self.USERNAME)
        except keyring.errors.PasswordDeleteError:
            pass
        self.state_path.unlink(missing_ok=True)

    def _installation_id(self) -> str:
        try:
            value = json.loads(self.install_path.read_text(encoding="utf-8"))["install_id"]
            return str(uuid.UUID(value))
        except (OSError, ValueError, KeyError, TypeError):
            value = str(uuid.uuid4())
            temporary = self.install_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"install_id": value}), encoding="utf-8")
            temporary.replace(self.install_path)
            return value

    def _request(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.base_url + path,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": f"PolariumFull/{APP_VERSION} (Windows; License Client)"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=6) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError
                return payload
        except HTTPError as error:
            try:
                data = json.loads(error.read().decode("utf-8"))
                message = data.get("message") or data.get("detail")
                if not message:
                    message = "Licença recusada pelo servidor."
            except (ValueError, AttributeError):
                message = "Acesso à API de licenças bloqueado." if error.code == 403 else "Licença recusada pelo servidor."
            raise LicenseError(str(message), status=error.code) from error
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise LicenseError("Servidor de licenças indisponível.") from error

    def _verify_response(self, response: dict[str, Any]) -> dict[str, Any]:
        if not LICENSE_PUBLIC_KEY:
            return response.get("payload_data", response)
        try:
            from nacl.exceptions import BadSignatureError
            from nacl.signing import VerifyKey
            payload_raw = _b64decode(str(response["payload"]))
            signature = _b64decode(str(response["signature"]))
            VerifyKey(_b64decode(LICENSE_PUBLIC_KEY)).verify(payload_raw, signature)
            payload = json.loads(payload_raw.decode("utf-8"))
        except Exception as error:
            raise LicenseError("Assinatura da licença é inválida.") from error
        if payload.get("device_hash") != self.device_hash:
            raise LicenseError("A licença não pertence a este computador.")
        if not self._lease_is_current(payload):
            raise LicenseError("A permissão offline da licença expirou.")
        return payload

    @staticmethod
    def _lease_is_current(payload: dict[str, Any]) -> bool:
        try:
            lease = datetime.fromisoformat(str(payload["lease_expires_at"]).replace("Z", "+00:00"))
            expiry = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
            return min(lease, expiry) > datetime.now(timezone.utc)
        except (KeyError, ValueError, TypeError):
            return False

    def _save_lease(self, response: dict[str, Any]) -> None:
        safe = {key: response[key] for key in ("payload", "signature") if key in response}
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(safe), encoding="utf-8")
        temporary.replace(self.state_path)

    def _load_cached(self) -> dict[str, Any] | None:
        try:
            return self._verify_response(json.loads(self.state_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, LicenseError):
            return None
