# Build with build_portable.py; resources and notices are staged there.
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

app = Path(SPECPATH)
staged = Path(os.environ['FERRODSP_BUILD_RESOURCES'])
datas = [(str(app/'resources'), 'resources'), (str(staged/'build-info.json'), 'resources')]
datas += collect_data_files('imageio_ffmpeg')
binaries = collect_dynamic_libs('pyrealsense2')
hiddenimports = collect_submodules('pyrealsense2')
a = Analysis([str(app/'portable_entry.py')], pathex=[str(app)], binaries=binaries,
    datas=datas, hiddenimports=hiddenimports,
    excludes=['matplotlib','scipy','IPython','tkinter','pytest','PyQt5','PyQt6','PySide2',
              'PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick',
              'PySide6.QtQml','PySide6.QtQuick','PySide6.QtPdf','PySide6.QtPdfWidgets',
              'pyqtgraph.opengl','pyqtgraph.examples','PySide6.scripts'], noarchive=False)
# QtGui's generic hook also collects PDF and virtual-keyboard plugins, which
# pull in QML/Quick despite this being a pure Widgets application. Omit them.
unused_qt={'qpdf.dll','qtvirtualkeyboardplugin.dll','qt6pdf.dll','qt6virtualkeyboard.dll',
           'qt6qml.dll','qt6qmlmeta.dll','qt6qmlmodels.dll','qt6qmlworkerscript.dll','qt6quick.dll'}
a.binaries=[item for item in a.binaries if Path(item[0]).name.lower() not in unused_qt]
allowed_roots=[Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve(),Path(os.environ['WINDIR']).resolve()]
for destination,source,kind in a.binaries:
    if not any(Path(source).resolve().is_relative_to(root) for root in allowed_roots):
        raise RuntimeError(f'Unexpected external binary in release: {source}')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FerroDSP-Lab',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    version=str(app/'version_info.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FerroDSP-Lab')
