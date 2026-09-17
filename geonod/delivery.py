"""Safe manifest-driven delivery loading; QGIS layers are created on the UI thread."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from os.path import commonpath
from pathlib import Path
from typing import Any
from zipfile import ZipFile


@dataclass(frozen=True)
class DeliverySource:
    path: Path
    kind: str
    name: str
    sublayer: str | None = None
    layer_id: str | None = None


@dataclass(frozen=True)
class DeliveryAddResult:
    added: int
    failures: tuple[str, ...]
    style_warnings: tuple[str, ...]


def extract_delivery_archive(archive_path: str | Path, destination: str | Path) -> Path:
    archive, target = Path(archive_path), Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    with ZipFile(archive) as zip_file:
        for member in zip_file.infolist():
            member_path = (target / member.filename).resolve()
            if member_path != resolved_target and resolved_target not in member_path.parents:
                raise ValueError('Exportarkivet innehåller en osäker filsökväg.')
        zip_file.extractall(target)
    return target


def _safe_delivery_path(root: Path, relative_path: Any) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return None
    candidate = root / relative_path
    resolved_candidate = candidate.resolve()
    resolved_root = root.resolve()
    return candidate if resolved_root in resolved_candidate.parents and candidate.is_file() else None


def _kind_for_manifest_layer(actual_format: Any, path: Path) -> str | None:
    format_name = str(actual_format or '').upper()
    if format_name in ('GEOTIFF', 'COPC_LAZ') or path.suffix.lower() in ('.tif', '.tiff', '.laz'):
        return 'raster'
    if format_name in ('GPKG', 'GEOJSON', 'SHP', 'FILEGDB') or path.suffix.lower() in ('.gpkg', '.geojson', '.shp', '.fgb'):
        return 'vector'
    return None


def _manifest_sources(manifest_path: Path) -> list[DeliverySource]:
    try:
        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get('schema_version') != 1 or not isinstance(payload.get('layers'), list):
        return []
    root = manifest_path.parent
    sources = []
    for row in payload['layers']:
        if not isinstance(row, dict) or row.get('status') != 'delivered':
            continue
        path = _safe_delivery_path(root, row.get('output_dataset'))
        kind = _kind_for_manifest_layer(row.get('actual_format'), path) if path else None
        if path is None or kind is None:
            continue
        layer_id = str(row.get('layer_id') or '').strip() or None
        sublayer = str(row.get('output_layer_name') or '').strip() or None
        name = sublayer or layer_id or path.stem.replace('_', ' ')
        sources.append(DeliverySource(path, kind, name.replace('_', ' '), sublayer, layer_id))
    return sources


def _gpkg_sources(path: Path) -> list[DeliverySource]:
    """Compatibility fallback for legacy deliveries without a manifest."""
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            rows = connection.execute("SELECT table_name, data_type FROM gpkg_contents ORDER BY table_name").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return [
        DeliverySource(path, 'vector' if data_type == 'features' else 'raster', str(table_name).replace('_', ' '), str(table_name))
        for table_name, data_type in rows if data_type in ('features', 'tiles', '2d-gridded-coverage')
    ]


def discover_delivery_sources(root: str | Path) -> list[DeliverySource]:
    root_path = Path(root)
    manifests = sorted(root_path.rglob('DeliveryManifest.json'))
    if manifests:
        return _manifest_sources(manifests[0])
    result = []
    for path in sorted(root_path.rglob('*')):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == '.gpkg':
            result.extend(_gpkg_sources(path))
        elif suffix in ('.tif', '.tiff'):
            result.append(DeliverySource(path, 'raster', path.stem.replace('_', ' ')))
        elif suffix in ('.shp', '.geojson', '.json', '.fgb'):
            result.append(DeliverySource(path, 'vector', path.stem.replace('_', ' ')))
    return result


def qgis_source_uri(source: DeliverySource) -> str:
    if source.kind == 'raster' and source.sublayer and source.path.suffix.lower() == '.gpkg':
        return f'GPKG:"{source.path.absolute()}":{source.sublayer}'
    return str(source.path.absolute()) + (f'|layername={source.sublayer}' if source.sublayer else '')


def layer_load_error(layer: Any, kind: str) -> str | None:
    if not layer.isValid():
        return 'QGIS kunde inte öppna lagret.'
    crs = layer.crs()
    if not crs.isValid():
        return 'Lagret saknar ett giltigt CRS.'
    if kind != 'vector':
        return None
    layer.updateExtents()
    if layer.featureCount() <= 0:
        return 'Lagret innehåller inga objekt efter inläsning.'
    feature = next(layer.getFeatures(), None)
    if feature is None or feature.geometry().isNull() or feature.geometry().isEmpty():
        return 'Lagret saknar läsbar geometri efter inläsning.'
    if layer.extent().isEmpty():
        return 'Lagret har en tom geografisk utbredning efter inläsning.'
    return None


def _canvas_extent_for_layer(layer: Any, canvas: Any, project: Any) -> Any | None:
    try:
        from qgis.core import QgsCoordinateTransform
        extent = layer.extent()
        canvas_crs = canvas.mapSettings().destinationCrs()
        if layer.crs() != canvas_crs:
            extent = QgsCoordinateTransform(layer.crs(), canvas_crs, project.transformContext()).transformBoundingBox(extent)
        return extent if not extent.isEmpty() else None
    except Exception:
        return None


def needs_display_reprojection(layer_crs: Any, canvas_crs: Any) -> bool:
    """Whether a vector needs the robust memory-layer display fallback."""
    try:
        return bool(layer_crs.isValid() and canvas_crs.isValid() and layer_crs != canvas_crs)
    except (AttributeError, TypeError):
        return False


def _set_project_transform_context(layer: Any, project: Any) -> None:
    """Give all providers QGIS's project transform context before rendering."""
    try:
        layer.setTransformContext(project.transformContext())
    except (AttributeError, RuntimeError):
        pass


