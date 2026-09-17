"""Small synchronous HTTP client; callers run it in a QgsTask, never on the UI thread."""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = 'https://geonod.se'


class GeoNodApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def normalize_base_url(value: str = DEFAULT_BASE_URL) -> str:
    candidate = str(value or DEFAULT_BASE_URL).strip().rstrip('/')
    if not candidate.startswith(('https://', 'http://')):
        raise ValueError('GeoNods adress måste börja med http:// eller https://.')
    return candidate


def _error_from_response(body: bytes, status: int | None = None) -> GeoNodApiError:
    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    message = payload.get('message') if isinstance(payload, dict) else None
    code = payload.get('error') if isinstance(payload, dict) else None
    return GeoNodApiError(message or 'GeoNod kunde inte slutföra begäran.', status, code)


@dataclass(frozen=True)
class PairingStart:
    pairing_id: str
    approval_url: str
    exchange_secret: str
    expires_at: str
    poll_interval_seconds: int


class GeoNodApiClient:
    """Client for the neutral GIS device-pairing and catalog contract."""
    def __init__(self, base_url: str = DEFAULT_BASE_URL, opener: Callable[..., Any] = urlopen):
        self.base_url = normalize_base_url(base_url)
        self._opener = opener

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, credential: str | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = Request(self.base_url + path, data=body, method=method)
        request.add_header('Accept', 'application/json')
        if body is not None:
            request.add_header('Content-Type', 'application/json')
        if credential:
            request.add_header('Authorization', 'GeoNod-Device ' + credential)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with self._opener(request, timeout=30) as response:
                raw = response.read()
                status = getattr(response, 'status', response.getcode())
        except HTTPError as error:
            raise _error_from_response(error.read(), error.code) from error
        except URLError as error:
            raise GeoNodApiError('Kunde inte ansluta till GeoNod. Kontrollera nätverket och försök igen.') from error
        except OSError as error:
            raise GeoNodApiError('Kunde inte ansluta till GeoNod. Kontrollera nätverket och försök igen.') from error
        if not 200 <= status < 300:
            raise _error_from_response(raw, status)
        try:
            decoded = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GeoNodApiError('GeoNod returnerade ett ogiltigt svar.', status, 'invalid_response') from error
        if not isinstance(decoded, dict):
            raise GeoNodApiError('GeoNod returnerade ett ogiltigt svar.', status, 'invalid_response')
        return status, decoded

    def start_pairing(self, device_name: str, client_version: str) -> PairingStart:
        _, response = self._request('POST', '/api/organizations?gis_pairing=start', {
            'deviceName': device_name,
            'clientVersion': client_version,
        })
        required = ('pairingId', 'approvalUrl', 'exchangeSecret', 'expiresAt')
        if not all(isinstance(response.get(key), str) and response[key] for key in required):
            raise GeoNodApiError('GeoNod returnerade ett ofullständigt anslutningssvar.', code='invalid_response')
        return PairingStart(
            pairing_id=response['pairingId'], approval_url=response['approvalUrl'], exchange_secret=response['exchangeSecret'],
            expires_at=response['expiresAt'], poll_interval_seconds=max(1, min(int(response.get('pollIntervalSeconds', 2)), 10)),
        )

    def exchange_pairing(self, pairing: PairingStart) -> dict[str, Any]:
        _, response = self._request('POST', '/api/organizations?gis_pairing=exchange', {
            'pairingId': pairing.pairing_id,
            'exchangeSecret': pairing.exchange_secret,
        })
        return response

    def session(self, credential: str) -> dict[str, Any]:
        return self._request('GET', '/api/organizations?gis=session', credential=credential)[1]

    def catalog(self, credential: str) -> dict[str, Any]:
        return self._request('GET', '/api/organizations?gis=catalog', credential=credential)[1]

    def project_areas(self, credential: str) -> dict[str, Any]:
        """List project AOIs through the same GIS-neutral device contract."""
        return self._request('GET', '/api/organizations?gis=project_areas', credential=credential)[1]

    def create_export_order(self, credential: str, organization_id: str, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        path = '/api/organizations/{}/export-orders'.format(quote(organization_id, safe=''))
        response = self._request('POST', path, payload, credential, {'Idempotency-Key': idempotency_key})[1]
        order = response.get('order')
        if not isinstance(order, dict) or not isinstance(order.get('id'), str):
            raise GeoNodApiError('GeoNod returnerade en ogiltig exportorder.', code='invalid_response')
        return order

    def export_order(self, credential: str, organization_id: str, order_id: str) -> dict[str, Any]:
        path = '/api/organizations/{}/export-orders/{}'.format(quote(organization_id, safe=''), quote(order_id, safe=''))
        response = self._request('GET', path, credential=credential)[1]
        order = response.get('order')
        if not isinstance(order, dict) or not isinstance(order.get('id'), str):
            raise GeoNodApiError('GeoNod returnerade en ogiltig exportstatus.', code='invalid_response')
        return order

    def download_export_order(self, credential: str, organization_id: str, order_id: str, destination: str | Path) -> Path:
        path = '/api/organizations/{}/export-orders/{}/download'.format(quote(organization_id, safe=''), quote(order_id, safe=''))
        request = Request(self.base_url + path, method='GET')
        request.add_header('Authorization', 'GeoNod-Device ' + credential)
        request.add_header('Accept', 'application/zip')
        target = Path(destination)
        try:
            with self._opener(request, timeout=15 * 60) as response:
                status = getattr(response, 'status', response.getcode())
                if not 200 <= status < 300:
                    raise _error_from_response(response.read(), status)
                created = False
                try:
                    with target.open('xb') as file:
                        created = True
                        while True:
                            chunk = response.read(81920)
                            if not chunk:
                                break
                            file.write(chunk)
                except Exception:
                    if created:
                        target.unlink(missing_ok=True)
                    raise
        except FileExistsError as error:
            raise GeoNodApiError('Exportfilen finns redan. Försök igen.') from error
        except HTTPError as error:
            raise _error_from_response(error.read(), error.code) from error
        except (URLError, OSError) as error:
            raise GeoNodApiError('Kunde inte hämta GeoNod-leveransen. Kontrollera nätverket och försök igen.') from error
        return target

    def revoke(self, credential: str) -> None:
        self._request('POST', '/api/organizations?gis_pairing=revoke_self', {}, credential)
