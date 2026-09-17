"""Small widget-independent state text for the staged QGIS workflow."""
from __future__ import annotations


def delivery_status(selected_layer_count: int, has_area: bool) -> str:
    if selected_layer_count <= 0:
        return 'Välj minst ett lager. Exporten aktiveras i nästa steg.'
    if not has_area:
        return f'{selected_layer_count} lager är valda. Välj ett område för att förbereda leveransen.'
    return f'{selected_layer_count} lager är valda och ett område är förberett. Exporten aktiveras i nästa steg.'


def catalog_expanded_for_search(query: str) -> bool:
    """Keep catalog groups collapsed until a search needs to reveal a match."""
    return bool(str(query or '').strip())


def aoi_selected_state(mode: str | None) -> dict[str, bool]:
    """The three AOI choices are mutually exclusive and persist independently of status text."""
    return {choice: mode == choice for choice in ('current_view', 'selected_polygon', 'project_area')}


def aoi_mode_has_geometry(mode: str | None, has_geometry: bool) -> bool:
    """A selected source is not export-ready until it has supplied an AOI."""
    return mode in {'current_view', 'selected_polygon', 'project_area'} and bool(has_geometry)