def display_package_path(sources: list[DeliverySource]) -> Path:
    """Keep all persistent display layers for one delivery in one sidecar GPKG."""
    vector_parents = [str(source.path.parent.resolve()) for source in sources if source.kind == 'vector']
    if not vector_parents:
        raise ValueError('Det finns inga vektorleveranser att skapa en visningskopia för.')
    return Path(commonpath(vector_parents)) / 'qgis_visning.gpkg'


def display_dataset_name(source: DeliverySource, used_names: set[str]) -> str:
    """A deterministic, safe GPKG sublayer name without cross-layer collisions."""
    raw = source.layer_id or source.sublayer or source.name or 'lager'
    base = ''.join(character.lower() if character.isalnum() else '_' for character in raw).strip('_') or 'lager'
    candidate, suffix = base, 2
    while candidate in used_names:
        candidate = f'{base}_{suffix}'
        suffix += 1
    used_names.add(candidate)
    return candidate


def persistent_display_uri(package_path: Path, package_layer_name: str) -> str:
    return f'{package_path.absolute()}|layername={package_layer_name}'


def display_layer_name(source: DeliverySource) -> str:
    """Keep the catalog name in the layer panel; technical details are properties."""
    return source.name


def delivery_group_name(archive_path: str | Path) -> str:
    """A human-readable local timestamp; export identifiers stay in layer properties."""
    timestamp = datetime.fromtimestamp(Path(archive_path).stat().st_mtime)
    months = ('jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec')
    return f'GeoNod — {timestamp.day} {months[timestamp.month - 1]} {timestamp:%H:%M}'


def _writer_error_message(result: Any) -> str | None:
    """Normalise QgsVectorFileWriter's version-dependent tuple result."""
    try:
        status = result[0] if isinstance(result, tuple) else result
        status_value = getattr(status, 'value', status)
        if status_value == 0 or str(status).endswith('NoError'):
            return None
        values = result if isinstance(result, tuple) else ()
        details = next((str(value) for value in reversed(values) if isinstance(value, str) and value.strip()), '')
        return details or 'QGIS kunde inte skriva den reprojicerade GeoPackage-filen.'
    except (TypeError, ValueError):
        return 'QGIS returnerade ett okänt fel vid skrivning av visningslagret.'


