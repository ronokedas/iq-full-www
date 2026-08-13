"""Login Google interativo no Edge e armazenamento protegido pelo Windows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .exceptions import AuthenticationError

SERVICE_NAME = "evemex-trading-bot"
SERVICE_USER = "google-session"
LOGIN_URL = "https://trade.evemex.com/pt/login"
EDGE_DEBUG_PORT = 9233


def _install_google_dependencies() -> None:
    """Instala no mesmo Python que iniciou o robô (inclusive quando usado via ``py``)."""
    requirements = __import__("pathlib").Path(__file__).resolve().parents[1] / "requirements.txt"
    try:
        print("Instalando os componentes necessarios para login Google...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(requirements)], check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise AuthenticationError(
            f"Não foi possível instalar as dependências do login Google neste Python ({sys.executable}). "
            f"Execute: {sys.executable} -m pip install -r requirements.txt"
        ) from error


@dataclass(frozen=True)
class GoogleSession:
    token: str | None = None
    cookies: tuple[dict[str, Any], ...] = ()

    def is_usable(self) -> bool:
        return bool(self.token or self.cookies)


class WindowsCredentialStore:
    """Armazena a sessão somente no cofre protegido do sistema operacional."""

    def _keyring(self):
        try:
            import keyring
        except ImportError:
            _install_google_dependencies()
            try:
                import keyring
            except ImportError as error:
                raise AuthenticationError("Login Google requer keyring.") from error
        return keyring

    def load(self) -> GoogleSession | None:
        raw = self._keyring().get_password(SERVICE_NAME, SERVICE_USER)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            session = GoogleSession(token=data.get("token"), cookies=tuple(data.get("cookies") or ()))
            return session if session.is_usable() else None
        except (TypeError, ValueError, json.JSONDecodeError):
            self.clear()
            return None

    def save(self, session: GoogleSession) -> None:
        if session.is_usable():
            self._keyring().set_password(SERVICE_NAME, SERVICE_USER, json.dumps(asdict(session), separators=(",", ":")))

    def clear(self) -> None:
        try:
            self._keyring().delete_password(SERVICE_NAME, SERVICE_USER)
        except Exception:
            pass


def _token_from_storage(storage: dict[str, str]) -> str | None:
    """Obtém somente valores de chaves conhecidas de autenticação da aplicação."""
    priority = ("access_token", "accessToken", "authToken", "token", "jwt")
    for key in priority:
        value = storage.get(key)
        if isinstance(value, str) and len(value) > 20:
            return value
    for raw in storage.values():
        try:
            value = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            for key in priority:
                token = value.get(key)
                if isinstance(token, str) and len(token) > 20:
                    return token
    return None


def _browser_session_is_authenticated(driver: Any) -> bool:
    """Consulta a API no próprio contexto do Edge sem revelar a credencial."""
    try:
        return bool(driver.execute_async_script("""
            const done = arguments[arguments.length - 1];
            fetch('https://api.evemex.com/me', {credentials: 'include'})
              .then(response => done(response.ok))
              .catch(() => done(false));
        """))
    except Exception:
        return False


class GoogleAuthenticator:
    """Usa Edge nativo para o Google e só conecta à sessão após o usuário concluir o login."""

    def __init__(self, store: WindowsCredentialStore | None = None, *, timeout_seconds: int = 300) -> None:
        self.store = store or WindowsCredentialStore()
        self.timeout_seconds = timeout_seconds

    def restore(self) -> GoogleSession | None:
        return self.store.load()

    def forget(self) -> None:
        self.store.clear()

    @staticmethod
    def _edge_executable() -> str:
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        raise AuthenticationError("Microsoft Edge não foi encontrado neste Windows")

    def _wait_for_user_confirmation(self) -> None:
        print("\nEdge aberto em modo normal. Entre com Google e conclua o 2FA.")
        print("Quando voltar para a plataforma Evemex no Edge, pressione ENTER aqui (limite: 5 minutos).")
        deadline = time.monotonic() + self.timeout_seconds
        if os.name != "nt":
            input()
            return
        import msvcrt
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key in ("\r", "\n"):
                    return
            time.sleep(.1)
        raise AuthenticationError("Tempo esgotado aguardando a confirmação do login Google (5 minutos)")

    def interactive_login(self) -> GoogleSession:
        try:
            from selenium import webdriver
            from selenium.webdriver.edge.options import Options
        except ImportError:
            _install_google_dependencies()
            try:
                from selenium import webdriver
                from selenium.webdriver.edge.options import Options
            except ImportError as error:
                raise AuthenticationError("Login Google requer Selenium.") from error
        profile = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EvemexTradingBot" / "edge-google-profile"
        profile.mkdir(parents=True, exist_ok=True)
        edge = subprocess.Popen([
            self._edge_executable(), f"--remote-debugging-port={EDGE_DEBUG_PORT}",
            f"--user-data-dir={profile}", "--new-window", LOGIN_URL,
        ])
        driver = None
        try:
            self._wait_for_user_confirmation()
            options = Options()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{EDGE_DEBUG_PORT}")
            driver = webdriver.Edge(options=options)
            url = str(driver.current_url)
            storage = driver.execute_script("return Object.assign({}, window.localStorage, window.sessionStorage);") or {}
            token = _token_from_storage(storage)
            cookies = tuple(driver.get_cookies())
            authenticated = "/login" not in url or _browser_session_is_authenticated(driver)
            if not authenticated or not (token or cookies):
                raise AuthenticationError("A sessão Google não foi reconhecida. Confirme que voltou à plataforma Evemex antes de pressionar ENTER")
            # O callback pode usar cookie HttpOnly no domínio da API.
            if not token:
                driver.get("https://api.evemex.com/me")
                api_cookies = driver.get_cookies()
                cookies = tuple({(item["name"], item.get("domain")): item for item in [*cookies, *api_cookies]}.values())
            session = GoogleSession(token=token, cookies=cookies)
            if not session.is_usable():
                raise AuthenticationError("A Evemex não forneceu uma credencial de sessão após o login Google")
            return session
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            # O Edge desta sessão usa perfil dedicado, então pode ser fechado
            # sem afetar as janelas pessoais do usuário.
            if edge.poll() is None:
                edge.terminate()
