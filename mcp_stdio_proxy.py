#!/usr/bin/env python3
"""
MDAS MCP stdio proxy — **Approach A host** for Cursor / other stdio MCP clients.

Implements [`MCP-Server-Developer-Guide.md`] checklist (browser login, loopback callback,
exchange, Bearer on every `/mcp` call): opens the configured website (`?source=mcp`),
waits for the SPA to redirect with `code`+`state` on an API-allowlisted URI, exchanges
them on WebAPI, stores tokens locally, then **bridges** MCP JSON-RPC JSONL over stdio
to the Streamable HTTP server (`POST /mcp` + SSE) with injected auth headers.

**Default handoff URI** aligns with WebAPI `McpHandoff:DefaultRedirectUri`:
`http://127.0.0.1:9847/callback`.

The Docker image still runs **`server.py`** (HTTP-only). Developers run **`mcp_stdio_proxy.py`**
on the workstation as the MCP entry Cursor spawns (`command`: `python`).

Environment (optional overrides):
  MDAS_MCP_HTTP_URL   — default `{mdas.resource_url from config.json}/mcp`
  MDAS_HANDOFF_REDIRECT_URI — callback the SPA redirects to after mint (allowlisted on API)
  MDAS_TOKEN_PATH     — file to store `{access_token, refresh_token, user_id}` JSON
                        (default `%USERPROFILE%\\.mdas-mcp\\tokens.json` on Windows, `~/.mdas-mcp/tokens.json` elsewhere)
  MDAS_FORCE_HANDOFF  — set `1` to ignore stored tokens and run browser flow again
  MDAS_NO_AUTO_BROWSER_HANDOFF — set ``1`` to disable automatic browser handoff when
    ``server.py`` returns ``mdas_trigger_browser_handoff`` (after failed token refresh).
  MDAS_DISABLE_TOKEN_DISK_RELOAD — set ``1`` to stop reloading ``tokens.json`` when the
    file changes (default: reload on each MCP HTTP request if mtime is newer).
  MDAS_HANDOFF_GRACE_SECONDS — after a recent ``tokens.json`` write, wait for an in-flight
    peer handoff instead of opening the browser again (default ``120``).
  MDAS_PROXY_LOGLEVEL — proxy stderr log level (default ``WARNING``). ``httpx`` stays quiet
    so Cursor does not show every ``POST /mcp`` as a false ``[error]``.

Usage::
  MDAS_FORCE_HANDOFF=1 python mcp_stdio_proxy.py
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from typing import Any
import threading
import webbrowser
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, unquote_plus, urlencode, urlparse, urlunparse

import anyio
import httpx

from mcp.client.streamable_http import streamable_http_client
from mcp.server.stdio import stdio_server

try:
    from mdas_config import AppConfig, load_config, reset_config_cache
except ImportError:
    # Standalone client kit (MDAS-MCP-Client): ship only this file + config JSON.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class ServerSettings:
        host: str
        port: int

    @dataclass(frozen=True)
    class MdasSettings:
        api_base_url: str
        resource_url: str
        website_login_url: str | None
        verify_tls: bool
        enable_token_refresh: bool

    @dataclass(frozen=True)
    class AppConfig:
        server: ServerSettings
        mdas: MdasSettings

    def _default_config_path() -> Path:
        return Path(__file__).resolve().parent / "config.json"

    def _resolve_config_path() -> Path:
        raw = os.environ.get("MDAS_CONFIG_PATH", "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
        return _default_config_path()

    def load_config(path: Path | None = None) -> AppConfig:
        cfg_path = path or _resolve_config_path()
        if not cfg_path.is_file():
            raise FileNotFoundError(
                f"MDAS-MCP config not found: {cfg_path}. "
                "Copy config.example.json to config.json or set MDAS_CONFIG_PATH."
            )

        with cfg_path.open(encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Config root must be a JSON object: {cfg_path}")

        server_raw = data.get("server") or {}
        mdas_raw = data.get("mdas") or {}
        if not isinstance(server_raw, dict) or not isinstance(mdas_raw, dict):
            raise ValueError(f"Config must contain 'server' and 'mdas' objects: {cfg_path}")

        api_base = str(mdas_raw.get("api_base_url", "")).strip().rstrip("/")
        if not api_base:
            raise ValueError(f"mdas.api_base_url is required in {cfg_path}")

        resource = str(mdas_raw.get("resource_url", "")).strip().rstrip("/")
        if not resource:
            raise ValueError(f"mdas.resource_url is required in {cfg_path}")

        login_raw = str(mdas_raw.get("website_login_url", "")).strip()
        website_login = login_raw or None

        verify_tls = mdas_raw.get("verify_tls", True)
        if isinstance(verify_tls, str):
            verify_tls = verify_tls.strip().lower() not in ("false", "0", "no", "off")

        enable_refresh = mdas_raw.get("enable_token_refresh", True)
        if isinstance(enable_refresh, str):
            enable_refresh = enable_refresh.strip().lower() not in ("false", "0", "no", "off")

        host = str(server_raw.get("host", "127.0.0.1")).strip() or "127.0.0.1"

        port_raw = server_raw.get("port", 8000)
        try:
            port = int(port_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"server.port must be an integer in {cfg_path}") from exc

        return AppConfig(
            server=ServerSettings(host=host, port=port),
            mdas=MdasSettings(
                api_base_url=api_base,
                resource_url=resource,
                website_login_url=website_login,
                verify_tls=bool(verify_tls),
                enable_token_refresh=bool(enable_refresh),
            ),
        )

    _config: AppConfig | None = None

    def reset_config_cache() -> None:
        global _config
        _config = None

logger = logging.getLogger("mdas-mcp-stdio-proxy")

DEFAULT_HANDOFF_REDIRECT = "http://127.0.0.1:9847/callback"
_NAME_ID_CLAIM = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"
_USER_MSG_PREFIX = "MDAS Login: "


def user_notice(message: str) -> None:
    """User-visible status on stderr (shown in Cursor MCP / terminal output)."""
    line = f"\n{_USER_MSG_PREFIX}{message}\n"
    print(line, file=sys.stderr, flush=True)
    logger.debug(message)


def _configure_logging() -> None:
    """
    MCP uses stdout for JSON-RPC; diagnostics go to stderr.
    Cursor labels stderr as [error] even for INFO — keep libraries quiet by default.
    """
    level_name = os.environ.get("MDAS_PROXY_LOGLEVEL", "WARNING").strip().upper() or "WARNING"
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(levelname)s:%(name)s:%(message)s",
        force=True,
    )
    logger.setLevel(level)
    for name in (
        "httpx",
        "httpcore",
        "h11",
        "mcp",
        "mcp.client",
        "anyio",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def _html_status_page(title: str, paragraphs: list[str]) -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        f"<title>{title}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:2rem auto;line-height:1.5}"
        "h1{font-size:1.25rem}</style></head><body>"
        f"<h1>{title}</h1>{body}</body></html>"
    )


class BrowserHandoffRequested(Exception):
    """Raised internally when MCP HTTP responses imply WebAPI rejected tokens after refresh."""


def _nested_exc_contains(exc: BaseException, cls: type[BaseException]) -> bool:
    if isinstance(exc, cls):
        return True
    grp = getattr(exc, "exceptions", None)
    if isinstance(grp, tuple):
        return any(isinstance(e, BaseException) and _nested_exc_contains(e, cls) for e in grp)
    return False


def _json_tree_has_browser_handoff_trigger(node: Any) -> bool:
    if isinstance(node, dict):
        if node.get("mdas_trigger_browser_handoff") is True:
            return True
        return any(_json_tree_has_browser_handoff_trigger(v) for v in node.values())
    if isinstance(node, list):
        return any(_json_tree_has_browser_handoff_trigger(x) for x in node)
    if isinstance(node, str) and "mdas_trigger_browser_handoff" in node:
        stripped = node.strip()
        compact = "".join(stripped.split())
        if '"mdas_trigger_browser_handoff":true' in compact or "'mdas_trigger_browser_handoff':true" in compact:
            return True
        try:
            return _json_tree_has_browser_handoff_trigger(json.loads(stripped))
        except json.JSONDecodeError:
            return False
    return False


def _mcp_bridge_item_requires_browser_handoff(item: Any) -> bool:
    if item is None or isinstance(item, Exception):
        return False
    payload: Any = None
    if isinstance(item, dict):
        payload = item
    else:
        dump = getattr(item, "model_dump", None)
        if callable(dump):
            try:
                payload = dump(mode="json")
            except TypeError:
                try:
                    payload = dump()
                except Exception:  # noqa: BLE001
                    payload = None
    if payload is None:
        return False
    return _json_tree_has_browser_handoff_trigger(payload)


def expanduser_maybe(p: Path) -> Path:
    """Resolve ~ and env in path-ish strings."""
    return Path(os.path.expanduser(str(p))).resolve()


def default_token_file() -> Path:
    raw = os.environ.get("MDAS_TOKEN_PATH", "").strip()
    if raw:
        path = expanduser_maybe(Path(raw))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        root = Path.home()
    d = root / ".mdas-mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d / "tokens.json"


def default_handoff_lock_file() -> Path:
    return default_token_file().parent / "handoff.lock"


def _handoff_grace_seconds() -> float:
    raw = os.environ.get("MDAS_HANDOFF_GRACE_SECONDS", "120").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 120.0


def token_file_age_seconds(path: Path) -> float | None:
    if not path.is_file():
        return None
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _handoff_lock_stale(lock_path: Path, *, max_age_s: float = 360.0) -> bool:
    if not lock_path.is_file():
        return True
    try:
        if time.time() - lock_path.stat().st_mtime > max_age_s:
            return True
        raw = lock_path.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            return not _pid_alive(int(raw))
    except OSError:
        return True
    return False


def _acquire_handoff_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.is_file() and not _handoff_lock_stale(lock_path):
        return False
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_handoff_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def wait_for_peer_handoff(lock_path: Path, timeout_s: float) -> bool:
    """Wait until no other process is running browser handoff; return False on timeout."""
    deadline = time.time() + max(1.0, timeout_s)
    last_notice = 0.0
    user_notice(
        "Waiting for sign-in to finish in your browser. "
        "No action needed — this usually takes a few seconds."
    )
    while time.time() < deadline:
        if not lock_path.is_file() or _handoff_lock_stale(lock_path):
            _release_handoff_lock(lock_path)
            user_notice("Sign-in finished. Connecting MDAS tools…")
            return True
        now = time.time()
        if now - last_notice >= 12.0:
            remaining = max(0, int(deadline - now))
            user_notice(
                f"Still waiting for browser sign-in to complete… ({remaining}s remaining)"
            )
            last_notice = now
        time.sleep(0.4)
    user_notice(
        "Timed out waiting for sign-in. Finish login in the browser, or run handoff again."
    )
    return False


def jwt_user_id_fallback(access_token: str) -> str | None:
    parts = access_token.split(".")
    if len(parts) != 3:
        return None
    seg = parts[1]
    pad = "=" * ((4 - len(seg) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(seg + pad)
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in (_NAME_ID_CLAIM, "nameidentifier", "sub", "user_id", "userId"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def user_id_from_exchange_body(body: dict) -> str | None:
    raw = (
        body.get("User") or body.get("user") or body.get("userData") or body.get("UserData")
    )
    if isinstance(raw, dict):
        for k in ("Id", "id", "userId"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def pick_token(payload: dict, *names: str) -> str | None:
    """API may return PascalCase (.NET anonymous object) depending on serializers."""
    for n in names:
        v = payload.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def load_stored_tokens(path: Path) -> tuple[str | None, str | None, str | None]:
    if not path.is_file():
        return None, None, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read token store %s: %s", path, exc)
        return None, None, None
    access = pick_token(raw, "access_token", "AccessToken")
    refresh = pick_token(raw, "refresh_token", "RefreshToken")
    uid = raw.get("user_id") or raw.get("UserId") or raw.get("userId")
    if isinstance(uid, str) and uid.strip():
        uid = uid.strip()
    else:
        uid = None
    return access, refresh, uid


def save_tokens(path: Path, *, access_token: str, refresh_token: str | None, user_id: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"access_token": access_token}
    if refresh_token:
        data["refresh_token"] = refresh_token
    if user_id:
        data["user_id"] = user_id
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except (OSError, AttributeError):  # noqa: S110
        pass


class TokenStore:
    """Mutable auth state shared by httpx hooks (proxy is the token host — not server.py)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.access: str | None = None
        self.refresh: str | None = None
        self.user_id: str | None = None
        self._last_sync_mtime_ns: int | None = None

    def _record_disk_mtime(self) -> None:
        try:
            self._last_sync_mtime_ns = self.path.stat().st_mtime_ns
        except OSError:
            self._last_sync_mtime_ns = None

    def load_from_disk(self) -> bool:
        access, refresh, uid = load_stored_tokens(self.path)
        if not access:
            return False
        self.access, self.refresh, self.user_id = access, refresh, uid
        self._record_disk_mtime()
        return True

    def sync_from_disk_if_changed(self) -> bool:
        """
        Reload tokens.json when another process updated it (e.g. ``--handoff-only``)
        so a long-running stdio bridge does not keep revoked in-memory credentials.
        """
        if os.environ.get("MDAS_DISABLE_TOKEN_DISK_RELOAD", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            return False
        if not self.path.is_file():
            return False
        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except OSError:
            return False
        if self._last_sync_mtime_ns is not None and mtime_ns <= self._last_sync_mtime_ns:
            return False
        access, refresh, uid = load_stored_tokens(self.path)
        if not access:
            return False
        changed = (
            access != self.access
            or refresh != self.refresh
            or uid != self.user_id
        )
        self.access, self.refresh, self.user_id = access, refresh, uid
        self._last_sync_mtime_ns = mtime_ns
        if changed:
            logger.info("Reloaded tokens from %s (disk file changed)", self.path)
        return changed

    def assign(self, access: str, refresh: str | None, user_id: str | None) -> None:
        self.access = access
        self.refresh = refresh
        self.user_id = user_id
        save_tokens(self.path, access_token=access, refresh_token=refresh, user_id=user_id)
        self._record_disk_mtime()

    def apply_access_from_header(self, token: str) -> None:
        token = token.strip()
        if not token or token == self.access:
            return
        self.access = token
        save_tokens(self.path, access_token=token, refresh_token=self.refresh, user_id=self.user_id)
        self._record_disk_mtime()
        logger.info("Updated access token from MCP X-MDAS-Access-Token header → %s", self.path)

    def reload_disk_state(self) -> bool:
        """Force-read tokens.json (used after peer handoff or external login)."""
        self._last_sync_mtime_ns = None
        if self.sync_from_disk_if_changed():
            return True
        return self.load_from_disk()

    def apply_disk_tokens_if_changed(self) -> bool:
        """Re-read tokens.json and update memory when content differs (peer login / handoff-only)."""
        access, refresh, uid = load_stored_tokens(self.path)
        if not access:
            return False
        if access == self.access and refresh == self.refresh and uid == self.user_id:
            return False
        self.access, self.refresh, self.user_id = access, refresh, uid
        self._record_disk_mtime()
        logger.info("Reloaded tokens from %s (disk content changed)", self.path)
        return True


def probe_access_token(cfg: AppConfig, access: str) -> bool:
    """True when WebAPI accepts the access token (cheap quote probe)."""
    url = f"{cfg.mdas.api_base_url.rstrip('/')}/api/quote/level1"
    try:
        with httpx.Client(verify=cfg.mdas.verify_tls, timeout=30.0) as client:
            r = client.get(
                url,
                params={"symbols": "AAPL"},
                headers={"Accept": "application/json", "Authorization": f"Bearer {access}"},
            )
    except httpx.HTTPError as exc:
        logger.warning("Access token probe failed (network): %s", exc)
        return False
    return r.status_code == 200


def level1_sample_row(row: dict) -> dict[str, object]:
    """Extract display fields from a WebAPI level1 row (snake_case or PascalCase)."""
    keys = {k.lower(): k for k in row}
    def pick(*names: str):
        for n in names:
            k = keys.get(n.lower())
            if k is not None and row[k] is not None:
                return row[k]
        return None
    return {
        "symbol": pick("symbol", "Symbol") or "?",
        "last": pick(
            "last",
            "Last",
            "last_px",
            "lastPx",
            "trade_px",
            "tradePx",
            "closing_px",
            "closingPx",
        ),
        "bid": pick("bid", "Bid", "bid_px", "bidPx"),
        "ask": pick("ask", "Ask", "ask_px", "askPx"),
    }


def fetch_level1_sample(cfg: AppConfig, access: str, symbol: str = "AAPL") -> dict[str, object] | None:
    """Return bid/ask/last for a symbol after login (validates quote entitlements)."""
    url = f"{cfg.mdas.api_base_url.rstrip('/')}/api/quote/level1"
    try:
        with httpx.Client(verify=cfg.mdas.verify_tls, timeout=30.0) as client:
            r = client.get(
                url,
                params={"symbols": symbol},
                headers={"Accept": "application/json", "Authorization": f"Bearer {access}"},
            )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
        logger.warning("level1 sample fetch failed: %s", exc)
        return None
    items = data if isinstance(data, list) else data.get("data") or data.get("quotes") or [data]
    if isinstance(items, dict):
        items = [items]
    if not items or not isinstance(items[0], dict):
        return None
    return level1_sample_row(items[0])


def try_refresh_via_api(cfg: AppConfig, store: TokenStore) -> bool:
    if not store.refresh or not store.user_id:
        return False
    url = f"{cfg.mdas.api_base_url.rstrip('/')}/api/user/refresh"
    body = {"user_id": store.user_id, "refresh_token": store.refresh}
    try:
        with httpx.Client(verify=cfg.mdas.verify_tls, timeout=30.0) as client:
            r = client.post(
                url,
                json=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        logger.warning("Refresh request failed (network): %s", exc)
        return False
    if r.status_code != 200:
        logger.info("Refresh via API failed HTTP %s: %s", r.status_code, r.text[:160])
        return False
    try:
        payload = r.json()
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    access = pick_token(payload, "AccessToken", "access_token")
    if not access:
        return False
    refresh = pick_token(payload, "RefreshToken", "refresh_token") or store.refresh
    store.assign(access, refresh, store.user_id)
    logger.info("Refreshed access token via API → %s", store.path)
    return True


def tokens_usable(cfg: AppConfig, store: TokenStore) -> bool:
    if not store.access:
        return False
    if probe_access_token(cfg, store.access):
        return True
    logger.info("Stored access token rejected by WebAPI; trying refresh...")
    if try_refresh_via_api(cfg, store) and probe_access_token(cfg, store.access or ""):
        return True
    return False


def _try_peer_handoff_tokens(
    cfg: AppConfig,
    store: TokenStore,
    *,
    lock_path: Path,
    wait_s: float,
    reason: str,
) -> bool:
    logger.info("%s; waiting up to %.0fs for peer handoff to finish...", reason, wait_s)
    user_notice(
        "Sign-in is already in progress elsewhere. "
        f"Waiting up to {int(wait_s)}s for it to finish (no second browser window)."
    )
    if not wait_for_peer_handoff(lock_path, wait_s):
        return False
    store.reload_disk_state()
    if tokens_usable(cfg, store):
        logger.info("Using tokens from %s after peer handoff", store.path)
        return True
    return False


def ensure_tokens(
    cfg: AppConfig,
    store: TokenStore,
    *,
    redirect_uri: str,
    login_url: str | None,
    force_handoff: bool,
    timeout_s: float,
) -> None:
    if not login_url:
        raise RuntimeError("mdas.website_login_url is missing in config.json — required for Approach A.")

    verify = cfg.mdas.verify_tls
    force = force_handoff or os.environ.get("MDAS_FORCE_HANDOFF", "").strip() in ("1", "true", "yes")
    lock_path = default_handoff_lock_file()
    grace_s = _handoff_grace_seconds()

    if not force:
        store.reload_disk_state()
        if tokens_usable(cfg, store):
            logger.info("Using stored tokens from %s", store.path)
            user_notice("Already signed in. MDAS quote tools are ready.")
            return

        age = token_file_age_seconds(store.path)
        if age is not None and age < grace_s:
            if _try_peer_handoff_tokens(
                cfg,
                store,
                lock_path=lock_path,
                wait_s=min(timeout_s, grace_s),
                reason=(
                    f"tokens.json was updated {age:.0f}s ago — skipping duplicate browser login"
                ),
            ):
                return

        if lock_path.is_file() and not _handoff_lock_stale(lock_path):
            if _try_peer_handoff_tokens(
                cfg,
                store,
                lock_path=lock_path,
                wait_s=timeout_s,
                reason="another MDAS MCP handoff is in progress",
            ):
                return

        logger.info("Stored tokens unusable; running browser handoff...")
        user_notice(
            "Opening the MDAS website for sign-in. "
            "Log in, complete any agreements, then wait for the success page."
        )

    access, refresh, uid = run_browser_handoff(
        cfg=cfg,
        redirect_uri=redirect_uri,
        login_url=login_url,
        verify_tls=verify,
        timeout_s=timeout_s,
        lock_path=lock_path,
    )
    store.assign(access, refresh, uid)
    logger.info("Saved tokens to %s", store.path)
    if not probe_access_token(cfg, access):
        logger.warning(
            "New tokens from handoff did not pass level1 probe — check agreements / entitlements on the website."
        )
        user_notice(
            "Sign-in saved, but a test quote failed. "
            "Complete any required agreements on the MDAS website, then try again."
        )
    else:
        sample = fetch_level1_sample(cfg, access)
        if sample and sample.get("bid") is not None:
            user_notice(
                "Sign-in complete. Sample quote — "
                f"{sample['symbol']}: last={sample['last']} bid={sample['bid']} ask={sample['ask']}. "
                "Use MCP quote tools in Cursor (mdas-local must stay enabled). "
                "Only toggle mdas-local off/on if the MCP panel shows Not connected."
            )
        else:
            user_notice(
                "Sign-in complete. You can return to Cursor and request quotes "
                "(for example: level1 for AAPL). "
                "Use MCP quote tools in Cursor (mdas-local must stay enabled). "
                "Only toggle mdas-local off/on if the MCP panel shows Not connected."
            )


def build_http_headers(access: str | None, refresh: str | None, uid: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if access:
        headers["Authorization"] = f"Bearer {access}"
    if refresh:
        headers["X-MDAS-Refresh-Token"] = refresh
    if uid:
        headers["X-MDAS-User-Id"] = uid
    return headers


def _is_local_mcp_http_host(host: str) -> bool:
    """True for loopback MCP (Windows often uses ``::1`` instead of ``127.0.0.1``)."""
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1", "[::1]")


def make_mcp_http_hooks(cfg: AppConfig, store: TokenStore) -> tuple[list, list]:
    """Inject latest tokens on every MCP HTTP request; persist server-driven refresh on response."""

    async def on_request(request: httpx.Request) -> None:
        # This httpx client only talks to the local MCP backend — always inject latest disk tokens.
        prev_access = store.access
        access, refresh, uid = load_stored_tokens(store.path)
        if access:
            if access != prev_access:
                logger.info("MCP HTTP: using tokens reloaded from %s", store.path)
            store.access, store.refresh, store.user_id = access, refresh, uid
            request.headers["Authorization"] = f"Bearer {access}"
        elif store.access:
            request.headers["Authorization"] = f"Bearer {store.access}"
        refresh = refresh or store.refresh
        uid = uid or store.user_id
        if cfg.mdas.enable_token_refresh and refresh:
            request.headers["X-MDAS-Refresh-Token"] = refresh
        elif "X-MDAS-Refresh-Token" in request.headers:
            del request.headers["X-MDAS-Refresh-Token"]
        if uid:
            request.headers["X-MDAS-User-Id"] = uid
        elif "X-MDAS-User-Id" in request.headers:
            del request.headers["X-MDAS-User-Id"]

    async def on_response(response: httpx.Response) -> None:
        path = response.request.url.path or ""
        if not (path == "/mcp" or path.startswith("/mcp/")):
            if not _is_local_mcp_http_host(response.request.url.host or ""):
                return
        new_access = response.headers.get("X-MDAS-Access-Token") or response.headers.get(
            "x-mdas-access-token",
        )
        if new_access:
            store.apply_access_from_header(new_access)

    return [on_request], [on_response]


def exchange_handoff(
    *,
    cfg: AppConfig,
    exchange_url: str,
    code: str,
    state: str,
    verify_tls: bool,
) -> tuple[str, str | None, str | None]:
    payload = {"code": code.strip(), "state": state.strip()}
    with httpx.Client(verify=verify_tls, timeout=60.0) as client:
        r = client.post(
            exchange_url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
        )
    try:
        body = r.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"handoff exchange HTTP {r.status_code}: invalid JSON ({exc})") from exc
    if r.status_code != 200:
        raise RuntimeError(
            f"handoff exchange failed HTTP {r.status_code}: {body!r}",
        )

    access = pick_token(body, "AccessToken", "access_token") if isinstance(body, dict) else None
    refresh = pick_token(body, "RefreshToken", "refresh_token") if isinstance(body, dict) else None
    uid = (
        user_id_from_exchange_body(body)
        if isinstance(body, dict)
        else None
    )
    if not access:
        raise RuntimeError(f"exchange response missing access token keys: keys={body.keys()!r}")

    uid = uid or jwt_user_id_fallback(access)
    return access, refresh, uid


def build_login_url(login_url: str, redirect_uri: str) -> str:
    """
    Tell the SPA which loopback callback to use after mint.
    Frontend should read allowlisted ``redirect_uri`` from the login query (see MCP-Frontend-Developer-Guide §5).
    """
    parsed = urlparse(login_url)
    pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "redirect_uri" not in pairs:
        pairs["redirect_uri"] = redirect_uri
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(pairs), parsed.fragment),
    )


