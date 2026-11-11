"""Resource paths and writable data for source and portable installations."""
import os
import sys
import hashlib
import json
from pathlib import Path

FROZEN = bool(getattr(sys, 'frozen', False))
APP = Path(__file__).resolve().parent
ROOT = APP.parent
LIBS = ROOT / 'tmp' / 'research-libs'
if not FROZEN and sys.prefix == sys.base_prefix and LIBS.is_dir():
    sys.path.insert(0, str(LIBS))
# Resources are read-only. A portable installation never writes into _internal.
DATA = Path(os.environ['FERRODSP_DATA_DIR']).expanduser().resolve() if os.environ.get('FERRODSP_DATA_DIR') else (
    Path(sys.executable).resolve().parent / 'UserData' if FROZEN else APP)
LOCAL = DATA / 'local'
RECORDINGS = DATA / 'recordings'

def build_info():
    path = APP / 'resources' / 'build-info.json'
    if FROZEN:
        return json.loads(path.read_text(encoding='utf-8'))
    return dict(version=(APP/'VERSION').read_text(encoding='utf-8').strip(),
                source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in APP.glob('*.py')})

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')

