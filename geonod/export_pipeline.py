"""QGIS-independent client for GeoNod's existing durable export-order contract."""
from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Any, Callable, Iterable

from .api_client import GeoNodApiError
from .catalog import CatalogLayer


PREFERRED_VECTOR_FORMATS = ('GPKG', 'GeoJSON', 'SHP', 'FILEGDB')


def output_format_for_layer(layer: CatalogLayer) -> str | None:
    """Prefer QGIS-native GPKG; keep the API's raster format unchanged."""
    formats = {value.upper() for value in layer.available_output_formats}
    if layer.export_data_kind.lower() == 'raster' or 'GEOTIFF' in formats:
        return 'GeoTIFF' if 'GEOTIFF' in formats else None
    for format_name in PREFERRED_VECTOR_FORMATS:
        if format_name.upper() in formats:
            return format_name
    return None


def export_payload(layers: Iterable[CatalogLayer], polygon: dict[str, Any]) -> dict[str, Any]:
    selected, unsupported = [], []
    for layer in layers:
        output_format = output_format_for_layer(layer)
        if output_format is None:
            unsupported.append(layer.name)
        else:
            selected.append({'layer_id': layer.id, 'output_format': output_format})
    if unsupported:
        raise ValueError('Följande lager saknar ett format som QGIS kan läsa: ' + ', '.join(unsupported))
    if not selected:
        raise ValueError('Välj minst ett lager som kan exporteras.')
    return {'polygon': polygon, 'selectedLayers': selected, 'defaultVectorFormat': 'GPKG'}


def completed_order_or_raise(order: dict[str, Any]) -> dict[str, Any] | None:
    status = str(order.get('status') or '').lower()
    if status in ('queued', 'processing'):
        return None
    if status == 'completed' and order.get('downloadAvailable') is True:
        return order
    code = str(order.get('failureCode') or status or 'okänd status')
    raise GeoNodApiError(f'GeoNod-exporten kunde inte slutföras ({code}).', code=code)


def wait_for_export(client: Any, credential: str, organization_id: str, order: dict[str, Any], progress: Callable[[int], None], sleeper: Callable[[float], None] = sleep, is_cancelled: Callable[[], bool] = lambda: False, max_polls: int = 450) -> dict[str, Any]:
    """Poll the shared order API. Called only inside a QgsTask."""
    for _ in range(max_polls + 1):
        if is_cancelled():
            raise RuntimeError('Exporten avbröts i QGIS.')
        complete = completed_order_or_raise(order)
        if complete is not None:
            return complete
        customer_progress = order.get('customerProgress') if isinstance(order.get('customerProgress'), dict) else {}
        percentage = customer_progress.get('percentage')
        progress(max(15, min(89, int(percentage) if isinstance(percentage, int) else 20)))
        sleeper(2)
        order = client.export_order(credential, organization_id, str(order.get('id') or ''))
    raise TimeoutError('Exporten tar längre tid än väntat. Den fortsätter i GeoNod och kan hämtas senare.')


def new_export_directory(base_directory: str | Path) -> Path:
    from datetime import datetime
    destination = Path(base_directory) / ('Export_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    destination.mkdir(parents=True, exist_ok=False)
    return destination
