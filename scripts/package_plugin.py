"""Validate the QGIS plugin layout and make an installable ZIP without QGIS."""
from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'geonod'
OUTPUT = ROOT / 'dist' / 'geonod-qgis-plugin.zip'
REQUIRED = ('metadata.txt', 'LICENSE', '__init__.py', 'geonod_plugin.py', 'dock_widget.py', 'api_client.py', 'auth.py', 'catalog.py', 'aoi.py', 'aoi_overlay.py', 'workflow.py', 'export_pipeline.py', 'delivery.py', 'styles.py', 'credential_store.py', 'assets/geonod-symbol.svg')
EXCLUDED_PARTS = {'__pycache__', 'tests', '.git'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo', '.pem', '.key', '.p12', '.pfx'}


def _is_package_file(path: Path) -> bool:
    """Keep development files, bytecode, and credential material out of the release ZIP."""
    name = path.name.lower()
    return (
        path.is_file()
        and not path.is_symlink()
        and not any(part in EXCLUDED_PARTS for part in path.parts)
        and not name.startswith('.git')
        and not name.startswith('.env')
        and path.suffix.lower() not in EXCLUDED_SUFFIXES
    )


def main() -> int:
    missing = [name for name in REQUIRED if not (PLUGIN / name).is_file()]
    if missing:
        raise SystemExit('Pluginstrukturen saknar: ' + ', '.join(missing))
    OUTPUT.parent.mkdir(exist_ok=True)
    with ZipFile(OUTPUT, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(PLUGIN.rglob('*')):
            if _is_package_file(path):
                archive.write(path, path.relative_to(ROOT).as_posix())
    print(OUTPUT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
