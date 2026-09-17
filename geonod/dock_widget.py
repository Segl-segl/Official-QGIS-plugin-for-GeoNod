"""Native PyQt GeoNod workflow panel; network and GIS work stay in the plugin."""
from __future__ import annotations

from typing import Any, Iterable

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QProgressBar, QScrollArea, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .catalog import CatalogLayer, CatalogSelection, catalog_hierarchy, filter_layers
from .workflow import aoi_selected_state, catalog_expanded_for_search, delivery_status


INK = '#18272D'
MUTED = '#536066'
PAPER = '#F4F1E9'
SURFACE = '#FFFFFF'
SUBTLE = '#EBE9E1'
FOREST = '#3F6B58'
FOREST_SOFT = '#E4ECE7'
BORDER = '#D8D8D0'


class GeoNodDockWidget(QWidget):
    connect_requested = pyqtSignal()
    disconnect_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    search_changed = pyqtSignal(str)
    selection_changed = pyqtSignal(object)
    current_view_requested = pyqtSignal()
    selected_polygon_requested = pyqtSignal()
    capture_selected_polygon_requested = pyqtSignal()
    project_area_requested = pyqtSignal(object)
    add_to_qgis_requested = pyqtSignal()
    download_requested = pyqtSignal()
    choose_destination_requested = pyqtSignal()
    reset_destination_requested = pyqtSignal()
    help_requested = pyqtSignal()
    open_export_details_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layers: list[CatalogLayer] = []
        self._selection = CatalogSelection()
        self._project_areas: list[dict[str, Any]] = []
        self._has_area = False
        self._area_mode = None
        self._layer_widgets = {}
        self._group_buttons = []
        self._build()

    def _build(self):
        self.setStyleSheet(f'GeoNodDockWidget {{ background: {PAPER}; color: {INK}; }}')
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f'background: {SURFACE}; border-bottom: 1px solid {BORDER};')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 12)
        title_row = QHBoxLayout()
        title = QLabel('GeoNod')
        title.setStyleSheet(f'font-size: 24px; font-weight: 600; color: {INK};')
        self.help_button = self._button('?')
        self.help_button.setFixedSize(28, 28)
        self.help_button.setToolTip('Öppna hjälp för GeoNod och QGIS')
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.help_button)
        subtitle = QLabel('Geodata direkt i QGIS')
        subtitle.setStyleSheet(f'color: {MUTED};')
        header_layout.addLayout(title_row)
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 18)
        layout.setSpacing(12)

        account = self._card(FOREST_SOFT)
        account_layout = QHBoxLayout(account)
        account_layout.setContentsMargins(14, 12, 14, 12)
        account_text = QVBoxLayout()
        account_text.setSpacing(3)
        account_label = QLabel('GeoNod-konto')
        account_label.setStyleSheet(f'font-weight: 600; color: {INK};')
        self.status = QLabel('Inte ansluten')
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f'color: {MUTED};')
        self.organization = QLabel('Organisation: —')
        self.organization.setStyleSheet(f'color: {MUTED}; font-size: 11px;')
        account_text.addWidget(account_label)
        account_text.addWidget(self.status)
        account_text.addWidget(self.organization)
        account_layout.addLayout(account_text, 1)
        self.connect_button = self._button('Anslut', primary=True)
        self.disconnect_button = self._button('Koppla från')
        self.disconnect_button.setVisible(False)
        actions = QVBoxLayout()
        actions.addWidget(self.connect_button)
        actions.addWidget(self.disconnect_button)
        account_layout.addLayout(actions)
        layout.addWidget(account)

        catalog = self._card()
        catalog_layout = QVBoxLayout(catalog)
        catalog_layout.setContentsMargins(14, 14, 14, 14)
        catalog_layout.setSpacing(10)
        catalog_layout.addLayout(self._step_heading('1', 'Underlag', 'Sök och välj geodata från GeoNods lagerkatalog.'))
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Sök lager, kategori eller leverantör')
        self.search.setEnabled(False)
        self.search.setClearButtonEnabled(True)
        self.refresh_button = self._button('Uppdatera')
        self.refresh_button.setEnabled(False)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.refresh_button)
        catalog_layout.addLayout(search_row)
        self.layers = QTreeWidget()
        self.layers.setHeaderHidden(True)
        self.layers.setRootIsDecorated(True)
        self.layers.setIndentation(14)
        self.layers.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.layers.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layers.setMinimumHeight(220)
        self.layers.setEnabled(False)
        self.layers.setStyleSheet(f'QTreeWidget {{ background: transparent; border: 0; }} QTreeWidget::item {{ border: 0; }}')
        catalog_layout.addWidget(self.layers)
        self.empty = QLabel('Anslut till GeoNod för att se lagerkatalogen.')
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(f'color: {MUTED}; padding: 10px;')
        catalog_layout.addWidget(self.empty)
        layout.addWidget(catalog)

        area = self._card()
        area_layout = QVBoxLayout(area)
        area_layout.setContentsMargins(14, 14, 14, 14)
        area_layout.setSpacing(10)
        area_layout.addLayout(self._step_heading('2', 'Område', 'Välj vilket område som ska användas när exportflödet blir tillgängligt.'))
        self.current_view_button = self._button('Aktuell kartvy', primary=True)
        self.selected_polygon_button = self._button('Vald polygon')
        self.capture_selected_polygon_button = self._button('Använd markerad polygon')
        self.capture_selected_polygon_button.setVisible(False)
        self.capture_selected_polygon_button.setEnabled(False)
        area_layout.addWidget(self.current_view_button)
        area_layout.addWidget(self.selected_polygon_button)
        area_layout.addWidget(self.capture_selected_polygon_button)
        project_row = QHBoxLayout()
        self.project_areas = QComboBox()
        self.project_areas.setEnabled(False)
        self.project_areas.addItem('Inga projektområden tillgängliga', None)
        self.use_project_area_button = self._button('Använd')
        self.use_project_area_button.setEnabled(False)
        project_row.addWidget(self.project_areas, 1)
        project_row.addWidget(self.use_project_area_button)
        area_layout.addWidget(QLabel('Projektområde'))
        area_layout.addLayout(project_row)
        self.area_status = QLabel('Välj Aktuell kartvy eller en markerad polygon.')
        self.area_status.setWordWrap(True)
        self.area_status.setStyleSheet(f'color: {MUTED}; font-size: 11px;')
        area_layout.addWidget(self.area_status)
        layout.addWidget(area)

        delivery = self._card()
        delivery_layout = QVBoxLayout(delivery)
        delivery_layout.setContentsMargins(14, 14, 14, 14)
        delivery_layout.setSpacing(6)
        delivery_layout.addLayout(self._step_heading('3', 'Export och leverans', 'Skapa en GeoNod-leverans och använd den direkt i QGIS eller spara den lokalt.'))
        self.delivery_status = QLabel('Välj underlag och område för att förbereda leveransen.')
        self.delivery_status.setWordWrap(True)
        self.delivery_status.setStyleSheet(f'color: {MUTED};')
        delivery_layout.addWidget(self.delivery_status)
        self.add_to_qgis_button = self._button('Ladda ner och lägg till i QGIS', primary=True)
        self.download_button = self._button('Ladda ner lokalt')
        self.add_to_qgis_button.setEnabled(False)
        self.download_button.setEnabled(False)
        delivery_layout.addWidget(self.add_to_qgis_button)
        delivery_layout.addWidget(self.download_button)
        destination_label = QLabel('Sparplats för lokal export')
        destination_label.setStyleSheet(f'font-weight: 600; color: {INK}; font-size: 11px; margin-top: 4px;')
        delivery_layout.addWidget(destination_label)
        self.destination = QLabel('Projektets GeoNod-mapp (standard)')
        self.destination.setWordWrap(True)
        self.destination.setStyleSheet(f'color: {MUTED}; font-size: 10px;')
        delivery_layout.addWidget(self.destination)
        destination_actions = QHBoxLayout()
        self.choose_destination_button = self._button('Välj mapp…')
        self.reset_destination_button = self._button('Använd projektmappen')
        self.reset_destination_button.setVisible(False)
        destination_actions.addWidget(self.choose_destination_button)
        destination_actions.addWidget(self.reset_destination_button)
        destination_actions.addStretch(1)
        delivery_layout.addLayout(destination_actions)
        self.export_stage = QLabel('')
        self.export_stage.setWordWrap(True)
        self.export_stage.setStyleSheet(f'color: {MUTED}; font-size: 10px;')
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        self.export_progress.setValue(0)
        self.export_progress.setTextVisible(False)
        self.export_progress.setMaximumHeight(5)
        self.export_progress.setStyleSheet(f'QProgressBar {{ border: 0; background: {SUBTLE}; border-radius: 2px; }} QProgressBar::chunk {{ background: {FOREST}; border-radius: 2px; }}')
        self.export_progress.setVisible(False)
        self.export_stage.setVisible(False)
        delivery_layout.addWidget(self.export_stage)
        delivery_layout.addWidget(self.export_progress)
        self.export_details_button = self._button('Visa exportdetaljer i GeoNod')
        self.export_details_button.setVisible(False)
        delivery_layout.addWidget(self.export_details_button)
        layout.addWidget(delivery)

        version = QFrame()
        version.setStyleSheet(f'QFrame {{ background: transparent; border: 0; }}')
        version_layout = QVBoxLayout(version)
        version_layout.setContentsMargins(2, 2, 2, 0)
        version_layout.setSpacing(2)
        self.version_label = QLabel('GeoNod för QGIS')
        self.version_label.setStyleSheet(f'color: {MUTED}; font-size: 10px;')
        self.version_status = QLabel('Versionsstatus laddas lokalt.')
        self.version_status.setWordWrap(True)
        self.version_status.setStyleSheet(f'color: {MUTED}; font-size: 10px;')
        self.update_button = self._button('Uppdatera GeoNod')
        self.update_button.setVisible(False)
        version_layout.addWidget(self.version_label)
        version_layout.addWidget(self.version_status)
        version_layout.addWidget(self.update_button)
        layout.addWidget(version)
        layout.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self.connect_button.clicked.connect(self.connect_requested)
        self.disconnect_button.clicked.connect(self.disconnect_requested)
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.search.textChanged.connect(self._on_search_changed)
        self.current_view_button.clicked.connect(self.current_view_requested)
        self.selected_polygon_button.clicked.connect(self.selected_polygon_requested)
        self.capture_selected_polygon_button.clicked.connect(self.capture_selected_polygon_requested)
        self.use_project_area_button.clicked.connect(self._request_project_area)
        self.add_to_qgis_button.clicked.connect(self.add_to_qgis_requested)
        self.download_button.clicked.connect(self.download_requested)
        self.choose_destination_button.clicked.connect(self.choose_destination_requested)
        self.reset_destination_button.clicked.connect(self.reset_destination_requested)
        self.help_button.clicked.connect(self.help_requested)
        self.export_details_button.clicked.connect(self.open_export_details_requested)
        self._set_area_mode(None)

    def _card(self, background: str = SURFACE) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f'QFrame {{ background: {background}; border: 1px solid {BORDER}; border-radius: 8px; }}')
        return card

    def _button(self, text: str, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setStyleSheet(f'QPushButton {{ background: {FOREST}; color: white; border: 1px solid {FOREST}; border-radius: 5px; padding: 7px 10px; font-weight: 600; }} QPushButton:disabled {{ background: {BORDER}; border-color: {BORDER}; }}')
        else:
            button.setStyleSheet(f'QPushButton {{ background: {SURFACE}; color: {INK}; border: 1px solid {BORDER}; border-radius: 5px; padding: 6px 9px; }} QPushButton:disabled {{ color: {MUTED}; background: {SUBTLE}; }}')
        return button

    def _area_button_style(self, selected: bool) -> str:
        if selected:
            return f'QPushButton {{ background: {FOREST}; color: white; border: 1px solid {FOREST}; border-radius: 5px; padding: 7px 10px; font-weight: 600; }}'
        return f'QPushButton {{ background: {SURFACE}; color: {INK}; border: 1px solid {BORDER}; border-radius: 5px; padding: 6px 9px; }}'

    def _set_area_mode(self, mode: str | None):
        self._area_mode = mode
        state = aoi_selected_state(mode)
        self.current_view_button.setStyleSheet(self._area_button_style(state['current_view']))
        self.selected_polygon_button.setStyleSheet(self._area_button_style(state['selected_polygon']))
        self.capture_selected_polygon_button.setVisible(state['selected_polygon'])
        self.capture_selected_polygon_button.setEnabled(state['selected_polygon'] and self.selected_polygon_button.isEnabled())
        self.use_project_area_button.setStyleSheet(self._area_button_style(state['project_area']))
        self.use_project_area_button.setText('Valt' if state['project_area'] else 'Använd')

    def _step_heading(self, number: str, title: str, description: str) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 2)
        badge = QLabel(number)
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f'background: {FOREST_SOFT}; color: {FOREST}; border-radius: 13px; font-weight: bold;')
        text = QVBoxLayout()
        heading = QLabel(title)
        heading.setStyleSheet(f'font-size: 16px; font-weight: 600; color: {INK};')
        subheading = QLabel(description)
        subheading.setWordWrap(True)
        subheading.setStyleSheet(f'color: {MUTED}; font-size: 11px;')
        text.addWidget(heading)
        text.addWidget(subheading)
        layout.addWidget(badge, 0, Qt.AlignTop)
        layout.addLayout(text, 1)
        return layout

    def set_busy(self, message: str):
        self.status.setText(message)
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)

    def set_disconnected(self, message: str = 'Inte ansluten'):
        self.status.setText(message)
        self.organization.setText('Organisation: —')
        self.connect_button.setVisible(True)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setVisible(False)
        self.search.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.layers.setEnabled(False)
        self.current_view_button.setEnabled(False)
        self.selected_polygon_button.setEnabled(False)
        self.capture_selected_polygon_button.setEnabled(False)
        self.project_areas.setEnabled(False)
        self.use_project_area_button.setEnabled(False)
        self.add_to_qgis_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.choose_destination_button.setEnabled(False)
        self.reset_destination_button.setEnabled(False)
        self._layers = []
        self._selection = CatalogSelection()
        self._has_area = False
        self._set_area_mode(None)
        self.set_export_details_available(False)
        self.layers.clear()
        self.empty.setText('Anslut till GeoNod för att se lagerkatalogen.')
        self.empty.setVisible(True)
        self.set_project_areas([])
        self.area_status.setText('Välj Aktuell kartvy eller en markerad polygon.')
        self.set_delivery_state()

    def set_connected(self, organization_name: str, layers: list[CatalogLayer], project_areas: list[dict[str, Any]] | None = None):
        self.status.setText('Ansluten till GeoNod')
        self.organization.setText('Organisation: ' + (organization_name or '—'))
        self.connect_button.setVisible(False)
        self.disconnect_button.setVisible(True)
        self.disconnect_button.setEnabled(True)
        self.search.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.layers.setEnabled(True)
        self.current_view_button.setEnabled(True)
        self.selected_polygon_button.setEnabled(True)
        self.capture_selected_polygon_button.setEnabled(self._area_mode == 'selected_polygon')
        self.choose_destination_button.setEnabled(True)
        self.reset_destination_button.setEnabled(True)
        self._layers = layers
        self._selection.retain(layers)
        self.set_project_areas(project_areas or [])
        self._render_layers(self.search.text())
        self.set_delivery_state()

    def set_project_areas(self, project_areas: list[dict[str, Any]]):
        self._project_areas = [area for area in project_areas if isinstance(area, dict) and isinstance(area.get('aoi'), dict)]
        self.project_areas.clear()
        if not self._project_areas:
            self.project_areas.addItem('Inga projektområden tillgängliga', None)
            self.project_areas.setEnabled(False)
            self.use_project_area_button.setEnabled(False)
            return
        for area in self._project_areas:
            name = str(area.get('name') or 'Namnlöst projektområde')
            organization = str(area.get('organizationName') or '')
            self.project_areas.addItem(f'{name} · {organization}' if organization else name, area)
        self.project_areas.setEnabled(True)
        self.use_project_area_button.setEnabled(True)

    def set_error(self, message: str):
        self.status.setText(message)
        self.connect_button.setVisible(True)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(bool(self._layers))

    def set_area(self, label: str, mode: str):
        self._has_area = True
        self._set_area_mode(mode)
        self.area_status.setText(f'{label} används som område.')
        self.set_delivery_state()

    def select_area_mode(self, mode: str, message: str):
        """Select an AOI source before it has yielded a valid geometry."""
        self._has_area = False
        self._set_area_mode(mode)
        self.area_status.setText(message)
        self.set_delivery_state()

    def set_area_error(self, message: str):
        self.area_status.setText(message)

    def set_delivery_state(self):
        self.delivery_status.setText(delivery_status(len(self._selection.ids), self._has_area))
        ready = bool(self._selection.ids) and self._has_area
        self.add_to_qgis_button.setEnabled(ready)
        self.download_button.setEnabled(ready)

    def set_destination(self, description: str, custom: bool):
        self.destination.setText(description)
        self.reset_destination_button.setVisible(custom)

    def set_export_progress(self, percentage: int, stage: str | None = None):
        self.export_stage.setVisible(True)
        self.export_progress.setVisible(True)
        self.export_progress.setValue(max(0, min(100, percentage)))
        if stage is None:
            stage = 'Förbereder export …' if percentage < 5 else ('Skapar export …' if percentage < 15 else ('Bearbetar …' if percentage < 90 else 'Hämtar leverans …'))
        self.export_stage.setText(stage)

    def set_export_running(self, running: bool):
        self.add_to_qgis_button.setEnabled(not running and bool(self._selection.ids) and self._has_area)
        self.download_button.setEnabled(not running and bool(self._selection.ids) and self._has_area)
        self.choose_destination_button.setEnabled(not running)
        self.reset_destination_button.setEnabled(not running)

    def set_export_result(self, message: str, failed: bool = False):
        self.set_export_running(False)
        self.set_export_progress(100 if not failed else 0, 'Fel' if failed else 'Klar')
        self.delivery_status.setText(message)

    def set_export_details_available(self, available: bool):
        self.export_details_button.setVisible(available)

    def set_version(self, installed_version: str, status: str, update_available: bool = False):
        self.version_label.setText('Installerad pluginversion: ' + installed_version)
        self.version_status.setText(status)
        self.update_button.setVisible(update_available)

    def _on_search_changed(self, query: str):
        self.search_changed.emit(query)
        self._render_layers(query)

    def _request_project_area(self):
        area = self.project_areas.currentData()
        if isinstance(area, dict):
            self.project_area_requested.emit(area)

    def _render_layers(self, query: str):
        visible = filter_layers(self._layers, query)
        self.layers.clear()
        self._layer_widgets = {}
        self._group_buttons = []
        expanded_for_search = catalog_expanded_for_search(query)
        for category in catalog_hierarchy(visible):
            category_item = QTreeWidgetItem(self.layers)
            category_item.setExpanded(expanded_for_search)
            category_layers = [layer for subcategory in category.subcategories for layer in subcategory.layers]
            self.layers.setItemWidget(category_item, 0, self._group_row(category.name, category_layers, True))
            for subcategory in category.subcategories:
                subcategory_item = QTreeWidgetItem(category_item)
                subcategory_item.setExpanded(expanded_for_search)
                self.layers.setItemWidget(subcategory_item, 0, self._group_row(subcategory.name, list(subcategory.layers), False))
                for layer in subcategory.layers:
                    layer_item = QTreeWidgetItem(subcategory_item)
                    layer_item.setData(0, Qt.UserRole, layer.id)
                    self.layers.setItemWidget(layer_item, 0, self._layer_row(layer))
        self.empty.setText('Inga lager matchar sökningen.' if self._layers else 'GeoNods lagerkatalog är tom.')
        self.empty.setVisible(not visible)

    def _group_row(self, name: str, layers: list[CatalogLayer], category: bool) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(3, 4, 3, 4)
        label = QLabel(name)
        label.setWordWrap(True)
        label.setStyleSheet(f'color: {INK if category else MUTED}; font-weight: 600; font-size: {"13px" if category else "11px"};')
        button = QPushButton('Rensa val' if self._selection.group_is_all_selected(layers) else 'Välj alla')
        button.setStyleSheet(f'QPushButton {{ color: {FOREST}; border: 1px solid {FOREST}; border-radius: 4px; padding: 2px 5px; font-size: 10px; }}')
        button.clicked.connect(lambda _checked=False, values=layers: self._toggle_group(values))
        self._group_buttons.append((button, layers))
        layout.addWidget(label, 1)
        layout.addWidget(button, 0, Qt.AlignTop)
        return row

    def _layer_row(self, layer: CatalogLayer) -> QWidget:
        selected = self._selection.is_selected(layer.id)
        row = QFrame()
        row.setStyleSheet(self._layer_row_style(selected))
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 7, 8, 7)
        checkbox = QCheckBox()
        checkbox.setChecked(selected)
        checkbox.toggled.connect(lambda _checked, layer_id=layer.id: self._toggle_layer(layer_id))
        self._layer_widgets[layer.id] = (row, checkbox)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(layer.name)
        name.setWordWrap(True)
        name.setStyleSheet(f'font-weight: 600; color: {INK};')
        source = QLabel(layer.source)
        source.setWordWrap(True)
        source.setStyleSheet(f'color: {MUTED}; font-size: 10px;')
        text.addWidget(name)
        text.addWidget(source)
        if layer.description:
            description = QLabel(layer.description)
            description.setWordWrap(True)
            description.setStyleSheet(f'color: {MUTED}; font-size: 10px;')
            text.addWidget(description)
        layout.addWidget(checkbox, 0, Qt.AlignTop)
        layout.addLayout(text, 1)
        return row

    def _layer_row_style(self, selected: bool) -> str:
        return f'QFrame {{ background: {FOREST_SOFT if selected else SURFACE}; border: 1px solid {FOREST if selected else BORDER}; border-radius: 6px; }}'

    def _update_selection_widgets(self):
        for layer_id, (row, checkbox) in self._layer_widgets.items():
            selected = self._selection.is_selected(layer_id)
            row.setStyleSheet(self._layer_row_style(selected))
            checkbox.blockSignals(True)
            checkbox.setChecked(selected)
            checkbox.blockSignals(False)
        for button, layers in self._group_buttons:
            button.setText('Rensa val' if self._selection.group_is_all_selected(layers) else 'Välj alla')

    def _toggle_layer(self, layer_id: str):
        self._selection.toggle(layer_id)
        self._emit_selection()
        self._update_selection_widgets()

    def _toggle_group(self, layers: Iterable[CatalogLayer]):
        values = list(layers)
        self._selection.set_group(values, not self._selection.group_is_all_selected(values))
        self._emit_selection()
        self._update_selection_widgets()

    def _emit_selection(self):
        self.selection_changed.emit(sorted(self._selection.ids))
        self.set_delivery_state()
