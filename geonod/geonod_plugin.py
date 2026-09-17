"""QGIS entry point and task-based UI orchestration."""
from __future__ import annotations

import platform
from pathlib import Path
from uuid import uuid4

from qgis.PyQt.QtCore import Qt, QStandardPaths, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog
from qgis.core import QgsApplication, QgsProject, QgsTask
from qgis.gui import QgsDockWidget

from .api_client import DEFAULT_BASE_URL, GeoNodApiClient
from .auth import wait_for_pairing
from .aoi import AoiCaptureError, capture_current_view, capture_selected_polygon, validate_polygon
from .aoi_overlay import clear_project_area_overlay, show_project_area_overlay
from .catalog import parse_catalog
from .credential_store import QgisCredentialStore
from .delivery import add_sources_to_qgis, delivery_group_name, discover_delivery_sources, extract_delivery_archive
from .dock_widget import GeoNodDockWidget
from .export_pipeline import export_payload, new_export_directory, wait_for_export


class GeoNodPlugin:
    VERSION = '1.0.0'
    HELP_URL = 'https://geonod.se/integrationer'
    EXPORT_DETAILS_URL = 'https://geonod.se/exporter'

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.panel = None
        self.credentials = QgisCredentialStore()
        self.client = GeoNodApiClient(DEFAULT_BASE_URL)
        self._selected_area = None
        self._selected_aoi_mode = None
        self._project_area_overlay = None
        self._last_export_order_id = None
        self._organization_id = None
        self._catalog_by_id = {}
        self._selected_layer_ids = set()
        self._custom_export_root = None
        # QgsTaskManager owns the C++ task, but not necessarily the Python
        # wrapper which retains fromFunction's Python callbacks. Keep each
        # wrapper alive until its main-thread completion callback runs.
        self._active_tasks = {}

    def initGui(self):
        self.action = QAction('GeoNod', self.iface.mainWindow())
        self.action.setIcon(QIcon(str(Path(__file__).resolve().parent / 'assets' / 'geonod-symbol.svg')))
        self.action.triggered.connect(self.show_panel)
        self.iface.addPluginToMenu('&GeoNod', self.action)
        self.iface.addToolBarIcon(self.action)
        self.dock = QgsDockWidget('GeoNod', self.iface.mainWindow())
        self.dock.setObjectName('GeoNodDockWidget')
        self.panel = GeoNodDockWidget(self.dock)
        self.dock.setWidget(self.panel)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()
        self.panel.connect_requested.connect(self.start_connection)
        self.panel.disconnect_requested.connect(self.disconnect)
        self.panel.refresh_requested.connect(self.refresh_connected_state)
        self.panel.current_view_requested.connect(self.use_current_view)
        self.panel.selected_polygon_requested.connect(self.use_selected_polygon)
        self.panel.capture_selected_polygon_requested.connect(self.capture_selected_polygon)
        self.panel.project_area_requested.connect(self.use_project_area)
        self.panel.selection_changed.connect(self._set_selected_layers)
        self.panel.add_to_qgis_requested.connect(lambda: self._start_export('add'))
        self.panel.download_requested.connect(lambda: self._start_export('download'))
        self.panel.choose_destination_requested.connect(self.choose_export_directory)
        self.panel.reset_destination_requested.connect(self.reset_export_directory)
        self.panel.help_requested.connect(self.open_help)
        self.panel.open_export_details_requested.connect(self.open_export_details)
        self.panel.set_version(
            self.VERSION,
            'Versionskontroll är inte tillgänglig för QGIS ännu.',
            update_available=False,
        )
        self._refresh_destination_description()
        credential = self.credentials.read()
        if credential:
            self.load_connected_state(credential)

    def unload(self):
        self._clear_project_area_overlay()
        if self.action:
            self.iface.removePluginMenu('&GeoNod', self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()

    def show_panel(self):
        self.dock.show()
        self.dock.raise_()

    def _run(self, description, work, completed, failed=None, progress=None):
        def done(exception, result=None):
            self._active_tasks.pop(id(task), None)
            if exception is not None:
                if failed is not None:
                    failed(exception)
                else:
                    self._set_task_error(exception)
                return
            try:
                completed(result)
            except Exception as error:
                self._set_task_error(error)

        task = QgsTask.fromFunction(description, work, on_finished=done)
        if progress is not None and hasattr(task, 'progressChanged'):
            task.progressChanged.connect(progress)
        # Retain before adding: a very fast task may finish during addTask().
        self._active_tasks[id(task)] = task
        try:
            QgsApplication.taskManager().addTask(task)
        except Exception as error:
            self._active_tasks.pop(id(task), None)
            if failed is not None:
                failed(error)
            else:
                self._set_task_error(error)
            return None
        return task

    def _set_task_error(self, error):
        message = str(error).strip()
        self.panel.set_error(message or 'GeoNod-åtgärden kunde inte slutföras. Försök igen.')

    def start_connection(self):
        self.panel.set_busy('Startar anslutning …')
        device_name = '{} · QGIS'.format(platform.node() or 'Den här datorn')
        self._run('Starta GeoNod-anslutning', lambda _task: self.client.start_pairing(device_name, self.VERSION), self._open_pairing)

    def _open_pairing(self, pairing):
        QDesktopServices.openUrl(QUrl(pairing.approval_url))
        self.panel.set_busy('Väntar på godkännande i webbläsaren …')
        self._run('Slutför GeoNod-anslutning', lambda _task: wait_for_pairing(self.client, pairing), self._connected_credential)

    def _connected_credential(self, credential):
        self.credentials.save(credential)
        self.load_connected_state(credential)

    def load_connected_state(self, credential):
        self.panel.set_busy('Hämtar GeoNod-katalogen …')
        def work(_task):
            session = self.client.session(credential)
            catalog = self.client.catalog(credential)
            organizations = session.get('organizations', [])
            organization = organizations[0] if organizations and isinstance(organizations[0], dict) else {}
            return str(organization.get('id') or ''), str(organization.get('name') or ''), parse_catalog(catalog)

        def connected(result):
            organization_id, organization_name, layers = result
            if not organization_id:
                raise RuntimeError('GeoNod returnerade ingen aktiv organisation.')
            self._organization_id = organization_id
            self._catalog_by_id = {layer.id: layer for layer in layers}
            self._selected_layer_ids.intersection_update(self._catalog_by_id)
            self.panel.set_connected(organization_name, layers)
            self._load_project_areas(credential)

        self._run('Hämta GeoNod-katalog', work, connected)

    def _load_project_areas(self, credential):
        """Optional enrichment: an unavailable route must never disconnect QGIS."""
        def work(_task):
            response = self.client.project_areas(credential)
            areas = response.get('projects', []) if isinstance(response, dict) else []
            return areas if isinstance(areas, list) else []

        self._run(
            'Hämta GeoNod-projektområden',
            work,
            self.panel.set_project_areas,
            lambda _error: self.panel.set_project_areas([]),
        )

    def refresh_connected_state(self):
        credential = self.credentials.read()
        if not credential:
            self.panel.set_disconnected()
            return
        self.load_connected_state(credential)

    def use_current_view(self):
        self._clear_project_area_overlay()
        self._selected_area = None
        self._selected_aoi_mode = 'current_view'
        self.panel.select_area_mode('current_view', 'Läser aktuell kartvy …')
        try:
            self._selected_area = capture_current_view(self.iface)
            self.panel.set_area('Aktuell kartvy', 'current_view')
        except AoiCaptureError as error:
            self.panel.set_area_error(str(error))
        except Exception:
            self.panel.set_area_error('Aktuell kartvy kunde inte läsas. Kontrollera kartans CRS och försök igen.')

    def use_selected_polygon(self):
        self._clear_project_area_overlay()
        self._selected_aoi_mode = 'selected_polygon'
        self._selected_area = None
        self.panel.select_area_mode(
            'selected_polygon',
            'Markera exakt ett polygonobjekt i det aktiva polygonlagret och klicka på Använd markerad polygon.',
        )

    def capture_selected_polygon(self):
        if self._selected_aoi_mode != 'selected_polygon':
            self.use_selected_polygon()
            return
        # Never fall back to an earlier extent or earlier feature when the
        # current selection is invalid. The selected mode remains active.
        self._selected_area = None
        self.panel.select_area_mode('selected_polygon', 'Läser markerad polygon …')
        try:
            geometry, layer_name, feature_id = capture_selected_polygon(self.iface)
            self._selected_area = geometry
            self.panel.set_area(f'1 polygon vald: {layer_name} · objekt {feature_id}', 'selected_polygon')
        except AoiCaptureError as error:
            self.panel.set_area_error(str(error))
        except Exception:
            self.panel.set_area_error('Den valda polygonen kunde inte läsas eller omprojiceras till WGS84.')

    def use_project_area(self, project_area):
        try:
            if not isinstance(project_area, dict):
                raise AoiCaptureError('Välj ett projektområde först.')
            self._selected_area = validate_polygon(project_area.get('aoi'))
            self._selected_aoi_mode = 'project_area'
            self.panel.set_area('Projektområde: ' + str(project_area.get('name') or 'Namnlöst projektområde'), 'project_area')
            try:
                self._show_project_area_overlay(self._selected_area)
            except Exception:
                # The overlay is only guidance; its failure must not alter the
                # validated WGS84 geometry that the export contract uses.
                self.panel.set_area_error('Projektområdet används, men kunde inte visas i kartans CRS.')
        except AoiCaptureError as error:
            self.panel.set_area_error(str(error))

    def _clear_project_area_overlay(self):
        clear_project_area_overlay(self._project_area_overlay)
        self._project_area_overlay = None

    def _show_project_area_overlay(self, polygon):
        self._clear_project_area_overlay()
        self._project_area_overlay = show_project_area_overlay(self.iface.mapCanvas(), polygon)

    def open_help(self):
        QDesktopServices.openUrl(QUrl(self.HELP_URL))

    def open_export_details(self):
        if self._last_export_order_id:
            QDesktopServices.openUrl(QUrl(self.EXPORT_DETAILS_URL))

    def _set_selected_layers(self, layer_ids):
        self._selected_layer_ids = {layer_id for layer_id in layer_ids if layer_id in self._catalog_by_id}

    def _default_export_root(self):
        project_file = QgsProject.instance().fileName()
        if project_file:
            return Path(project_file).resolve().parent / 'GeoNod'
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        return Path(documents or Path.cwd()) / 'GeoNod'

    def _export_root(self):
        return Path(self._custom_export_root) if self._custom_export_root else self._default_export_root()

    def _refresh_destination_description(self):
        root = self._export_root()
        description = str(root) if self._custom_export_root else 'Projektets GeoNod-mapp (standard): ' + str(root)
        self.panel.set_destination(description, bool(self._custom_export_root))

    def choose_export_directory(self):
        chosen = QFileDialog.getExistingDirectory(self.iface.mainWindow(), 'Välj mapp för GeoNod-exporter', str(self._export_root()))
        if chosen:
            self._custom_export_root = chosen
            self._refresh_destination_description()

    def reset_export_directory(self):
        self._custom_export_root = None
        self._refresh_destination_description()

    def _start_export(self, mode):
        selected = [self._catalog_by_id[layer_id] for layer_id in self._selected_layer_ids if layer_id in self._catalog_by_id]
        credential = self.credentials.read()
        if not credential or not self._organization_id or not self._selected_area:
            self.panel.set_export_result('Välj underlag och område och kontrollera GeoNod-anslutningen innan export.', True)
            return
        try:
            payload = export_payload(selected, self._selected_area)
        except ValueError as error:
            self.panel.set_export_result(str(error), True)
            return
        destination_root = self._export_root()
        self.panel.set_export_running(True)
        self._set_export_details_available(False)
        self.panel.set_export_progress(1, 'Förbereder export …')

        def set_progress(task, value):
            if hasattr(task, 'setProgress'):
                task.setProgress(value)

        def create_work(task):
            set_progress(task, 3)
            destination = new_export_directory(destination_root)
            set_progress(task, 8)
            order = self.client.create_export_order(credential, self._organization_id, payload, 'qgis-local-' + uuid4().hex)
            set_progress(task, 15)
            return {'destination': destination, 'order': order}

        def delivery_completed(result):
            archive = result['archive']
            if mode == 'download':
                self.panel.set_export_result('Leveransen är klar: ' + str(archive))
                return
            self.panel.set_export_progress(96, 'Lägger till i QGIS …')
            try:
                added_result = add_sources_to_qgis(result['sources'], delivery_group_name(archive), self.iface.mapCanvas())
            except Exception as error:
                self.panel.set_export_result('Leveransen hämtades men kunde inte läggas till i QGIS: ' + str(error), True)
                return
            if not added_result.added:
                details = ' ' + ' '.join(added_result.failures) if added_result.failures else ''
                self.panel.set_export_result('Leveransen hämtades, men inga stödda lager kunde läsas i QGIS.' + details, True)
                return
            suffix = (' Följande lager kunde inte läsas: ' + ', '.join(added_result.failures) + '.') if added_result.failures else ''
            style_suffix = (' Styles: ' + ', '.join(added_result.style_warnings) + '.') if added_result.style_warnings else ''
            self.panel.set_export_result(f'Klar – {added_result.added} lager lades till i QGIS.{suffix}{style_suffix}')

        def failed(error):
            self.panel.set_export_result('GeoNod-exporten kunde inte slutföras: ' + (str(error).strip() or 'okänt fel'), True)

        def export_created(result):
            order = result['order']
            self._last_export_order_id = str(order.get('id') or '') or None
            self._set_export_details_available(bool(self._last_export_order_id))
            self.panel.set_export_progress(15, 'Bearbetar export …')

            def delivery_work(task):
                set_progress(task, 15)
                completed_order = wait_for_export(
                    self.client, credential, self._organization_id, order,
                    lambda value: set_progress(task, value),
                    is_cancelled=lambda: bool(getattr(task, 'isCanceled', lambda: False)()),
                )
                set_progress(task, 90)
                filename = Path(str(completed_order.get('downloadFilename') or 'geonod-export.zip')).name or 'geonod-export.zip'
                archive = self.client.download_export_order(
                    credential, self._organization_id, str(completed_order['id']), result['destination'] / filename,
                )
                if mode == 'download':
                    set_progress(task, 100)
                    return {'archive': archive, 'destination': result['destination'], 'sources': []}
                extracted = extract_delivery_archive(archive, result['destination'] / 'uppackad')
                sources = discover_delivery_sources(extracted)
                set_progress(task, 94)
                return {'archive': archive, 'destination': result['destination'], 'sources': sources}

            self._run(
                'Hämta GeoNod-leverans', delivery_work, delivery_completed, failed,
                lambda value: self.panel.set_export_progress(int(value)),
            )

        self._run(
            'Skapa GeoNod-export', create_work, export_created, failed,
            lambda value: self.panel.set_export_progress(int(value)),
        )

    def _set_export_details_available(self, available):
        if hasattr(self.panel, 'set_export_details_available'):
            self.panel.set_export_details_available(available)

    def disconnect(self):
        credential = self.credentials.read()
        if not credential:
            self.credentials.delete()
            self._clear_project_area_overlay()
            self._selected_area = None
            self._selected_aoi_mode = None
            self._organization_id = None
            self._last_export_order_id = None
            self._set_export_details_available(False)
            self.panel.set_disconnected()
            return
        # The account may remain connected if revocation fails, but the
        # project-area visual aid must never outlive an explicit disconnect.
        self._clear_project_area_overlay()
        self.panel.set_busy('Kopplar från GeoNod …')
        def completed(_):
            self.credentials.delete()
            self._clear_project_area_overlay()
            self._selected_area = None
            self._selected_aoi_mode = None
            self._organization_id = None
            self._last_export_order_id = None
            self._set_export_details_available(False)
            self.panel.set_disconnected('Frånkopplad')
        self._run('Koppla från GeoNod', lambda _task: self.client.revoke(credential), completed)
