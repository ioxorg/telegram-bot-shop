from __future__ import annotations

import base64
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from configs.configs import settings

logger = logging.getLogger(__name__)

_token: str | None = None
_token_fetched_at: float = 0.0
_TOKEN_TTL = 3600  # seconds before we proactively refresh


class MarzbanError(Exception):
    pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.marzban_base_url, timeout=30.0)


async def _authenticate(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/admin/token",
        data={
            "username": settings.marzban_username,
            "password": settings.marzban_password,
        },
    )
    if resp.status_code != 200:
        raise MarzbanError(f"Auth failed: {resp.status_code} — {resp.text}")
    return resp.json()["access_token"]


async def _get_token(client: httpx.AsyncClient, force_refresh: bool = False) -> str:
    global _token, _token_fetched_at
    now = time.monotonic()
    if force_refresh or _token is None or (now - _token_fetched_at) > _TOKEN_TTL:
        _token = await _authenticate(client)
        _token_fetched_at = now
    return _token


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _authorized_get(client: httpx.AsyncClient, url: str) -> dict:
    token = await _get_token(client)
    resp = await client.get(url, headers=_auth_header(token))
    if resp.status_code == 401:
        token = await _get_token(client, force_refresh=True)
        resp = await client.get(url, headers=_auth_header(token))
    if not resp.is_success:
        raise MarzbanError(f"GET {url} → {resp.status_code}: {resp.text}")
    return resp.json()


async def _authorized_post(
    client: httpx.AsyncClient, url: str, payload: dict
) -> dict:
    token = await _get_token(client)
    resp = await client.post(url, json=payload, headers=_auth_header(token))
    if resp.status_code == 401:
        token = await _get_token(client, force_refresh=True)
        resp = await client.post(url, json=payload, headers=_auth_header(token))
    if not resp.is_success:
        raise MarzbanError(f"POST {url} → {resp.status_code}: {resp.text}")
    return resp.json()


def _sanitize_username(name: str) -> str:
    """Convert a user-provided config name into a valid Marzban username."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:32] if s else "user"


async def _user_exists(client: httpx.AsyncClient, username: str) -> bool:
    token = await _get_token(client)
    resp = await client.get(f"/api/user/{username}", headers=_auth_header(token))
    if resp.status_code == 401:
        token = await _get_token(client, force_refresh=True)
        resp = await client.get(f"/api/user/{username}", headers=_auth_header(token))
    if resp.status_code == 404:
        return False
    if resp.is_success:
        return True
    raise MarzbanError(f"Could not check username availability: {resp.status_code}")


async def check_username_available(config_name: str) -> bool:
    """Public helper — returns True if the sanitized name is free in Marzban."""
    username = _sanitize_username(config_name)
    try:
        async with _client() as client:
            return not await _user_exists(client, username)
    except httpx.TransportError as exc:
        raise MarzbanError(f"Cannot reach Marzban panel: {exc}") from exc


async def _fetch_inbounds(client: httpx.AsyncClient) -> dict[str, list[str]]:
    """
    Returns the panel's inbounds grouped by protocol, e.g.:
      {"vless": ["VLESS TCP REALITY", "VLESS WS"], "vmess": ["VMESS WS"]}
    """
    data = await _authorized_get(client, "/api/inbounds")
    # The API returns {protocol: [{"tag": "...", ...}, ...]}
    # Normalise to {protocol: [tag, ...]}
    result: dict[str, list[str]] = {}
    for proto, entries in data.items():
        tags = [e["tag"] for e in entries if "tag" in e]
        if tags:
            result[proto] = tags
    if not result:
        raise MarzbanError("Panel returned no configured inbounds")
    logger.debug("Fetched inbounds from panel: %s", list(result.keys()))
    return result


async def create_subscription(
    telegram_id: int,
    duration_days: int,
    data_limit_gb: int,
    config_name: str,
) -> tuple[str, str]:
    username = _sanitize_username(config_name)
    expire_ts = int(
        (datetime.now(tz=timezone.utc) + timedelta(days=duration_days)).timestamp()
    )
    data_limit_bytes = data_limit_gb * 1024**3 if data_limit_gb > 0 else 0

    logger.info(
        "Creating Marzban user %s for tg:%d (duration=%d days, data_limit=%d GB)",
        username,
        telegram_id,
        duration_days,
        data_limit_gb,
    )

    try:
        async with _client() as client:
            if await _user_exists(client, username):
                raise MarzbanError(
                    f"Username '{username}' is already taken in Marzban. "
                    "Ask the user to choose a different config name."
                )

            inbounds = await _fetch_inbounds(client)

            payload = {
                "username": username,
                "proxies": {proto: {} for proto in inbounds},
                "inbounds": inbounds,
                "expire": expire_ts,
                "data_limit": data_limit_bytes,
                "data_limit_reset_strategy": "no_reset",
                "status": "active",
            }

            result = await _authorized_post(client, "/api/user", payload)
    except MarzbanError:
        raise
    except httpx.TransportError as exc:
        raise MarzbanError(f"Cannot reach Marzban panel: {exc}") from exc

    subscription_url = result.get("subscription_url", "")
    if not subscription_url:
        raise MarzbanError("Marzban returned no subscription_url")

    logger.debug("Subscription URL created for %s", username)
    return username, subscription_url


def _rename_link(uri: str, name: str) -> str:
    """Inject `name` as the remark/display-name into a proxy URI."""
    if uri.startswith("vmess://"):
        try:
            padding = "=" * (-len(uri[8:]) % 4)
            data = json.loads(base64.b64decode(uri[8:] + padding).decode())
            data["ps"] = name
            encoded = base64.b64encode(
                json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
            ).decode()
            return f"vmess://{encoded}"
        except Exception:
            return uri

    # vless, trojan, ss, hysteria2, tuic, … — remark is the URL fragment
    # Use the raw name (no percent-encoding) — matches what Marzban itself writes
    if "#" in uri:
        return uri.rsplit("#", 1)[0] + "#" + name
    return uri + "#" + name


async def fetch_individual_links(marzban_username: str, config_name: str) -> list[str]:
    """
    Fetch individual proxy URIs for `marzban_username` from the panel API,
    then inject `config_name` as the remark on each link.
    Numeric suffixes are added when there are multiple links.
    """
    try:
        async with _client() as client:
            user_data = await _authorized_get(client, f"/api/user/{marzban_username}")
    except MarzbanError:
        raise
    except httpx.TransportError as exc:
        raise MarzbanError(f"Cannot reach Marzban panel: {exc}") from exc

    raw_links: list[str] = user_data.get("links", [])
    if not raw_links:
        raise MarzbanError(f"No links returned for user {marzban_username}")

    logger.info("Fetched %d links for Marzban user %s", len(raw_links), marzban_username)

    if len(raw_links) == 1:
        return [_rename_link(raw_links[0], config_name)]

    return [
        _rename_link(link, f"{config_name} {i + 1}")
        for i, link in enumerate(raw_links)
    ]
