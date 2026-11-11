"""Build a clean, relocatable Windows ZIP. Run inside the build venv."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

APP=Path(__file__).resolve().parent
ROOT=APP.parent

def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def copy_public_source(destination):
    # Explicit allowlist: never walk local settings, tokens, recordings or experiments.
    destination.mkdir(parents=True)
    extensions={'.py','.md','.txt','.json','.spec','.ps1','.cmd'}
    for path in APP.iterdir():
        if path.is_file() and (path.suffix in extensions or path.name in {'VERSION','.gitignore'}):
            shutil.copy2(path,destination/path.name)
    for name in ['resources','licenses']:
        shutil.copytree(APP/name,destination/name)

def collect_licenses(destination):
    destination.mkdir()
    components=[]
    names=['numpy','PySide6','PySide6_Essentials','PySide6_Addons','shiboken6',
           'pyqtgraph','opencv-python-headless','pyrealsense2','sounddevice','cffi',
           'pycparser','h5py','Pillow','imageio-ffmpeg','colorama','packaging','PyInstaller']
    for name in names:
        dist=metadata.distribution(name)
        components.append(dict(name=name,version=dist.version,
            license=dist.metadata.get('License-Expression') or dist.metadata.get('License','See notices'),
            project_urls=dist.metadata.get_all('Project-URL',[]),
            homepage=dist.metadata.get('Home-page')))
        for path in dist.files or []:
            if any(part in path.name.lower() for part in ('license','copying','notice')) and path.suffix not in {'.py','.pyc','.pyd'}:
                src=Path(dist.locate_file(path))
                if not src.is_file():continue
                # Preserve names/structure to avoid silently losing third-party notices.
                target=destination/name/Path(*[p for p in path.parts if p not in {'.','..'}])
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,target)
    shutil.copytree(APP/'licenses',destination/'additional')
    shutil.copy2(Path(sys.base_prefix)/'LICENSE.txt',destination/'Python-LICENSE.txt')
    write_json(destination/'components.json',components)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=APP/'dist')
    args=parser.parse_args()
    if sys.platform!='win32' or platform.machine().lower() not in {'amd64','x86_64'}:
        raise SystemExit('Build on Windows x64.')
    if sys.version_info[:2]!=(3,12) or sys.prefix==sys.base_prefix:
        raise SystemExit('Use a clean Python 3.12 x64 venv with requirements-build.txt.')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    work=APP/'build';work.mkdir(exist_ok=True)
    version=(APP/'VERSION').read_text().strip()
    archive_name=f'FerroDSP-Lab-{version}-windows-x64'
    # Unique staging avoids removing an existing release or its UserData directory.
    stage=Path(tempfile.mkdtemp(prefix='portable-',dir=work))
    info=dict(version=version,built_utc=datetime.now(timezone.utc).isoformat(),
              python=platform.python_version(),platform='windows-x64',
              dependencies={d.metadata['Name']:d.version for d in metadata.distributions()},
              source_sha256={p.name:digest(p) for p in APP.glob('*.py')},
              resources_sha256={p.name:digest(p) for p in (APP/'resources').glob('*.json')})
    try:
        info['git_base']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
        info['git_dirty']=bool(subprocess.check_output(['git','status','--porcelain','--','pc_app'],cwd=ROOT,text=True))
    except (OSError,subprocess.CalledProcessError):info['git_base']=None
    write_json(stage/'build-info.json',info)
    env=os.environ.copy();env['FERRODSP_BUILD_RESOURCES']=str(stage)
    env.pop('PYTHONPATH',None);env.pop('IMAGEIO_FFMPEG_EXE',None)
    env.pop('PYTHONHOME',None)
    # Do this during ANALYSIS too: unrelated programs can put incompatible ICU,
    # OpenSSL or UCRT DLLs on PATH and silently contaminate the release.
    env['PATH']=os.pathsep.join([str(Path(sys.executable).parent),sys.base_prefix,
                                str(Path(os.environ['WINDIR'])/'System32'),os.environ['WINDIR']])
    subprocess.run([sys.executable,'-m','unittest','discover','-s',str(APP),'-p','test_*.py','-v'],env=env,check=True)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',
        '--distpath',str(stage/'dist'),'--workpath',str(stage/'pyinstaller'),str(APP/'FerroDSP-Lab.spec')],env=env,check=True)
    bundle=stage/'dist/FerroDSP-Lab'
    for name in ['QUICKSTART.md','THIRD_PARTY.md','RELEASE_NOTES.md']:
        shutil.copy2(APP/name,bundle/name)
    shutil.copy2(ROOT/'LICENSE',bundle/'LICENSE')
    shutil.copy2(stage/'build-info.json',bundle/'build-info.json')
    collect_licenses(bundle/'Licenses')
    copy_public_source(bundle/'Source/pc_app')
    shutil.copy2(ROOT/'LICENSE',bundle/'Source/LICENSE')
    import imageio_ffmpeg
    ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe())
    (bundle/'Licenses/FFmpeg-build.txt').write_bytes(subprocess.check_output([str(ffmpeg),'-version'],stderr=subprocess.STDOUT))
    (bundle/'Licenses/FFmpeg-license.txt').write_bytes(subprocess.check_output([str(ffmpeg),'-L'],stderr=subprocess.STDOUT))
    # Run the actual EXE with a clean PATH, separate data and no installed Python path.
    verify_env=env.copy()
    verify_env['PATH']=os.pathsep.join([str(Path(os.environ['WINDIR'])/'System32'),os.environ['WINDIR']])
    verify_env['FERRODSP_DATA_DIR']=str(stage/'test-data')
    verify_env.pop('PYTHONHOME',None)
    report=stage/'self-test.json'
    subprocess.run([str(bundle/'FerroDSP-Lab.exe'),'--self-test',str(report)],cwd=stage,env=verify_env,check=True,timeout=180)
    if not json.loads(report.read_text(encoding='utf-8'))['ok']:raise RuntimeError('Frozen verification failed')
    shutil.copy2(report,output/(archive_name+'-self-test.json'))
    if (bundle/'UserData').exists():raise RuntimeError('Private data unexpectedly present in release')
    for path in bundle.rglob('*'):
        if any(p in {'local','recordings','UserData','.venv','__pycache__'} for p in path.relative_to(bundle).parts):
            raise RuntimeError(f'Unexpected private/cache path: {path}')
    # Hash all distributed files before archiving. Source and notices travel with the EXE.
    manifest={p.relative_to(bundle).as_posix():digest(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
    write_json(bundle/'files-sha256.json',manifest)
    archive=output/(archive_name+'.zip')
    if archive.exists():raise FileExistsError(f'Refusing to overwrite release: {archive}')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():z.write(path,Path(archive_name)/path.relative_to(bundle))
    (output/(archive.name+'.sha256')).write_text(f'{digest(archive)}  {archive.name}\n',encoding='ascii')
    print(json.dumps(dict(archive=str(archive),bytes=archive.stat().st_size,staging=str(bundle)),ensure_ascii=False))

if __name__=='__main__':main()
