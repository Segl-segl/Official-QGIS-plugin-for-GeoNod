"""QGIS-independent catalog parsing, hierarchy and selection state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class CatalogLayer:
    id: str
    name: str
    source: str
    category: str
    subcategory: str
    description: str = ''
    display_order: int = 0
    category_order: int = 0
    subcategory_order: int = 0
    export_data_kind: str = ''
    available_output_formats: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogSubcategory:
    name: str
    layers: tuple[CatalogLayer, ...]


@dataclass(frozen=True)
class CatalogCategory:
    name: str
    subcategories: tuple[CatalogSubcategory, ...]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ''


def _order(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_catalog(payload: dict[str, Any]) -> list[CatalogLayer]:
    """Return the display-safe subset of GeoNod's shared public catalog."""
    rows = payload.get('layers', []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    result: list[CatalogLayer] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        layer_id, name = _text(row.get('id')), _text(row.get('name'))
        if not layer_id or not name:
            continue
        result.append(CatalogLayer(
            id=layer_id,
            name=name,
            source=_text(row.get('source')) or _text(row.get('provider')) or '—',
            category=_text(row.get('category')) or 'Övrigt',
            subcategory=_text(row.get('subcategory')) or 'Övrigt',
            description=_text(row.get('public_description')),
            display_order=_order(row.get('display_order')),
            category_order=_order(row.get('category_order')),
            subcategory_order=_order(row.get('subcategory_order')),
            export_data_kind=_text(row.get('export_data_kind')),
            available_output_formats=tuple(
                value.strip() for value in row.get('available_output_formats', [])
                if isinstance(value, str) and value.strip()
            ),
        ))
    return sorted(result, key=lambda layer: (
        layer.category_order, layer.subcategory_order, layer.display_order,
        layer.category.casefold(), layer.subcategory.casefold(), layer.name.casefold(),
    ))


def filter_layers(layers: Iterable[CatalogLayer], query: str) -> list[CatalogLayer]:
    needle = _text(query).casefold()
    if not needle:
        return list(layers)
    return [layer for layer in layers if needle in ' '.join((
        layer.name, layer.source, layer.category, layer.subcategory, layer.description,
    )).casefold()]


def catalog_hierarchy(layers: Iterable[CatalogLayer]) -> list[CatalogCategory]:
    """Build the category → subcategory → layer tree used by every GIS UI."""
    grouped: dict[str, dict[str, list[CatalogLayer]]] = {}
    for layer in layers:
        grouped.setdefault(layer.category, {}).setdefault(layer.subcategory, []).append(layer)
    categories: list[CatalogCategory] = []
    for category, subcategories in grouped.items():
        ordered_subcategories = []
        for name, category_layers in subcategories.items():
            ordered_subcategories.append(CatalogSubcategory(name, tuple(sorted(
                category_layers, key=lambda layer: (layer.display_order, layer.name.casefold()),
            ))))
        ordered_subcategories.sort(key=lambda group: (
            min((layer.subcategory_order for layer in group.layers), default=0), group.name.casefold(),
        ))
        categories.append(CatalogCategory(category, tuple(ordered_subcategories)))
    categories.sort(key=lambda group: (
        min((layer.category_order for subcategory in group.subcategories for layer in subcategory.layers), default=0),
        group.name.casefold(),
    ))
    return categories


class CatalogSelection:
    """Selection state separated from widgets so it remains easy to test."""
    def __init__(self):
        self._selected: set[str] = set()

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._selected)

    def is_selected(self, layer_id: str) -> bool:
        return layer_id in self._selected

    def toggle(self, layer_id: str) -> None:
        if layer_id in self._selected:
            self._selected.remove(layer_id)
        else:
            self._selected.add(layer_id)

    def set_group(self, layers: Iterable[CatalogLayer], selected: bool) -> None:
        ids = {layer.id for layer in layers}
        if selected:
            self._selected.update(ids)
        else:
            self._selected.difference_update(ids)

    def group_is_all_selected(self, layers: Iterable[CatalogLayer]) -> bool:
        ids = {layer.id for layer in layers}
        return bool(ids) and ids.issubset(self._selected)

    def retain(self, available_layers: Iterable[CatalogLayer]) -> None:
        self._selected.intersection_update(layer.id for layer in available_layers)
