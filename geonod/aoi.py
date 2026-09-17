"""AOI capture helpers. QGIS map access is intentionally explicit and synchronous."""
from __future__ import annotations

import json
import math
from typing import Any


class AoiCaptureError(ValueError):
    pass


def validate_polygon(geometry: Any) -> dict[str, Any]:
    """Validate the Polygon-only, EPSG:4326 GeoJSON contract used by GeoNod."""
    if not isinstance(geometry, dict) or geometry.get('type') != 'Polygon':
        raise AoiCaptureError('Området måste vara en polygon.')
    coordinates = geometry.get('coordinates')
    if not isinstance(coordinates, list) or not coordinates:
        raise AoiCaptureError('Polygonen saknar koordinater.')
    for ring in coordinates:
        if not isinstance(ring, list) or len(ring) < 4:
            raise AoiCaptureError('Varje polygonring måste ha minst fyra koordinater.')
        for position in ring:
            if (not isinstance(position, list) or len(position) < 2
                    or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in position[:2])):
                raise AoiCaptureError('Polygonen innehåller ogiltiga koordinater.')
            if not -180 <= position[0] <= 180 or not -90 <= position[1] <= 90:
                raise AoiCaptureError('Polygonen ligger utanför WGS84:s giltiga koordinatområde.')
        if ring[0][:2] != ring[-1][:2]:
            raise AoiCaptureError('Polygonringarna måste vara slutna.')
    return {'type': 'Polygon', 'coordinates': coordinates}


def selected_feature_from_layer(layer: Any) -> tuple[Any, int]:
    """Read exactly one feature by selected id, never from a stale canvas click."""
    try:
        count = int(layer.selectedFeatureCount())
        selected_ids = list(layer.selectedFeatureIds())
    except (AttributeError, TypeError, ValueError) as error:
        raise AoiCaptureError('Det aktiva lagrets markering kunde inte läsas.') from error
    if count == 0 or not selected_ids:
        raise AoiCaptureError('Markera exakt ett polygonobjekt i det aktiva polygonlagret.')
    if count != 1 or len(selected_ids) != 1:
        raise AoiCaptureError('Markera exakt ett polygonobjekt i det aktiva polygonlagret, inte flera.')
    feature_id = selected_ids[0]
    try:
        feature = layer.getFeature(feature_id)
    except (AttributeError, TypeError, ValueError) as error:
        raise AoiCaptureError('Det markerade polygonobjektet kunde inte hämtas från lagret.') from error
    if feature is None or (hasattr(feature, 'isValid') and not feature.isValid()):
        raise AoiCaptureError('Det markerade polygonobjektet kunde inte hämtas från lagret.')
    return feature, feature_id


def geometry_to_polygon(geometry: Any) -> dict[str, Any]:
    """Convert a QGIS Polygon/MultiPolygon to GeoNod's multi-ring Polygon."""
    try:
        parsed = json.loads(geometry.asJson())
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise AoiCaptureError('Polygonen kunde inte läsas som GeoJSON.') from error
    if isinstance(parsed, dict) and parsed.get('type') == 'MultiPolygon':
        polygons = parsed.get('coordinates')
        if not isinstance(polygons, list):
            raise AoiCaptureError('Multipolygonen saknar koordinater.')
        # ArcGIS Pro serialises all Polygon parts as rings in the shared
        # Polygon request contract. Preserve every exterior and interior ring.
        parsed = {
            'type': 'Polygon',
            'coordinates': [ring for polygon in polygons if isinstance(polygon, list) for ring in polygon],
        }
    return validate_polygon(parsed)


def _to_wgs84(geometry: Any, source_crs: Any, project: Any) -> dict[str, Any]:
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry
    transformed = QgsGeometry(geometry)
    transform = QgsCoordinateTransform(source_crs, QgsCoordinateReferenceSystem('EPSG:4326'), project.transformContext())
    result = transformed.transform(transform)
    if result not in (None, 0):
        raise AoiCaptureError('Området kunde inte omprojiceras till WGS84.')
    return geometry_to_polygon(transformed)


def capture_current_view(iface: Any) -> dict[str, Any]:
    """Capture the active canvas extent at click time and transform it to EPSG:4326."""
    from qgis.core import QgsGeometry, QgsProject
    canvas = iface.mapCanvas()
    if canvas is None or canvas.extent().isEmpty():
        raise AoiCaptureError('Öppna en karta med en giltig utbredning först.')
    return _to_wgs84(QgsGeometry.fromRect(canvas.extent()), canvas.mapSettings().destinationCrs(), QgsProject.instance())


def capture_selected_polygon(iface: Any) -> tuple[dict[str, Any], str, int]:
    """Capture exactly one selected polygon feature from the active vector layer."""
    from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
    layer = iface.activeLayer()
    if not isinstance(layer, QgsVectorLayer) or layer.geometryType() != QgsWkbTypes.PolygonGeometry:
        raise AoiCaptureError('Välj ett polygonlager som aktivt lager först.')
    feature, feature_id = selected_feature_from_layer(layer)
    geometry = feature.geometry()
    if geometry is None or geometry.isEmpty() or QgsWkbTypes.geometryType(geometry.wkbType()) != QgsWkbTypes.PolygonGeometry:
        raise AoiCaptureError('Det markerade objektet måste vara en giltig polygon.')
    source_crs = layer.crs()
    if source_crs is None or not source_crs.isValid():
        raise AoiCaptureError('Det aktiva polygonlagret saknar ett giltigt koordinatsystem.')
    return _to_wgs84(geometry, source_crs, QgsProject.instance()), layer.name(), int(feature_id)