def run_browser_handoff(
    *,
    cfg: AppConfig,
    redirect_uri: str,
    login_url: str,
    verify_tls: bool,
    timeout_s: float,
    lock_path: Path | None = None,
) -> tuple[str, str | None, str | None]:
    lock = lock_path or default_handoff_lock_file()
    if not _acquire_handoff_lock(lock):
        user_notice(
            "Another sign-in is already in progress. "
            "Waiting for it to finish instead of opening a second browser window."
        )
        if wait_for_peer_handoff(lock, min(timeout_s, 120.0)):
            access, refresh, uid = load_stored_tokens(default_token_file())
            if access:
                user_notice("Using credentials from the completed sign-in.")
                return access, refresh, uid
        raise RuntimeError(
            "MDAS login already in progress in another window/process. "
            "Finish that login or delete handoff.lock under .mdas-mcp.",
        )
    try:
        return _run_browser_handoff_locked(
            cfg=cfg,
            redirect_uri=redirect_uri,
            login_url=login_url,
            verify_tls=verify_tls,
            timeout_s=timeout_s,
        )
    finally:
        _release_handoff_lock(lock)


def _run_browser_handoff_locked(
    *,
    cfg: AppConfig,
    redirect_uri: str,
    login_url: str,
    verify_tls: bool,
    timeout_s: float,
) -> tuple[str, str | None, str | None]:
    exchange_url = f"{cfg.mdas.api_base_url.rstrip('/')}/api/user/handoff/exchange"
    parsed_r = urlparse(redirect_uri)
    host = parsed_r.hostname or "127.0.0.1"
    port = parsed_r.port or (443 if parsed_r.scheme == "https" else 80)
    path_prefix = parsed_r.path or "/"
    if path_prefix.endswith("/"):
        path_prefix = path_prefix.rstrip("/")

    handoff_done = threading.Event()
    tokens_out: list[tuple[str, str | None, str | None] | None] = [None]
    handoff_error: list[BaseException | None] = [None]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args):  # noqa: ANN001
            logger.debug(fmt, *args)

        def _send_html(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            up = urlparse(self.path or "")
            logger.info("Handoff listener received GET %s (expect path %s)", up.path, path_prefix)
            if up.path.rstrip("/") != path_prefix.rstrip("/"):
                self._send_html(404, b"<html><body>404</body></html>")
                return

            qs = parse_qs(up.query)
            code_l = qs.get("code") or qs.get("Code")
            state_l = qs.get("state") or qs.get("State")

            html_ok = _html_status_page(
                "Sign-in complete",
                [
                    "Your MDAS session is connected to Cursor.",
                    "You can <strong>close this tab</strong> and return to the editor.",
                ],
            )
            html_err = _html_status_page(
                "Sign-in error",
                [
                    "The redirect is missing <code>code</code> or <code>state</code>.",
                    "Return to the MDAS login page and try again.",
                ],
            )

            if not code_l or not state_l:
                self._send_html(400, html_err.encode("utf-8"))
                return

            code = unquote_plus(code_l[0])
            state_val = unquote_plus(state_l[0])
            logger.info("Handoff callback received code+state; exchanging with API...")
            user_notice("Browser sign-in received. Finishing connection to MDAS…")
            try:
                tokens_out[0] = exchange_handoff(
                    cfg=cfg,
                    exchange_url=exchange_url,
                    code=code,
                    state=state_val,
                    verify_tls=verify_tls,
                )
                user_notice(
                    "Sign-in complete. You can close the browser tab and return to Cursor."
                )
                self._send_html(200, html_ok.encode("utf-8"))
            except Exception as exc:
                handoff_error[0] = exc
                user_notice(f"Sign-in failed: {exc}")
                html_fail = _html_status_page(
                    "Sign-in failed",
                    [
                        "Could not complete the MDAS connection.",
                        "Return to Cursor and try signing in again.",
                        str(exc),
                    ],
                )
                self._send_html(500, html_fail.encode("utf-8"))
            finally:
                handoff_done.set()

    if host.lower() not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            "Only loopback redirects are supported by this proxy. Set MDAS_HANDOFF_REDIRECT_URI to a "
            "host of 127.0.0.1 or localhost matching API McpHandoff:AllowedRedirectUris.",
        )
    bind_host = "127.0.0.1"
    httpserver = HTTPServer((bind_host, port), Handler)
    t = threading.Thread(target=httpserver.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    t.start()
    browser_url = build_login_url(login_url, redirect_uri)
    logger.info(
        "Waiting for browser redirect to %s (login alone is NOT enough — SPA must POST handoff/mint then redirect here).",
        redirect_uri,
    )
    logger.info("Handoff listener on http://%s:%s%s", host, port, parsed_r.path)
    logger.info("Opening browser: %s", browser_url)
    user_notice(
        "A browser tab should open for MDAS sign-in. "
        "Log in, finish any agreements, then wait for the success page."
    )
    webbrowser.open(browser_url)

    try:
        if not handoff_done.wait(timeout=timeout_s):
            user_notice(
                "Timed out waiting for sign-in. Complete login in the browser, then try again."
            )
            raise TimeoutError(
                "Timed out waiting for redirect with code+state.\n"
                "After login, the website SPA must:\n"
                "  1) POST /api/user/handoff/mint (Bearer from login)\n"
                "  2) Navigate the browser to redirect_url targeting\n"
                f"     {redirect_uri!r}\n"
                "Common causes:\n"
                "  • Mint never called (check DevTools → Network for handoff/mint)\n"
                "  • Redirect went elsewhere (e.g. mdas-app …/mcp-handoff/callback instead of 127.0.0.1:9847)\n"
                "  • Agreements (NeedSign) not finished before mint\n"
                "  • redirect_uri not passed to mint — login URL now includes redirect_uri query for the SPA",
            )
        if handoff_error[0] is not None:
            raise handoff_error[0]
        if not tokens_out[0]:
            raise RuntimeError("Handoff finished without tokens")
    finally:
        httpserver.shutdown()
        httpserver.server_close()

    return tokens_out[0]


async def bridge_stdio_http_with_rehandoff(
    mcp_http_url: str,
    cfg: AppConfig,
    *,
    token_path: Path,
    redirect_uri: str,
    login_url: str,
    timeout_s: float,
) -> None:
    """
    Run stdio ↔ Streamable HTTP until disconnect, or rerun browser handoff when Docker MCP
    flags ``mdas_trigger_browser_handoff`` (WebAPI denied request after refresh failed).

    Tokens are **not** stored in ``server.py`` — this proxy keeps ``tokens.json`` and injects
    ``Authorization`` / ``X-MDAS-*`` on every MCP HTTP request via httpx hooks.
    """
    verify = cfg.mdas.verify_tls
    timeouts = httpx.Timeout(600.0, connect=60.0)
    auto_browser = os.environ.get("MDAS_NO_AUTO_BROWSER_HANDOFF", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )
    store = TokenStore(token_path)
    req_hooks, resp_hooks = make_mcp_http_hooks(cfg, store)

    async with stdio_server() as (stdin_r, stdin_w):
        while True:
            ensure_tokens(
                cfg,
                store,
                redirect_uri=redirect_uri,
                login_url=login_url,
                force_handoff=False,
                timeout_s=timeout_s,
            )
            logger.info(
                "Bridging stdio MCP → %s (token file %s)",
                mcp_http_url,
                store.path,
            )
            user_notice("MDAS MCP is connected. You can request quotes in Cursor.")

            session_needs_handoff = False
            async with httpx.AsyncClient(
                verify=verify,
                timeout=timeouts,
                follow_redirects=True,
                event_hooks={"request": req_hooks, "response": resp_hooks},
            ) as hc:
                async with streamable_http_client(mcp_http_url, http_client=hc, terminate_on_close=True) as (
                    http_r,
                    http_w,
                    _get_sid,
                ):

                    async def up() -> None:
                        async for item in stdin_r:
                            if isinstance(item, Exception):
                                logger.error("Malformed stdin MCP line: %s", item)
                                continue
                            await http_w.send(item)

                    async def down() -> None:
                        async for item in http_r:
                            if isinstance(item, Exception):
                                logger.warning("upstream MCP transport error: %s", item)
                                continue
                            if auto_browser and _mcp_bridge_item_requires_browser_handoff(item):
                                logger.info(
                                    "WebAPI session invalid after refresh; opening browser for handoff."
                                )
                                raise BrowserHandoffRequested
                            await stdin_w.send(item)

                    try:
                        async with anyio.create_task_group() as tg:
                            tg.start_soon(up)
                            tg.start_soon(down)
                    except BaseException as group_or_exc:
                        if auto_browser and _nested_exc_contains(group_or_exc, BrowserHandoffRequested):
                            session_needs_handoff = True
                        else:
                            raise

            if not (auto_browser and session_needs_handoff):
                return
            logger.info("Re-authenticating via browser, then restarting MCP bridge...")
            ensure_tokens(
                cfg,
                store,
                redirect_uri=redirect_uri,
                login_url=login_url,
                force_handoff=True,
                timeout_s=timeout_s,
            )


def _parse_handoff_redirect() -> str:
    return os.environ.get("MDAS_HANDOFF_REDIRECT_URI", DEFAULT_HANDOFF_REDIRECT).strip()


def _mcp_http_url_from_config(cfg: AppConfig) -> str:
    explicit = os.environ.get("MDAS_MCP_HTTP_URL", "").strip()
    if explicit:
        return explicit
    base = cfg.mdas.resource_url.rstrip("/")
    return f"{base}/mcp"


def smoke_test_chain(cfg: AppConfig) -> None:
    """
    Non-interactive checks before a full browser handoff.
    - Local Streamable HTTP MCP (Docker) health + 401 probes
    - WebAPI handoff/exchange reachable (expect 401 invalid code for dummy payload)

    Override MCP base URL (e.g. run smoke from Docker: ``MDAS_SMOKE_MCP_BASE=http://host.docker.internal:8000``).

    """
    raw_override = os.environ.get("MDAS_SMOKE_MCP_BASE", "").strip().rstrip("/")
    base = raw_override if raw_override else cfg.mdas.resource_url.rstrip("/")
    verify = cfg.mdas.verify_tls
    errors: list[str] = []

    with httpx.Client(verify=verify, timeout=30.0, follow_redirects=True) as client:
        # 1. Health
        try:
            r = client.get(f"{base}/health")
            if r.status_code != 200:
                errors.append(f"/health expected 200, got {r.status_code}")
            else:
                js = r.json()
                if js.get("service") != "mdas-mcp":
                    errors.append(f"/health unexpected body: {js!r}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"/health failed: {exc}")

        # 2. OAuth probe (no plain-text 404)
        try:
            r = client.get(f"{base}/.well-known/oauth-authorization-server")
            if r.status_code != 401:
                errors.append(f"/.well-known/oauth-authorization-server expected 401, got {r.status_code}")
            else:
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    errors.append("/.well-known/oauth-authorization-server body is not JSON")
                else:
                    if "error" not in data:
                        errors.append("/.well-known/oauth-authorization-server JSON missing error key")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"oauth probe failed: {exc}")

        # 3. GET /mcp without Bearer
        try:
            r = client.get(f"{base}/mcp")
            if r.status_code != 401:
                errors.append(f"GET /mcp without Bearer expected 401, got {r.status_code}")
            else:
                data = r.json()
                if data.get("error") != "authentication_required":
                    errors.append(f"GET /mcp JSON missing authentication_required: keys={list(data)[:5]}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"GET /mcp failed: {exc}")

        # 4. SSE legacy path
        try:
            r = client.get(f"{base}/sse")
            if r.status_code != 501:
                errors.append(f"GET /sse expected 501, got {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"GET /sse failed: {exc}")

        # 5. WebAPI exchange dummy (proves route + TLS)
        ex_url = f"{cfg.mdas.api_base_url.rstrip('/')}/api/user/handoff/exchange"
        try:
            r2 = client.post(
                ex_url,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={"code": "__smoke_dummy__", "state": "__smoke_dummy__"},
            )
            if r2.status_code not in (400, 401):
                errors.append(
                    f"POST handoff/exchange with dummy code expected 400/401, got {r2.status_code} {r2.text[:120]!r}",
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"POST handoff/exchange failed (VPN/network?): {exc}")

    if errors:
        raise RuntimeError("Smoke test failed:\n- " + "\n- ".join(errors))
    logger.info("Smoke test OK: MCP at %s + API handoff/exchange reachable", base)


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="MDAS MCP Approach A — stdio → Streamable HTTP proxy")
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="Verify local MCP HTTP + dev API handoff/exchange reachability (no browser).",
    )
    ap.add_argument(
        "--handoff-only",
        action="store_true",
        help="Run browser handoff once, save tokens, then exit.",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        metavar="SEC",
        help="Max seconds waiting for SPA redirect during handoff (default 300).",
    )
    ap.add_argument(
        "--config",
        dest="config_path",
        default="",
        help="Path to config.json (otherwise MDAS_CONFIG_PATH or application/config.json).",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = parse_args(argv)

    _configure_logging()

    if args.config_path:
        reset_config_cache()
        cfg = load_config(expanduser_maybe(Path(args.config_path)))
    else:
        cfg = load_config()

    token_file = default_token_file()
    redirect_uri = _parse_handoff_redirect()
    mcp_http_url = _mcp_http_url_from_config(cfg)
    login = cfg.mdas.website_login_url or ""

    if args.smoke:
        logger.info("--smoke: checking local MCP HTTP + WebAPI handoff/exchange...")
        smoke_test_chain(cfg)
        logger.info("--smoke: all checks passed.")
        return 0

    if args.handoff_only:
        logger.info("--handoff-only: exchange and save tokens; then exit.")
        store = TokenStore(token_file)
        ensure_tokens(
            cfg,
            store,
            redirect_uri=redirect_uri,
            login_url=login,
            force_handoff=True,
            timeout_s=float(args.timeout),
        )
        return 0

    async def _async_bridge() -> None:
        await bridge_stdio_http_with_rehandoff(
            mcp_http_url,
            cfg,
            token_path=token_file,
            redirect_uri=redirect_uri,
            login_url=login,
            timeout_s=float(args.timeout),
        )

    anyio.run(_async_bridge, backend="asyncio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