def _persistent_reprojected_vector_layer(source_layer: Any, source: DeliverySource, canvas_crs: Any,
                                          project: Any, package_path: Path, package_layer_name: str,
                                          overwrite_file: bool) -> Any:
    """Write a disk-backed GPKG view in the canvas CRS; do not alter source data."""
    from qgis.core import QgsCoordinateTransform, QgsVectorFileWriter, QgsVectorLayer

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.layerName = package_layer_name
    options.ct = QgsCoordinateTransform(source_layer.crs(), canvas_crs, project.transformContext())
    options.actionOnExistingFile = (
        QgsVectorFileWriter.CreateOrOverwriteFile if overwrite_file
        else QgsVectorFileWriter.CreateOrOverwriteLayer
    )
    package_path.parent.mkdir(parents=True, exist_ok=True)
    error = _writer_error_message(QgsVectorFileWriter.writeAsVectorFormatV3(
        source_layer, str(package_path), project.transformContext(), options,
    ))
    if error:
        raise RuntimeError(error)
    display = QgsVectorLayer(persistent_display_uri(package_path, package_layer_name), display_layer_name(source), 'ogr')
    validation_error = layer_load_error(display, 'vector')
    if validation_error:
        raise RuntimeError(validation_error)
    try:
        display.setRenderer(source_layer.renderer().clone())
    except (AttributeError, RuntimeError):
        pass
    _set_project_transform_context(display, project)
    display.setCustomProperty('geonodOriginalSource', str(source.path))
    display.setCustomProperty('geonodOriginalCrs', source_layer.crs().authid())
    display.setCustomProperty('geonodDisplaySource', str(package_path))
    display.setCustomProperty('geonodDisplayCrs', canvas_crs.authid())
    return display


def add_sources_to_qgis(sources: list[DeliverySource], group_name: str, canvas: Any = None) -> DeliveryAddResult:
    """Validate, style, add and repaint layers; zoom once after a multi-layer import."""
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
    from .styles import apply_optional_layer_style

    project = QgsProject.instance()
    group = project.layerTreeRoot().addGroup(group_name)
    added, failures, style_warnings, combined_extent = 0, [], [], None
    display_path = display_package_path(sources) if any(source.kind == 'vector' for source in sources) else None
    display_layer_names: set[str] = set()
    wrote_display_file = False
    for source in sources:
        uri = qgis_source_uri(source)
        layer = QgsRasterLayer(uri, source.name) if source.kind == 'raster' else QgsVectorLayer(uri, source.name, 'ogr')
        error = layer_load_error(layer, source.kind)
        if error:
            failures.append(f'{source.name}: {error}')
            continue
        style_warning = apply_optional_layer_style(layer, source.layer_id)
        if style_warning:
            style_warnings.append(f'{source.name}: {style_warning}')
        _set_project_transform_context(layer, project)
        display_layer = layer
        if source.kind == 'vector' and canvas is not None:
            canvas_crs = canvas.mapSettings().destinationCrs()
            if needs_display_reprojection(layer.crs(), canvas_crs):
                try:
                    if display_path is None:
                        raise RuntimeError('QGIS saknar en sökväg för den beständiga visningskopian.')
                    display_layer = _persistent_reprojected_vector_layer(
                        layer, source, canvas_crs, project, display_path,
                        display_dataset_name(source, display_layer_names), not wrote_display_file,
                    )
                    wrote_display_file = True
                except Exception as display_error:
                    failures.append(f'{source.name}: kunde inte skapa CRS-visning ({display_error})')
                    continue
        display_layer.triggerRepaint()
        project.addMapLayer(display_layer, False)
        group.addLayer(display_layer)
        added += 1
        if canvas is not None:
            extent = _canvas_extent_for_layer(display_layer, canvas, project)
            if extent is not None:
                if combined_extent is None:
                    combined_extent = extent
                else:
                    combined_extent.combineExtentWith(extent)
    if not added:
        project.layerTreeRoot().removeChildNode(group)
    elif canvas is not None:
        if combined_extent is not None:
            canvas.setExtent(combined_extent)
        canvas.refresh()
    return DeliveryAddResult(added, tuple(failures), tuple(style_warnings))
