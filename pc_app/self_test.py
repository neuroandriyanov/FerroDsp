"""Offline verification of the actual frozen runtime, including a full recording."""
import bootstrap
import io
import json
import platform
import traceback
import unittest
from pathlib import Path

def run(destination, application):
    report = dict(build=bootstrap.build_info(), frozen=bootstrap.FROZEN,
                  platform=platform.platform(), checks={}, ok=False)
    try:
        import cv2
        import h5py
        import numpy as np
        import pyrealsense2 as rs
        import sounddevice as sd
        import pyqtgraph as pg
        from PySide6 import QtCore
        from demo_video import font
        import test_core
        import test_synchronization
        import test_distance_filter
        plot=pg.PlotWidget()
        plot.plot(np.arange(20), np.sin(np.arange(20)))
        plot.resize(320,200)
        plot.show()
        application.processEvents()
        assert not plot.grab().isNull(), 'Qt rendering failed'
        plot.close()
        assert font(18).getmask('Катушка — 200 мм').getbbox(), 'Unicode font failed'
        report['checks']['versions']=dict(Qt=QtCore.qVersion(), numpy=np.__version__,
                                         OpenCV=cv2.__version__, h5py=h5py.__version__)
        if bootstrap.FROZEN:
            origins={m.__name__:Path(m.__file__).resolve().is_relative_to(bootstrap.APP)
                     for m in (cv2,h5py,np,rs,sd,pg,QtCore)}
            report['checks']['loaded_from_bundle']=origins
            assert all(origins.values()), 'External library loaded'
        # Discovery only; no camera stream or audio capture is opened.
        report['checks']['camera_count']=len(rs.context().query_devices())
        report['checks']['audio_device_count']=len(sd.query_devices())
        assert report['build']['source_sha256'], 'Missing source identity'
        json.loads((bootstrap.APP/'resources/transport-protocol.json').read_text(encoding='utf-8'))
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                                 for module in (test_core,test_synchronization,test_distance_filter))
        output=io.StringIO()
        result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
        report['checks']['tests_run']=result.testsRun
        report['checks']['test_output']=output.getvalue()
        report['ok']=result.wasSuccessful()
    except Exception:
        report['error']=traceback.format_exc()
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['ok'] else 1
