"""Offline Kasm Chrome sessions (CDP + view URLs) — no Workspaces API keys."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx

from job_automation.logging_config import get_logger, log_event

logger = get_logger(__name__)

PORTAL_START_URLS = {
    "hiringcafe": "https://hiring.cafe/",
    "builtin": "https://builtin.com/jobs",
    "jobright": "https://jobright.ai/",
    "glassdoor": "https://www.glassdoor.com/Job/index.htm",
}


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _ensure_resize_remote(url: str) -> str:
    """Force KasmVNC remote resize so the desktop follows the client window."""
    if not url or "resize=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}resize=remote"


def _parse_portal_map(raw: str | None) -> dict[str, str]:
    """Parse `builtin=http://...,hiringcafe=http://...` or plain CSV (order-assigned later)."""
    if not raw or not raw.strip():
        return {}
    text = raw.strip()
    if "=" not in text:
        return {}
    out: dict[str, str] = {}
    for part in _split_csv(text):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            out[key] = value
    return out


@dataclass
class KasmConfig:
    """
    Offline mode (default): connect to Kasm Chrome you already run.
    No API key / image id required — only CDP endpoints (+ optional view URLs).

    API mode (optional): create/destroy sessions via Kasm Workspaces Public API.
    """

    enabled: bool = False
    mode: str = "offline"  # offline | api
    max_sessions: int = 2
    # Offline: list of CDP HTTP endpoints, e.g. http://127.0.0.1:9333,http://127.0.0.1:9334
    cdp_endpoints: list[str] = field(default_factory=list)
    # Offline: optional portal -> cdp overrides
    cdp_by_portal: dict[str, str] = field(default_factory=dict)
    # Offline: Watch links (same length as cdp_endpoints, or portal map, or one shared URL)
    view_urls: list[str] = field(default_factory=list)
    view_by_portal: dict[str, str] = field(default_factory=dict)
    view_url: str = ""

    # --- API mode only (optional) ---
    api_url: str = ""
    api_key: str = ""
    api_key_secret: str = ""
    image_id: str = ""
    user_id: str = ""
    cdp_mode: str = "container_ip"
    cdp_port: int = 9333
    cdp_port_key: str = "cdp"
    request_timeout_sec: float = 60.0
    ready_timeout_sec: float = 180.0
    poll_interval_sec: float = 3.0
    verify_ssl: bool = True

    @classmethod
    def from_env(cls) -> "KasmConfig":
        enabled_raw = os.getenv("KASM_ENABLED", "false").strip().lower()
        enabled = enabled_raw in {"1", "true", "yes", "on"}
        mode = (os.getenv("KASM_MODE") or "offline").strip().lower()
        if mode in {"local", "cdp", "direct"}:
            mode = "offline"

        max_sessions = int(os.getenv("KASM_MAX_SESSIONS", "1") or "1")
        max_sessions = max(1, min(max_sessions, 2))

        cdp_endpoints = _split_csv(os.getenv("KASM_CDP_ENDPOINTS"))
        # Single-endpoint shortcut
        single_cdp = (os.getenv("KASM_CDP_URL") or "").strip()
        if single_cdp and not cdp_endpoints:
            cdp_endpoints = [single_cdp]

        view_urls = _split_csv(os.getenv("KASM_VIEW_URLS"))
        view_url = (os.getenv("KASM_VIEW_URL") or "").strip()
        if view_url and not view_urls:
            view_urls = [view_url]
        # Sensible local defaults so Watch works after start_kasm_local.sh
        # even if KASM_VIEW_URLS was omitted from .env.
        if enabled and mode == "offline" and not view_urls:
            view_urls = [
                "https://127.0.0.1:6911/?resize=remote",
            ][:max_sessions]
        if enabled and mode == "offline" and not cdp_endpoints:
            cdp_endpoints = [
                "http://127.0.0.1:9333",
            ][:max_sessions]
        # Prefer remote resize so the Kasm desktop tracks the browser window.
        view_urls = [_ensure_resize_remote(url) for url in view_urls]
        if view_url:
            view_url = _ensure_resize_remote(view_url)

        verify_raw = os.getenv("KASM_VERIFY_SSL", "true").strip().lower()
        verify_ssl = verify_raw not in {"0", "false", "no", "off"}

        return cls(
            enabled=enabled,
            mode=mode,
            max_sessions=max_sessions,
            cdp_endpoints=cdp_endpoints,
            cdp_by_portal=_parse_portal_map(os.getenv("KASM_CDP_BY_PORTAL")),
            view_urls=view_urls,
            view_by_portal=_parse_portal_map(os.getenv("KASM_VIEW_BY_PORTAL")),
            view_url=view_url,
            api_url=(os.getenv("KASM_API_URL") or "").rstrip("/"),
            api_key=os.getenv("KASM_API_KEY") or "",
            api_key_secret=os.getenv("KASM_API_KEY_SECRET") or "",
            image_id=os.getenv("KASM_IMAGE_ID") or "",
            user_id=os.getenv("KASM_USER_ID") or "",
            cdp_mode=(os.getenv("KASM_CDP_MODE") or "container_ip").strip().lower(),
            cdp_port=int(os.getenv("KASM_CDP_PORT", "9333") or "9333"),
            cdp_port_key=(os.getenv("KASM_CDP_PORT_KEY") or "cdp").strip(),
            request_timeout_sec=float(os.getenv("KASM_REQUEST_TIMEOUT_SEC", "60") or "60"),
            ready_timeout_sec=float(os.getenv("KASM_READY_TIMEOUT_SEC", "180") or "180"),
            poll_interval_sec=float(os.getenv("KASM_POLL_INTERVAL_SEC", "3") or "3"),
            verify_ssl=verify_ssl,
        )

    @property
    def is_offline(self) -> bool:
        return self.mode != "api"

    def validate(self) -> None:
        if not self.enabled:
            return
        if self.is_offline:
            if not self.cdp_endpoints and not self.cdp_by_portal:
                raise RuntimeError(
                    "Kasm offline mode enabled but no CDP endpoints set. "
                    "Set KASM_CDP_ENDPOINTS=http://host:9333,http://host:9334 "
                    "or KASM_CDP_BY_PORTAL=builtin=http://host:9333,hiringcafe=http://host:9334"
                )
            return
        missing = [
            name
            for name, value in [
                ("KASM_API_URL", self.api_url),
                ("KASM_API_KEY", self.api_key),
                ("KASM_API_KEY_SECRET", self.api_key_secret),
                ("KASM_IMAGE_ID", self.image_id),
            ]
            if not value
        ]
        if missing:
            raise RuntimeError(f"Kasm API mode enabled but missing config: {', '.join(missing)}")


@dataclass
class KasmSession:
    portal: str
    kasm_id: str
    user_id: str
    view_url: str
    cdp_url: str | None = None
    status: str = "starting"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "portal": self.portal,
            "kasm_id": self.kasm_id,
            "user_id": self.user_id,
            "view_url": self.view_url,
            "cdp_url": self.cdp_url,
            "status": self.status,
        }


class KasmClient:
    """Kasm Workspaces Public API (optional; not used in offline mode)."""

    def __init__(self, config: KasmConfig):
        self.config = config

    def _auth_payload(self) -> dict[str, Any]:
        return {
            "api_key": self.config.api_key,
            "api_key_secret": self.config.api_key_secret,
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = urljoin(self.config.api_url + "/", path.lstrip("/"))
        with httpx.Client(timeout=self.config.request_timeout_sec, verify=self.config.verify_ssl) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"raw": data}

    def request_kasm(
        self,
        *,
        image_id: str | None = None,
        user_id: str | None = None,
        kasm_url: str | None = None,
        enable_sharing: bool = True,
        environment: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            **self._auth_payload(),
            "image_id": image_id or self.config.image_id,
            "enable_sharing": enable_sharing,
        }
        uid = user_id if user_id is not None else self.config.user_id
        if uid:
            payload["user_id"] = uid
        if kasm_url:
            payload["kasm_url"] = kasm_url
        if environment:
            payload["environment"] = environment
        return self._post("/api/public/request_kasm", payload)

    def get_kasm_status(self, *, kasm_id: str, user_id: str) -> dict[str, Any]:
        payload = {
            **self._auth_payload(),
            "kasm_id": kasm_id,
            "user_id": user_id,
        }
        return self._post("/api/public/get_kasm_status", payload)

    def destroy_kasm(self, *, kasm_id: str, user_id: str) -> dict[str, Any]:
        payload = {
            **self._auth_payload(),
            "kasm_id": kasm_id,
            "user_id": user_id,
        }
        return self._post("/api/public/destroy_kasm", payload)


class KasmSessionBroker:
    """Bind portals to offline CDP endpoints, or create API sessions."""

    def __init__(self, config: KasmConfig | None = None):
        self.config = config or KasmConfig.from_env()
        self.client = KasmClient(self.config)
        self.sessions: dict[str, KasmSession] = {}

    def create_sessions(self, portals: list[str]) -> dict[str, KasmSession]:
        self.config.validate()
        if self.sessions:
            self.destroy_all()
        selected = list(portals[: self.config.max_sessions])
        if self.config.is_offline:
            return self._create_offline_sessions(selected)
        return self._create_api_sessions(selected)

    def _resolve_view_url(self, portal: str, index: int) -> str:
        if portal in self.config.view_by_portal:
            return self.config.view_by_portal[portal]
        if index < len(self.config.view_urls):
            return self.config.view_urls[index]
        if self.config.view_url:
            return self.config.view_url
        if self.config.view_urls:
            return self.config.view_urls[0]
        return ""

    def _resolve_cdp_url(self, portal: str, index: int) -> str:
        if portal in self.config.cdp_by_portal:
            return self.config.cdp_by_portal[portal]
        if index < len(self.config.cdp_endpoints):
            return self.config.cdp_endpoints[index]
        raise RuntimeError(
            f"No CDP endpoint available for portal '{portal}' (index {index}). "
            f"Have {len(self.config.cdp_endpoints)} endpoint(s) in KASM_CDP_ENDPOINTS."
        )

    def _create_offline_sessions(self, portals: list[str]) -> dict[str, KasmSession]:
        for index, portal in enumerate(portals):
            cdp_url = self._resolve_cdp_url(portal, index)
            view_url = self._resolve_view_url(portal, index)
            session = KasmSession(
                portal=portal,
                kasm_id=f"offline-{portal}-{index}",
                user_id="offline",
                view_url=view_url,
                cdp_url=cdp_url,
                status="running",
                raw={"mode": "offline", "start_url": PORTAL_START_URLS.get(portal)},
            )
            self.sessions[portal] = session
            log_event(
                logger,
                f"Offline Kasm bind cdp={cdp_url} view={view_url or '(none)'}",
                portal=portal,
                action="kasm_ready",
            )
        return dict(self.sessions)

    def _absolute_view_url(self, kasm_url_path: str) -> str:
        if kasm_url_path.startswith("http://") or kasm_url_path.startswith("https://"):
            return kasm_url_path
        return f"{self.config.api_url}{kasm_url_path}"

    def _extract_cdp_url(self, status: dict[str, Any]) -> str | None:
        mode = self.config.cdp_mode
        if mode in {"none", "disabled", "off"}:
            return None
        kasm = status.get("kasm") or {}
        if mode == "container_ip":
            container_ip = kasm.get("container_ip")
            if container_ip:
                return f"http://{container_ip}:{self.config.cdp_port}"
            return None
        if mode == "port_map":
            port_map = kasm.get("port_map") or {}
            entry = port_map.get(self.config.cdp_port_key) or {}
            path = entry.get("path")
            if not path:
                return None
            base = self.config.api_url.rstrip("/")
            return f"{base}/{path.strip('/')}/"
        return None

    def wait_until_running(self, *, kasm_id: str, user_id: str) -> dict[str, Any]:
        deadline = time.time() + self.config.ready_timeout_sec
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.client.get_kasm_status(kasm_id=kasm_id, user_id=user_id)
            status = (
                ((last.get("kasm") or {}).get("operational_status"))
                or last.get("operational_status")
                or last.get("status")
                or ""
            ).lower()
            if status == "running":
                return last
            if status in {"stopped", "error", "failed"}:
                raise RuntimeError(f"Kasm session {kasm_id} entered terminal status: {status} ({last})")
            time.sleep(self.config.poll_interval_sec)
        raise TimeoutError(
            f"Kasm session {kasm_id} not running within {self.config.ready_timeout_sec}s. Last={last}"
        )

    def create_session_for_portal(self, portal: str) -> KasmSession:
        start_url = PORTAL_START_URLS.get(portal, "https://builtin.com/jobs")
        log_event(logger, f"Requesting Kasm session for {portal}", portal=portal, action="kasm_request")
        created = self.client.request_kasm(
            kasm_url=start_url,
            enable_sharing=True,
            environment={
                "CHROME_ARGS": f"--remote-debugging-port={self.config.cdp_port} --remote-debugging-address=0.0.0.0",
            },
        )
        kasm_id = created.get("kasm_id")
        user_id = created.get("user_id") or self.config.user_id
        if not kasm_id or not user_id:
            raise RuntimeError(f"Kasm request_kasm missing ids: {created}")

        status = self.wait_until_running(kasm_id=kasm_id, user_id=user_id)
        view_path = status.get("kasm_url") or created.get("kasm_url") or ""
        view_url = self._absolute_view_url(view_path) if view_path else self.config.api_url
        cdp_url = self._extract_cdp_url(status)

        session = KasmSession(
            portal=portal,
            kasm_id=kasm_id,
            user_id=user_id,
            view_url=view_url,
            cdp_url=cdp_url,
            status="running",
            raw={"created": created, "status": status},
        )
        self.sessions[portal] = session
        log_event(
            logger,
            f"Kasm session ready view={view_url} cdp={cdp_url or 'none'}",
            portal=portal,
            action="kasm_ready",
        )
        return session

    def _create_api_sessions(self, portals: list[str]) -> dict[str, KasmSession]:
        for portal in portals:
            self.create_session_for_portal(portal)
        return dict(self.sessions)

    def destroy_all(self) -> None:
        if self.config.is_offline:
            # Offline browsers are owned by you — JobSeek only disconnects Playwright.
            self.sessions.clear()
            return
        for portal, session in list(self.sessions.items()):
            try:
                self.client.destroy_kasm(kasm_id=session.kasm_id, user_id=session.user_id)
                log_event(logger, "Destroyed Kasm session", portal=portal, action="kasm_destroy")
            except Exception as exc:
                log_event(
                    logger,
                    f"Failed to destroy Kasm session: {exc}",
                    portal=portal,
                    action="kasm_destroy_error",
                    level=40,
                )
        self.sessions.clear()

    def status_payload(self) -> list[dict[str, Any]]:
        return [s.to_status_dict() for s in self.sessions.values()]
