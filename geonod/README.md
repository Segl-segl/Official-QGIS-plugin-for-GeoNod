# GeoNod for QGIS

GeoNod for QGIS connects QGIS to the GeoNod catalog using secure device pairing. A GeoNod account is required. After connecting, you can browse the catalog, select one or more layers, choose an area of interest (AOI), and request an export without leaving QGIS.

The plugin supports these current workflows:

- **Catalog:** Browse GeoNod layers by category and subcategory, search, inspect provider and description, and select multiple layers.
- **Area of interest:** Use the current map view, capture exactly one selected polygon, or select one of your GeoNod project areas. All locally captured geometry is transformed to WGS84 before it is sent with the export request. Selecting a project area also displays it as a temporary QGIS overlay.
- **Local export:** GeoNod creates an export for the selected layers and AOI. The plugin can download the delivery into the project's `GeoNod` folder or into a folder you choose.
- **Download and add to QGIS:** You can either download the delivery locally or download it and add its supported datasets to the current QGIS project in a GeoNod layer group.
- **Vector and raster:** Vector deliveries prefer GeoPackage and raster deliveries use GeoTIFF. The plugin loads supported delivered vector and raster datasets, including manifest-defined GeoPackage sublayers.
- **Persistent CRS fallback:** If a delivered vector layer uses a CRS that differs from the current canvas, the plugin creates a persistent `qgis_visning.gpkg` alongside the delivery for a robust display copy. The original delivery remains unchanged.

## Install from QGIS Plugin Manager

The primary installation path is QGIS Plugin Manager:

1. In QGIS, open **Plugins → Manage and Install Plugins…**.
2. Search for **GeoNod** in **All**.
3. Select it, choose **Install Plugin**, and make sure it is enabled.
4. Open the GeoNod panel from the **GeoNod** menu or the GeoNod toolbar button.

## First connection

1. Open the GeoNod panel and select **Connect**.
2. QGIS opens your browser to a GeoNod approval page.
3. Sign in to your GeoNod account if needed, review the device pairing request, and approve it.
4. Return to QGIS and wait for the panel to show your organization and catalog. The device credential is stored through QGIS Authentication Manager; if its authentication database is unavailable, the credential is kept only for the current QGIS session.
5. Choose catalog layers and an AOI, then select **Download** or **Download and add to QGIS**.

## Manual ZIP installation (development fallback)

Use ZIP installation only for development or when Plugin Manager is unavailable. From the repository root, run:

```powershell
python scripts/package_plugin.py
```

This creates `dist/geonod-qgis-plugin.zip`. In QGIS, open **Plugins → Manage and Install Plugins… → Install from ZIP**, select that file, then enable **GeoNod**.

## QGIS styles

An optional QGIS-native `.qml` style can be placed in `geonod/assets/styles/<layer_id>.qml`, for example `naturvardsverket-naturreservat.qml`. The plugin applies it when the matching `layer_id` appears in `DeliveryManifest.json`. If no style exists, QGIS uses its default renderer.

## License

GeoNod for QGIS is distributed under GPL-2.0-or-later. See `LICENSE`.
