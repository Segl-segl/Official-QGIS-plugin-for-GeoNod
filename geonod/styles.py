"""Optional QGIS-native QML styles for GeoNod delivery layers."""
from __future__ import annotations

from pathlib import Path
from typing import Any


STYLE_DIRECTORY = Path(__file__).resolve().parent / 'assets' / 'styles'


def qml_style_path(layer_id: str | None) -> Path | None:
    if not isinstance(layer_id, str) or not layer_id or Path(layer_id).name != layer_id:
        return None
    path = STYLE_DIRECTORY / f'{layer_id}.qml'
    return path if path.is_file() else None


def apply_optional_layer_style(layer: Any, layer_id: str | None) -> str | None:
    """Apply only a vendored QML. Missing styles deliberately keep QGIS defaults."""
    path = qml_style_path(layer_id)
    if path is None:
        return None
    try:
        message, success = layer.loadNamedStyle(str(path))
    except Exception as error:
        return f'QML-stilen kunde inte läsas ({error}).'
    if not success:
        return 'QML-stilen kunde inte tillämpas' + (f': {message}' if message else '.')
    layer.triggerRepaint()
    return None
