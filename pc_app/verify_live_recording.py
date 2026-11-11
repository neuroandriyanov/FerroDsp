"""Explicit hardware validation of an EMPTY setup, after user confirmation.

Restores the already selected geometry, records a 12 s technical trial, and
checks stored files. It never sends commands to SigmaStudio or the DSP.
"""
import bootstrap
import hashlib
import json
import time
import wave
from pathlib import Path
import cv2
import h5py
import numpy as np
from labctl import request
from recording import dump

def command(value):
    result=json.loads(request(value))
    if not result.get('ok'):raise RuntimeError(result)
    return result['result']

def verify():
    state=json.loads(request())
    if state['recording']:raise RuntimeError('A recording is already active')
    command({'action':'restore_geometry'})
    command({'action':'phase_baseline'})
    command({'action':'item_add','item':dict(name='Техническая проверка — пустой фон',material='нет предмета',
        orientation='камера и катушка неподвижны',notes='Проверка программы и файлов; не опыт распознавания металла')})
    command({'action':'record_start'})
    time.sleep(12)
    result=command({'action':'record_stop'})
    for _ in range(60):
        state=json.loads(request())
        if state['last_recording'] and state['last_recording'].get('status')!='finalizing' and not state['recording']:break
        time.sleep(.25)
    path=Path(state['last_recording']['path'])
    meta=json.loads((path/'session.json').read_text(encoding='utf-8'))
    assert meta['status']=='completed',meta
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((path/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in manifest['files'])
    frames=[json.loads(s) for s in (path/'camera.jsonl').read_text(encoding='utf-8').splitlines()]
    iq=[json.loads(s) for s in (path/'iq.jsonl').read_text(encoding='utf-8').splitlines()]
    audio=[json.loads(s) for s in (path/'audio-timing.jsonl').read_text(encoding='utf-8').splitlines()]
    with h5py.File(path/'camera.h5') as f:
        shape=list(f['depth_z16'].shape)
        assert shape[0]==len(frames) and shape[1:]==[480,640]
        assert f['depth_z16'].dtype==np.uint16
        assert f['aligned_color_jpeg'].shape[0]==len(frames)
        assert np.all(np.diff(f['host_monotonic_ns'][:])>0)
    with wave.open(str(path/'spdif.wav'),'rb') as w:
        wav=dict(rate=w.getframerate(),channels=w.getnchannels(),bits=w.getsampwidth()*8,samples=w.getnframes(),duration_s=w.getnframes()/w.getframerate())
        assert wav['rate']==96000 and wav['channels']==2 and wav['bits']==24
        assert wav['samples']==sum(r['frames'] for r in audio)
    cap=cv2.VideoCapture(str(path/'depth-annotated.avi'))
    video_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));ok,first=cap.read();cap.release()
    assert video_frames==len(frames) and ok
    assert len(frames)>300 and 11.5<wav['duration_s']<12.8
    assert all(r['host_ns']>=meta['start_monotonic_ns'] and r['host_ns']<=meta['requested_stop_monotonic_ns'] for r in frames)
    report=dict(checked_at=meta['finished_at'],recording=str(path.relative_to(bootstrap.ROOT)),camera_shape=shape,
                depth_video_frames=video_frames,wav=wav,valid_iq_fraction=sum(r['valid'] for r in iq)/len(iq),
                camera_frame_number_gaps=sum(max(0,b['depth_frame_number']-a['depth_frame_number']-1) for a,b in zip(frames,frames[1:])),
                callback_status_count=sum(bool(r['status']) for r in audio),
                geometry=meta['plane'],empty_scene_valid_distance_count=sum(r['measurement']['valid'] for r in frames),
                manifest_verified=True,program_source_sha256=meta['source_sha256'],
                notes='Empty-scene device and file test, not physical distance accuracy or metal classification validation.')
    dest=bootstrap.ROOT/'experiments/2026-11-11-lab-app';dest.mkdir(exist_ok=True)
    previous=dest/'hardware-validation.json'
    if previous.exists():
        old=json.loads(previous.read_text(encoding='utf-8'))
        stamp=old['checked_at'][:19].replace(':','').replace('-','')
        archive=dest/f'hardware-validation-{stamp}.json'
        if not archive.exists():archive.write_bytes(previous.read_bytes())
    dump(dest/'hardware-validation.json',report)
    cv2.imwrite(str(dest/'recorded-depth-frame.png'),first)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':verify()
