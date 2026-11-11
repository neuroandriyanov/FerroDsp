# Third-party components

FerroDSP Lab application source is MIT licensed; see `LICENSE` and `Source/pc_app`.
The included libraries retain their own licenses and copyright notices in `Licenses/`.
Exact installed versions, upstream project URLs and build provenance are recorded in
`Licenses/components.json` and `build-info.json`. This package does not change their license.

* CPython: Python Software Foundation license, https://www.python.org/downloads/source/
* Qt, PySide6 and Shiboken 6.12.0: LGPLv3 option. These are dynamically loaded,
  unmodified libraries in `_internal/PySide6` and `_internal/shiboken6`; they can be
  replaced with compatible modified versions. Reverse engineering for debugging
  modifications to these libraries is permitted. Full application source and the
  build recipe are included to permit rebuilding/relinking.
  Sources: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/
  and https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/ .
  See https://doc.qt.io/qtforpython-6/licenses.html and https://doc.qt.io/qt-6/licenses-used-in-qt.html .
* FFmpeg is a **separate executable** invoked through pipes, delivered by
  imageio-ffmpeg. The included Gyan 9.0.2 essentials build enables GPL and version3;
  FFmpeg/libx264 are **GPLv3**, not covered by the Python wrapper's BSD license.
  Exact configuration and license information: `Licenses/FFmpeg-build.txt` and
  `Licenses/FFmpeg-license.txt`; full GPL text: `Licenses/additional/GPL-3.0.txt`.
  Upstream distribution/source entry: https://www.gyan.dev/ffmpeg/builds/ .
  FFmpeg source revision: https://github.com/FFmpeg/FFmpeg/tree/946fcce07b .
  x264 source: https://code.videolan.org/videolan/x264 .
  The executable lives in `_internal/imageio_ffmpeg/binaries/` and may be replaced
  with a compatible FFmpeg supporting libx264. `IMAGEIO_FFMPEG_EXE` may also select one.
* RealSense SDK: Apache-2.0, https://github.com/realsenseai/librealsense/tree/v2.59.1 .
* NumPy, h5py/HDF5, Pillow, OpenCV, pyqtgraph, sounddevice/PortAudio, cffi and
  their bundled native libraries: notices from their distributions are included.
  OpenCV's bundled decoder has its own third-party notice; see its LICENSE-3RD-PARTY.txt.
* PyInstaller bootloader: GPL with the bootloader distribution exception, included
  in `Licenses/PyInstaller`. It does not change the application's MIT license.
* Segoe UI is read from the user's Windows installation; it is not redistributed.

Keep this file and `Licenses/` with binary redistributions. Retain access to matching
third-party sources/build information when publishing a release, including the
FFmpeg build and its enabled libraries. Do not describe the entire binary bundle as MIT-only.
