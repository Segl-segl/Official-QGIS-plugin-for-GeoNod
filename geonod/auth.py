"""Device-pairing orchestration independent from QGIS widgets."""
from __future__ import annotations

from datetime import datetime, timezone
from time import sleep
from typing import Callable

from .api_client import GeoNodApiClient, GeoNodApiError, PairingStart


def _expires_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def wait_for_pairing(client: GeoNodApiClient, pairing: PairingStart, sleeper: Callable[[float], None] = sleep, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> str:
    """Poll until browser approval creates a device credential or the request expires."""
    deadline = _expires_at(pairing.expires_at)
    while now() < deadline:
        response = client.exchange_pairing(pairing)
        if response.get('state') == 'pending':
            sleeper(pairing.poll_interval_seconds)
            continue
        credential = response.get('credential')
        if response.get('state') == 'connected' and isinstance(credential, str) and credential:
            return credential
        raise GeoNodApiError('GeoNod kunde inte slutföra anslutningen.', code='pairing_incomplete')
    raise GeoNodApiError('Anslutningsförfrågan har gått ut. Försök igen.', code='pairing_expired')
