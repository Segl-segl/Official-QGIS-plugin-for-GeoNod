"""Temporary, project-area-only map highlight for the QGIS canvas."""
from __future__ import annotations

import json
from typing import Any


def clear_project_area_overlay(overlay: Any) -> None:
    """Remove the visual aid without touching the GeoJSON used for export."""
    if overlay is None:
        return
    try:
        overlay.hide()
        overlay.reset()
        overlay.deleteLater()
    except (AttributeError, RuntimeError):
        # A canvas can already have been destroyed during QGIS shutdown.
        pass


def show_project_area_overlay(canvas: Any, polygon: dict[str, Any]) -> Any:
    """Draw WGS84 GeoJSON in the canvas CRS and return its removable rubber band."""
    from qgis.PyQt.QtGui import QColor
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject, QgsWkbTypes
    from qgis.gui import QgsRubberBand

    geometry = QgsGeometry.fromGeoJson(json.dumps(polygon))
    if geometry.isNull() or geometry.isEmpty():
        raise ValueError('Projektområdets geometri kunde inte visas.')
    destination_crs = canvas.mapSettings().destinationCrs()
    transform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem('EPSG:4326'), destination_crs, QgsProject.instance().transformContext(),
    )
    if geometry.transform(transform) not in (None, 0):
        raise ValueError('Projektområdet kunde inte omprojiceras till kartans CRS.')
    overlay = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
    overlay.setToGeometry(geometry, None)
    overlay.setColor(QColor(63, 107, 88, 220))
    overlay.setFillColor(QColor(63, 107, 88, 48))
    overlay.setWidth(2)
    overlay.show()
    return overlay
