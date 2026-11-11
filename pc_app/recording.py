"""Bounded, asynchronous experiment writer. Every accepted packet is accounted for."""
import bootstrap
import hashlib
import json
import queue
import shutil
import threading
import time
import uuid
import wave
from datetime import datetime, timezone, timedelta
from pathlib import Path
import cv2
import h5py
import numpy as np

SAMARA = timezone(timedelta(hours=4))

def now_iso():
    return datetime.now(SAMARA).isoformat()

def dump(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)

class Recorder:
    def __init__(self, root, metadata, background, config):
        if shutil.disk_usage(root).free < config['minimum_disk_gb']*1024**3:
            raise ValueError('Недостаточно свободного места для записи')
        stamp = datetime.now(SAMARA).strftime('%Y%m%d-%H%M%S')
        self.path = Path(root)/f'{stamp}-{uuid.uuid4().hex[:8]}'
        self.path.mkdir(parents=True,exist_ok=False)
        self.start_ns = time.perf_counter_ns()
        self.stop_ns = None
        self.stage='capture';self.export_progress=0.
        self.meta = dict(metadata, schema='ferrodsp-lab-v2', started_at=now_iso(),
                         settings=config.copy(),
                         start_monotonic_ns=self.start_ns, status='recording',
                         synchronization='Common host QPC timeline: per-packet IAudioClock mapping, camera SDK exposure or backend time; raw clocks retained. Physical latency is not calibrated.',
                         video_timing='Demo is resampled from saved timestamps onto the requested recording interval; missing frames remain explicit.',
                         analysis_window=dict(type='Hann centred',duration_ms=40,hop_ms=10,decoder_lookahead_ms=70),
                         raw_audio_padding_ms=150,
                         geometry_limit='Visible camera-facing surface to calibrated plane; occluded nearest surface and object thickness are not measured.')
        self.config = config.copy()
        self.accepting = True
        self.error = None
        self.queue = queue.Queue(maxsize=240)
        self.lock = threading.Lock()
        self.counts = {'camera':0,'audio_samples':0,'iq':0,'rejected_packets':0}
        if background is not None:
            np.save(self.path/'background-m.npy',background)
        calibration = Path(__file__).parent/'resources/transport-calibration.json'
        shutil.copyfile(calibration,self.path/'transport-calibration.json')
        self.meta['calibration_sha256'] = hashlib.sha256(calibration.read_bytes()).hexdigest()
        self.meta['application_build'] = bootstrap.build_info()
        self.meta['source_sha256'] = self.meta['application_build']['source_sha256']
        dump(self.path/'session.json',self.meta)
        self.thread = threading.Thread(target=self._run,name='experiment-writer',daemon=False)
        self.thread.start()

    def submit(self, kind, packet):
        with self.lock:
            if not self.accepting:
                return
            # Drop pre-start analysis windows, not actual raw audio packets.
            if kind in ['camera','iq'] and (packet['host_ns'] < self.start_ns or
                    (self.stop_ns is not None and packet['host_ns'] > self.stop_ns)):
                return
            try:
                self.queue.put_nowait((kind,packet))
            except queue.Full:
                self.counts['rejected_packets'] += 1
                self.error = 'Переполнена очередь записи. Опыт неполный; данные сохранены.'
                self.accepting = False

    def stop(self, reason='user'):
        with self.lock:
            self.accepting = False
        if self.thread.is_alive():
            self.queue.put(('stop',reason),timeout=10)
        # Called by the finalizer worker, never the UI: large-file hashing may
        # legitimately take time. Do not declare completion while it still runs.
        self.thread.join()
        return dict(path=str(self.path), **self.counts, error=self.error)

    def _run(self):
        raw = None
        data = None
        logs = {}
        reason = 'writer_error'
        try:
            raw = wave.open(str(self.path/'spdif.wav'),'wb')
            raw.setnchannels(2); raw.setsampwidth(3); raw.setframerate(96000)
            data = h5py.File(self.path/'camera.h5','w')
            depth = data.create_dataset('depth_z16',shape=(0,480,640),maxshape=(None,480,640),
                                        dtype='<u2',chunks=(1,480,640),compression='lzf')
            times = data.create_dataset('host_monotonic_ns',shape=(0,),maxshape=(None,),dtype='<i8')
            color = None
            if self.config['save_color']:
                color = data.create_dataset('aligned_color_jpeg',shape=(0,),maxshape=(None,),dtype=h5py.vlen_dtype(np.dtype('uint8')))
            logs = {name:(self.path/f'{name}.jsonl').open('w',encoding='utf-8')
                    for name in ['camera','audio-timing','iq','events']}
            while True:
                kind,p = self.queue.get()
                if kind == 'stop':
                    reason = p
                    break
                if kind == 'camera':
                    i = self.counts['camera']
                    depth.resize(i+1,axis=0); depth[i] = p['depth_raw']
                    times.resize(i+1,axis=0); times[i] = p['host_ns']
                    if color is not None:
                        ok,jpg = cv2.imencode('.jpg',p['color'],[cv2.IMWRITE_JPEG_QUALITY,95])
                        if not ok: raise RuntimeError('JPEG encode failed')
                        color.resize(i+1,axis=0); color[i] = jpg.reshape(-1)
                    record = {k:v for k,v in p.items() if k not in ['depth_raw','color','depth_video']}
                    record['stored_frame_index'] = i
                    data.attrs['depth_scale_m'] = p['depth_scale_m']
                    logs['camera'].write(json.dumps(record,ensure_ascii=False)+'\n')
                    self.counts['camera'] += 1
                    if i % 30 == 0:
                        data.flush()
                        if shutil.disk_usage(self.path).free < self.config['minimum_disk_gb']*1024**3:
                            raise RuntimeError('Запись остановлена: мало свободного места')
                elif kind == 'audio':
                    raw.writeframesraw(p['payload'])
                    record = {k:v for k,v in p.items() if k != 'payload'}
                    record['wav_sample_start'] = self.counts['audio_samples']
                    logs['audio-timing'].write(json.dumps(record)+'\n')
                    self.counts['audio_samples'] += p['frames']
                elif kind == 'iq':
                    logs['iq'].write(json.dumps(p)+'\n')
                    self.counts['iq'] += 1
                elif kind == 'event':
                    logs['events'].write(json.dumps(p,ensure_ascii=False)+'\n')
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            self.accepting = False
        finally:
            for f in logs.values(): f.close()
            if data is not None: data.close()
            if raw is not None: raw.close()
            self.meta.update(finished_at=now_iso(),stop_monotonic_ns=time.perf_counter_ns(),
                             requested_stop_monotonic_ns=self.stop_ns,
                             status='incomplete' if self.error else 'completed',error=self.error,
                             stop_reason=reason,counts=self.counts)
            if self.counts['camera'] == 0 or self.counts['audio_samples'] == 0:
                self.meta['status'] = 'incomplete'
            self.stage='analysis'
            try:
                from analysis_data import write_analysis
                self.meta['analysis']=write_analysis(self.path,self.meta)
                if self.config['save_video'] and self.counts['camera']:
                    from demo_video import render_demo
                    self.stage='demonstration'
                    self.meta['demonstration']=render_demo(self.path,self.meta,lambda v:setattr(self,'export_progress',v))
            except Exception as exc:
                self.error=self.error or f'Экспорт: {type(exc).__name__}: {exc}'
                self.meta['error']=self.error;self.meta['status']='incomplete'
            self.stage='hashes'
            dump(self.path/'session.json',self.meta)
            # Hash in chunks; long recordings must not be loaded into RAM.
            manifest=[]
            for p in sorted(self.path.iterdir()):
                if not p.is_file() or p.name=='manifest.json':continue
                digest=hashlib.sha256()
                with p.open('rb') as f:
                    for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
                manifest.append(dict(path=p.name,bytes=p.stat().st_size,sha256=digest.hexdigest()))
            dump(self.path/'manifest.json',{'files':manifest,'status':self.meta['status']})
            self.stage='done';self.export_progress=1.
