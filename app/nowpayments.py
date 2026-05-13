from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.nowpayments.io/v1"

# Statuses that mean the payment is complete and we can activate the subscription
SUCCESS_STATUSES = {"confirmed", "finished"}
# Statuses that mean the payment window is over / something went wrong
FAILED_STATUSES = {"failed", "expired", "refunded"}

# In-memory JWT cache: email → (token, expiry)
_jwt_cache: dict[str, tuple[str, datetime]] = {}


class NowPaymentsError(Exception):
    pass


def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Content-Type": "application/json"}


async def _get_jwt(
    email: str,
    password: str,
    proxy_url: str | None = None,
) -> str:
    """Return a valid JWT for the NOWPayments dashboard API, refreshing if needed."""
    cached = _jwt_cache.get(email)
    if cached:
        token, expiry = cached
        if datetime.now(tz=timezone.utc) < expiry:
            return token

    async with httpx.AsyncClient(timeout=20.0, proxy=proxy_url) as client:
        try:
            resp = await client.post(
                f"{_BASE}/auth",
                json={"email": email, "password": password},
            )
        except httpx.TransportError as exc:
            raise NowPaymentsError(f"Cannot reach NOWPayments auth: {exc}") from exc

    if not resp.is_success:
        raise NowPaymentsError(
            f"NOWPayments auth error {resp.status_code}: {resp.text[:200]}"
        )

    token = resp.json()["token"]
    # JWT lifetime is 5 min; refresh every 3 min to stay well inside the window
    _jwt_cache[email] = (token, datetime.now(tz=timezone.utc) + timedelta(minutes=3))
    logger.info("NOWPayments JWT refreshed for %s", email)
    return token


async def create_invoice(
    api_key: str,
    price_usd: float,
    order_id: int,
    description: str,
    proxy_url: str | None = None,
) -> dict:
    """Create a hosted invoice page. Returns dict with 'id' and 'invoice_url'."""
    payload = {
        "price_amount": price_usd,
        "price_currency": "usd",
        "order_id": str(order_id),
        "order_description": description,
    }
    async with httpx.AsyncClient(timeout=20.0, proxy=proxy_url) as client:
        try:
            resp = await client.post(
                f"{_BASE}/invoice", json=payload, headers=_headers(api_key)
            )
        except httpx.TransportError as exc:
            raise NowPaymentsError(f"Cannot reach NOWPayments: {exc}") from exc
    if not resp.is_success:
        raise NowPaymentsError(
            f"NOWPayments error {resp.status_code}: {resp.text[:200]}"
        )
    data = resp.json()
    logger.info(
        "NOWPayments invoice created: id=%s url=%s",
        data.get("id"), data.get("invoice_url"),
    )
    return data


async def get_payments_for_invoice(
    api_key: str,
    email: str,
    password: str,
    invoice_id: str,
    proxy_url: str | None = None,
) -> list[dict]:
    """Return payments tied to a NOWPayments invoice ID (newest first). Requires JWT auth."""
    jwt = await _get_jwt(email, password, proxy_url)
    headers = {**_headers(api_key), "Authorization": f"Bearer {jwt}"}

    async with httpx.AsyncClient(timeout=20.0, proxy=proxy_url) as client:
        try:
            resp = await client.get(
                f"{_BASE}/payment/",
                params={
                    "invoiceId": invoice_id,
                    "limit": 5,
                    "sortBy": "created_at",
                    "orderBy": "desc",
                },
                headers=headers,
            )
        except httpx.TransportError as exc:
            raise NowPaymentsError(f"Cannot reach NOWPayments: {exc}") from exc

    if not resp.is_success:
        raise NowPaymentsError(
            f"NOWPayments error {resp.status_code}: {resp.text[:200]}"
        )
    data = resp.json()
    if isinstance(data, dict):
        return data.get("data", [])
    return data if isinstance(data, list) else []
