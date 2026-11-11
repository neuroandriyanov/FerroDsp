"""Re-export an existing v2 session without changing its data or manifest."""
import bootstrap
import argparse
import hashlib
import json
from pathlib import Path
from demo_video import render_demo
from recording import dump,now_iso

def export(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Каталог результата уже существует; выберите новый каталог')
    meta=json.loads((source/'session.json').read_text(encoding='utf-8'))
    if meta['schema']!='ferrodsp-lab-v2':raise ValueError('Нужна запись формата v2')
    manifest_hash=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest()
    result=render_demo(source,meta,output_dir=destination)
    report=dict(exported_at=now_iso(),source_session=str(source),source_manifest_sha256=manifest_hash,
                source_data_modified=False,demonstration=result,
                rendering_source_sha256={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                                          for name in ['demo_video.py','video_encoding.py','processing.py','distance_filter.py']})
    dump(destination/'export.json',report)
    files=[]
    for p in sorted(destination.iterdir()):
        if p.is_file():
            with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
            files.append(dict(path=p.name,bytes=p.stat().st_size,sha256=digest))
    dump(destination/'manifest.json',dict(files=files))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();print(json.dumps(export(args.source,args.destination),ensure_ascii=False,indent=2))
