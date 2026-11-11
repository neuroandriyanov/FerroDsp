"""Explicit 12 s device/file smoke test; no metal labels or accuracy claims."""
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
from analysis_data import read_rows
from processing import LiveDecoder,unpack24

def command(value):
    result=json.loads(request(value))
    if not result.get('ok'):raise RuntimeError(result)
    return result['result']

def verify():
    initial=json.loads(request())
    if initial['recording']:raise RuntimeError('Recording already active')
    command({'action':'restore_geometry'})
    command({'action':'phase_baseline'})
    command({'action':'item_add','item':dict(name='Проверка синхронной записи',material='технический опыт',
        orientation='камера и катушка неподвижны',notes='Проверка часов и файлов; не измерение точности и не разметка металла')})
    command({'action':'record_start'})
    time.sleep(12)
    command({'action':'record_stop'})
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        state=json.loads(request())
        if not state['recording'] and state.get('last_recording',{}).get('status')!='finalizing':break
        time.sleep(.3)
    else:raise RuntimeError('Finalization timeout')
    path=Path(state['last_recording']['path'])
    meta=json.loads((path/'session.json').read_text(encoding='utf-8'))
    assert meta['status']=='completed',meta.get('error')
    files=json.loads((path/'manifest.json').read_text(encoding='utf-8'))['files']
    for entry in files:
        with (path/entry['path']).open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        assert actual==entry['sha256'],entry['path']
    audio=read_rows(path/'audio-timing.jsonl');frames=read_rows(path/'camera.jsonl');iq=read_rows(path/'iq.jsonl')
    with wave.open(str(path/'spdif.wav')) as wav:
        assert wav.getnframes()==sum(p['frames'] for p in audio)
        assert (wav.getframerate(),wav.getsampwidth(),wav.getnchannels())==(96000,3,2)
        duration=wav.getnframes()/96000
    assert 12.1<duration<13, duration
    at=np.array([p['host_first_sample_estimate_ns'] for p in audio])
    it=np.array([p['host_ns'] for p in iq]);ft=np.array([p['host_ns'] for p in frames])
    assert np.all(np.diff(at)>0) and np.all(np.diff(it)>0) and np.all(np.diff(ft)>0)
    assert all(p['timestamp_valid'] for p in audio)
    assert all(p['depth_clock']['timestamp_valid'] for p in frames)
    assert audio[0]['host_first_sample_estimate_ns']<meta['start_monotonic_ns']-140_000_000
    assert audio[-1]['host_first_sample_estimate_ns']>meta['requested_stop_monotonic_ns']+140_000_000
    assert all(b['stream_sample_start']==a['stream_sample_start']+a['frames'] for a,b in zip(audio,audio[1:]))
    with h5py.File(path/'analysis.h5') as h:
        assert len(h['frames/time_s'])==len(frames)
        assert len(h['signals/time_s'])==len(iq)
        assert h['aligned_frames/complete_observation'].dtype==np.bool_
        pairs=h['aligned_frames/signal_index'][:];dt=h['aligned_frames/signal_minus_frame_ms'][:]
        assert np.all(np.abs(dt[pairs>=0])<=15)
        valid=h['signals/valid'][:]
        fraction=float(valid.mean());assert fraction>.9,fraction
        np.testing.assert_allclose(h['signals/amplitude'][:],np.abs(np.array([r['iq'] for r in iq])[:,::2]+1j*np.array([r['iq'] for r in iq])[:,1::2]))
        centres=h['signals/wav_center_sample'][:]
        decoder=LiveDecoder()
        with wave.open(str(path/'spdif.wav')) as wav:
            for i in np.linspace(0,len(iq)-1,12,dtype=int):
                first=round(centres[i]-(decoder.n-1)/2)
                assert first>=0 and first+decoder.n<=wav.getnframes()
                wav.setpos(first);block=unpack24(wav.readframes(decoder.n))
                z=decoder.kernel@block
                ratios=(np.abs(z[:4])/np.abs(z[4])[None,:]).reshape(8)
                recovered=(ratios-decoder.cal['intercept'])/decoder.cal['slope']
                np.testing.assert_allclose(recovered,iq[i]['iq'],atol=1e-10)
    video=cv2.VideoCapture(str(path/'demonstration.mp4'))
    video_count=int(video.get(cv2.CAP_PROP_FRAME_COUNT));fps=video.get(cv2.CAP_PROP_FPS)
    video.set(cv2.CAP_PROP_POS_FRAMES,min(video_count-1,60));ok,image=video.read();video.release()
    assert ok and image.shape==(640,1280,3)
    assert abs(video_count/fps-(meta['requested_stop_monotonic_ns']-meta['start_monotonic_ns'])/1e9)<=1/fps
    report=dict(recording=str(path.relative_to(bootstrap.ROOT)),checked_at=meta['finished_at'],schema=meta['schema'],
        frames=len(frames),iq_rows=len(iq),valid_iq_fraction=fraction,audio_duration_s=duration,
        audio_flagged_packets=sum(bool(p['status']) for p in audio),
        camera_frame_gaps=sum(max(0,b['depth_frame_number']-a['depth_frame_number']-1) for a,b in zip(frames,frames[1:])),
        timestamp_source_counts={name:sum(p['depth_clock']['timestamp_source']==name for p in frames) for name in {p['depth_clock']['timestamp_source'] for p in frames}},
        camera_exposure_timestamp_available=all(p['depth_clock']['exposure_time_known'] for p in frames),
        audio_clock_residual_p95_ms_max=max(p['clock_fit']['residual_p95_ms'] for p in audio),
        audio_timestamp_before_arrival_ms_range=[float(np.min([(p['host_arrival_ns']-p['host_first_sample_estimate_ns'])/1e6 for p in audio])),float(np.max([(p['host_arrival_ns']-p['host_first_sample_estimate_ns'])/1e6 for p in audio]))],
        video=meta['demonstration'],analysis=meta['analysis'],manifest_verified=True,raw_pcm_redecoded_windows=12,
        source_sha256=meta['source_sha256'],notes='File/timeline consistency only. No physical latency, distance accuracy or classification validation.')
    dest=bootstrap.ROOT/'experiments/2026-11-11-synchronized-recording';dest.mkdir(exist_ok=True)
    dump(dest/f'{path.name}-validation.json',report)
    cv2.imwrite(str(dest/f'{path.name}-demonstration.jpg'),image)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':verify()
