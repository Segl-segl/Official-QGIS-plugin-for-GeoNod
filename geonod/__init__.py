"""GeoNod QGIS plugin entry package."""


def classFactory(iface):
    from .geonod_plugin import GeoNodPlugin
    return GeoNodPlugin(iface)
