"""Device workers, experiment state and control API shared by the native window."""
import bootstrap
import collections
import copy
import json
import queue
import threading
import time
from pathlib import Path
import cv2
import numpy as np
import pyrealsense2 as rs
import sounddevice as sd
from processing import LiveDecoder, unpack24, fit_plane, nearest_point, preview
from recording import Recorder, dump, now_iso
from wasapi_capture import Capture
from timing import AudioClockMap, SampleTimeline, camera_stamp
from distance_filter import DistanceFilter

APP = bootstrap.APP
LOCAL = bootstrap.LOCAL
RECORDINGS = bootstrap.RECORDINGS
DEFAULTS = dict(view='overlay',alpha_color=.55,alpha_depth=1.,colormap='Turbo',
                color_min_m=.15,color_max_m=1.2,min_depth_m=.12,max_depth_m=2.0,
                foreground_mm=15.,minimum_gap_mm=8.,maximum_gap_mm=1000.,min_area_px=12,
                roi=[0,0,640,480],fps=30,save_color=True,save_video=True,minimum_disk_gb=2.,
                audio_index=None,camera_serial=None,camera_time_offset_ms=0.,audio_time_offset_ms=0.,
                demo_seconds=8.,distance_spike_mm=15.)

class Engine:
    def __init__(self):
        LOCAL.mkdir(parents=True,exist_ok=True)
        RECORDINGS.mkdir(parents=True,exist_ok=True)
        self.config = DEFAULTS.copy()
        self.items = []
        self.selected_item = -1
        self.plane = None
        self.background = None
        self.points = []
        self.point_pixels = []
        self.latest = None
        self.camera_info = {}
        self.camera_options = []
        self.audio_info = {}
        self.raw = np.zeros((100,2))
        self.iq = collections.deque(maxlen=12000)
        self.iq_lock = threading.Lock()
        self.distances=collections.deque(maxlen=5000)
        self.distance_lock=threading.Lock()
        self.camera_status = 'Отключена'
        self.audio_status = 'Отключён'
        self.camera_error = None
        self.audio_error = None
        self.option_error = None
        self.camera_drops = 0
        self.audio_flags = 0
        self.audio_packets = 0
        self.last_audio_ns = 0
        self.last_iq_ns = 0
        self.background_frames = None
        self.background_progress = 0
        self.camera_thread = None
        self.audio_thread = None
        self.stop_event = threading.Event()
        self.camera_commands = queue.Queue()
        self.recorder = None
        self.last_recording = None
        self.finalizer = None
        self.started_ns = time.perf_counter_ns()
        self.errors = collections.deque(maxlen=20)
        self.load_settings()

    def load_settings(self):
        path=LOCAL/'settings.json'
        if path.exists():
            try:
                s=json.loads(path.read_text(encoding='utf-8'))
                self.config.update({k:v for k,v in s.get('config',{}).items() if k in DEFAULTS})
                self.items=s.get('items',[])
                self.selected_item=0 if self.items else -1
            except Exception as exc:self.errors.append(str(exc))

    def save_settings(self):
        dump(LOCAL/'settings.json',dict(config=self.config,items=self.items))

    def set_config(self, changes):
        if self.recorder:
            raise ValueError('Настройки измерения фиксируются на время записи; сначала остановите опыт')
        if any(k not in DEFAULTS for k in changes):raise ValueError('Неизвестный параметр')
        c=dict(self.config,**changes)
        if c['fps'] not in [6,15,30]:raise ValueError('FPS: 6, 15 или 30')
        if c['view'] not in ['color','depth','overlay']:raise ValueError('Неверный вид')
        if c['colormap'] not in ['Turbo','Jet','Viridis','Серый']:raise ValueError('Неверная палитра')
        for key in ['alpha_color','alpha_depth']:
            if not 0 <= c[key] <= 1:raise ValueError('Прозрачность: 0…1')
        if not .05 <= c['min_depth_m'] < c['max_depth_m'] <= 10:raise ValueError('Диапазон глубины: 0.05…10 м')
        if not 0 <= c['color_min_m'] < c['color_max_m'] <= 10:raise ValueError('Неверный диапазон палитры')
        if not 1 <= c['foreground_mm'] <= 200:raise ValueError('Порог фона: 1…200 мм')
        if not np.isfinite(c['distance_spike_mm']) or not 1<=c['distance_spike_mm']<=500:raise ValueError('Порог выбросов расстояния: 1…500 мм')
        if not 0 <= c['minimum_gap_mm'] < c['maximum_gap_mm'] <= 10000:raise ValueError('Неверный диапазон расстояний до катушки')
        if not 3 <= c['min_area_px'] <= 10000:raise ValueError('Неверный размер связной области')
        if not .2 <= c['minimum_disk_gb'] <= 1000:raise ValueError('Неверный запас диска')
        for key in ['camera_time_offset_ms','audio_time_offset_ms']:
            if not np.isfinite(c[key]) or abs(c[key])>2000:raise ValueError('Поправка времени: −2000…2000 мс')
        if not 2<=c['demo_seconds']<=60:raise ValueError('Окно демонстрационных графиков: 2…60 с')
        x,y,w,h=c['roi']
        if not all(isinstance(v,int) for v in [x,y,w,h]) or x<0 or y<0 or w<4 or h<4 or x+w>640 or y+h>480:
            raise ValueError('ROI должен лежать внутри 640×480')
        if any(c[k]!=self.config[k] for k in ['fps','camera_serial','audio_index','camera_time_offset_ms','audio_time_offset_ms']) and self.running:
            raise ValueError('Для смены устройства, FPS или поправок времени сначала отключите потоки')
        if c['camera_serial']!=self.config['camera_serial']:
            self.plane=None;self.background=None
        self.config=c
        self.save_settings()

    @property
    def running(self):
        return bool((self.camera_thread and self.camera_thread.is_alive()) or (self.audio_thread and self.audio_thread.is_alive()))

    def start(self):
        if self.running:return
        self.stop_event.clear()
        self.latest=None;self.camera_error=None;self.audio_error=None
        self.iq.clear();self.audio_flags=0;self.audio_packets=0
        with self.distance_lock:self.distances.clear()
        self.last_audio_ns=0;self.last_iq_ns=0;self.camera_drops=0
        self.camera_status='Подключение…';self.audio_status='Подключение…'
        self.started_ns=time.perf_counter_ns()
        self.camera_thread=threading.Thread(target=self._camera,name='D415',daemon=True)
        self.audio_thread=threading.Thread(target=self._audio,name='SPDIF',daemon=True)
        self.camera_thread.start();self.audio_thread.start()

    def stop(self):
        if self.recorder:
            self.stop_recording()
            raise RuntimeError('Запись завершается; отключение станет доступно после сохранения')
        self.stop_event.set()
        for thread in [self.camera_thread,self.audio_thread]:
            if thread:thread.join(timeout=7)
        if self.running:raise RuntimeError('Поток ещё останавливается')
        if self.finalizer and self.finalizer.is_alive():
            raise RuntimeError('Файлы опыта ещё закрываются; повторите закрытие после сообщения «Сохранено»')
        self.camera_status='Отключена';self.audio_status='Отключён'

    def _options(self, sensors):
        rows=[]
        for i,sensor in enumerate(sensors):
            name=sensor.get_info(rs.camera_info.name)
            for option in sensor.get_supported_options():
                try:
                    r=sensor.get_option_range(option)
                    rows.append(dict(sensor=i,sensor_name=name,option=int(option),name=str(option).replace('option.',''),
                                     value=sensor.get_option(option),minimum=r.min,maximum=r.max,step=r.step,
                                     default=r.default,readonly=sensor.is_option_read_only(option),description=sensor.get_option_description(option)))
                except RuntimeError:pass
        self.camera_options=rows

    def set_camera_option(self, sensor, option, value):
        if self.recorder:raise ValueError('Во время записи параметры камеры заблокированы')
        row=next((r for r in self.camera_options if r['sensor']==sensor and r['option']==option),None)
        if not row or row['readonly']:raise ValueError('Параметр отсутствует или доступен только для чтения')
        if not np.isfinite(value) or not row['minimum'] <= value <= row['maximum']:raise ValueError('Значение вне допустимого диапазона')
        if row['step'] and abs((value-row['minimum'])/row['step']-round((value-row['minimum'])/row['step']))>.001:
            raise ValueError('Значение не соответствует шагу параметра')
        self.camera_commands.put((sensor,option,value))

    def _camera(self):
        pipeline=None
        try:
            context=rs.context()
            devices=[d for d in context.query_devices() if 'D415' in d.get_info(rs.camera_info.name)]
            serial=self.config['camera_serial']
            devices=[d for d in devices if not serial or d.get_info(rs.camera_info.serial_number)==serial]
            if len(devices)!=1:raise RuntimeError('Не найдена единственная D415; выберите серийный номер')
            device=devices[0]
            serial=device.get_info(rs.camera_info.serial_number)
            pipeline=rs.pipeline(context)
            cfg=rs.config();cfg.enable_device(serial)
            cfg.enable_stream(rs.stream.depth,640,480,rs.format.z16,self.config['fps'])
            cfg.enable_stream(rs.stream.color,640,480,rs.format.bgr8,self.config['fps'])
            profile=pipeline.start(cfg)
            sensors=profile.get_device().query_sensors()
            scale=profile.get_device().first_depth_sensor().get_depth_scale()
            intr=profile.get_stream(rs.stream.depth).as_video_stream_profile().get_intrinsics()
            self.camera_info=dict(name='RealSense D415',serial=serial,firmware=device.get_info(rs.camera_info.firmware_version),
                                  depth_scale_m=scale,width=640,height=480,fps=self.config['fps'],
                                  intrinsics=dict(fx=intr.fx,fy=intr.fy,ppx=intr.ppx,ppy=intr.ppy,model=str(intr.model),coeffs=list(intr.coeffs)),
                                  alignment='RGB resampled into native depth coordinates using factory extrinsics')
            self._options(sensors)
            align=rs.align(rs.stream.depth)
            cloud=rs.pointcloud()
            last_frame=None
            distance_filter=None;distance_key=None
            history=collections.deque(maxlen=3);history_key=None;active_recorder=None
            self.camera_status='640×480 · '+str(self.config['fps'])+' кадр/с'
            while not self.stop_event.is_set():
                while not self.camera_commands.empty():
                    i,o,value=self.camera_commands.get_nowait()
                    try:
                        sensors[i].set_option(rs.option(o),value)
                        self.option_error=None
                        # Acquisition changes invalidate the empty-scene reference.
                        self.background=None
                        if str(rs.option(o)) in ['option.depth_units','option.visual_preset','option.disparity_shift']:
                            self.plane=None
                        self._options(sensors)
                    except Exception as exc:self.option_error=str(exc)
                frames=pipeline.wait_for_frames(timeout_ms=3000)
                arrival=time.perf_counter_ns()
                d0=frames.get_depth_frame();c0=frames.get_color_frame()
                if not d0 or not c0:continue
                depth_clock=camera_stamp(d0,rs,arrival);color_clock=camera_stamp(c0,rs,arrival)
                host=depth_clock['host_ns']+round(self.config['camera_time_offset_ms']*1e6)
                frames=align.process(frames)
                d=frames.get_depth_frame();c=frames.get_color_frame()
                if not d or not c:continue
                scale=d.get_units()
                self.camera_info=dict(self.camera_info,depth_scale_m=scale)
                raw=np.asanyarray(d.get_data()).copy()
                depth=raw.astype(np.float32)*scale
                color=np.asanyarray(c.get_data()).copy()
                pts=cloud.calculate(d)
                xyz=np.asanyarray(pts.get_vertices()).view(np.float32).reshape(480,640,3).copy()
                number=d.get_frame_number()
                if last_frame is not None:self.camera_drops+=max(0,number-last_frame-1)
                last_frame=number
                if self.background_frames is not None:
                    self.background_frames.append(depth)
                    self.background_progress=len(self.background_frames)
                    if len(self.background_frames)>=15:
                        stack=np.array(self.background_frames)
                        # Pixels must be valid in at least half the frames; no hole filling.
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore',RuntimeWarning)
                            bg=np.nanmedian(np.where(stack>0,stack,np.nan),axis=0)
                        bg[np.sum(stack>0,axis=0)<8]=0
                        self.background=np.nan_to_num(bg,nan=0).astype(np.float32)
                        self.background_frames=None
                        np.save(LOCAL/'background-m.npy',self.background)
                cfg=self.config.copy()
                measurement=nearest_point(depth,xyz,self.background,self.plane,cfg)
                new_key=(id(self.plane),id(self.background),tuple(cfg['roi']),*(cfg[k] for k in [
                    'min_depth_m','max_depth_m','foreground_mm','minimum_gap_mm','maximum_gap_mm','min_area_px','distance_spike_mm']))
                if new_key!=distance_key:
                    distance_filter=DistanceFilter(cfg);distance_key=new_key
                    with self.distance_lock:self.distances.clear()
                with self.distance_lock:self.distances.extend(distance_filter.push(host,measurement))
                shown,video=preview(color,depth,measurement,cfg,self.point_pixels)
                packet=dict(depth_raw=raw,depth_m=depth,xyz=xyz,color=color,preview=shown,depth_video=video,
                            host_ns=host,host_arrival_ns=arrival,depth_clock=depth_clock,color_clock=color_clock,
                            color_host_ns=color_clock['host_ns']+round(self.config['camera_time_offset_ms']*1e6),
                            depth_scale_m=scale,depth_frame_number=int(number),
                            color_frame_number=int(c.get_frame_number()),
                            depth_timestamp_ms=d.get_timestamp(),color_timestamp_ms=c.get_timestamp(),
                            depth_timestamp_domain=str(d.get_frame_timestamp_domain()),
                            color_timestamp_domain=str(c.get_frame_timestamp_domain()),measurement=measurement)
                self.latest=packet
                key=(cfg,id(self.plane),id(self.background))
                if key!=history_key:
                    history=collections.deque(maxlen=max(3,int(np.ceil(max(0,cfg['camera_time_offset_ms'])/1000*cfg['fps']))+3))
                    history_key=key
                saved={k:v for k,v in packet.items() if k not in ['depth_m','xyz','preview','depth_video']}
                recorder=self.recorder
                if recorder:
                    if active_recorder is not recorder:
                        for old in history:recorder.submit('camera',old)
                    recorder.submit('camera',saved)
                active_recorder=recorder;history.append(saved)
        except Exception as exc:
            self.camera_error=f'{type(exc).__name__}: {exc}'
            self.camera_status='Ошибка камеры'
            self.errors.append(self.camera_error)
        finally:
            if pipeline:
                try:pipeline.stop()
                except RuntimeError:pass

    def _audio(self):
        try:
            hosts=sd.query_hostapis()
            candidates=[dict(d,index=i,hostapi_name=hosts[d['hostapi']]['name']) for i,d in enumerate(sd.query_devices())
                        if d['max_input_channels']>=2 and 'spdif' in d['name'].lower() and hosts[d['hostapi']]['name']=='Windows WASAPI']
            index=self.config['audio_index']
            candidates=[d for d in candidates if (d['index']==index if index is not None else 'sound blaster g3' in d['name'].lower())]
            if len(candidates)!=1:raise RuntimeError('Выберите единственный S/PDIF WASAPI; микрофон не используется')
            device=candidates[0]
            decoder=LiveDecoder()
            clock=AudioClockMap();timeline=SampleTimeline();last_device_end=None
            sample_index=0;history=collections.deque(maxlen=1000);active_recorder=None;history_offset=None
            # Sounddevice only enumerates the UI choice. Native WASAPI owns capture.
            name=device['name']
            if 'sound blaster g3' in name.lower():name='sound blaster g3'
            with Capture(name_contains=name) as stream:
                self.audio_info=stream.info
                self.audio_status='S/PDIF · 96 кГц · 24 бит'
                for packet in stream.packets(self.stop_event):
                    clock.update(packet,stream.frequency.value)
                    offset=self.config['audio_time_offset_ms']
                    if offset!=history_offset:history.clear();history_offset=offset
                    packet['host_first_sample_estimate_ns']+=round(offset*1e6)
                    gap=0 if last_device_end is None else packet['device_sample_start']-last_device_end
                    packet['device_gap_samples']=gap
                    if gap:packet['status']+=',device_position_gap'
                    last_device_end=packet['device_sample_start']+packet['frames']
                    self.last_audio_ns=time.perf_counter_ns()
                    self.audio_packets+=1
                    packet['stream_sample_start']=sample_index
                    timeline.append(packet)
                    if packet['status']:self.audio_flags+=1
                    recorder=self.recorder
                    if recorder:
                        def save_audio(p):
                            # Pre/post-roll preserves complete centred analysis windows.
                            period=p['sample_period_ns']
                            trim=max(0,min(p['frames'],int(np.ceil((recorder.start_ns-150_000_000-p['host_first_sample_estimate_ns'])/period))))
                            end=p['frames']
                            if recorder.stop_ns is not None:
                                end=max(0,min(end,int(np.ceil((recorder.stop_ns+150_000_000-p['host_first_sample_estimate_ns'])/period))))
                            if trim<end:
                                saved=dict(p,payload=p['payload'][trim*6:end*6],frames=end-trim,
                                           stream_sample_start=p['stream_sample_start']+trim,trimmed_prefix_samples=trim,
                                           device_sample_start=p['device_sample_start']+trim,
                                           host_first_sample_estimate_ns=p['host_first_sample_estimate_ns']+round(trim*period))
                                recorder.submit('audio',saved)
                        if active_recorder is not recorder:
                            for old in history:save_audio(old)
                        save_audio(packet)
                    active_recorder=recorder;history.append(packet)
                    x=unpack24(packet['payload'])
                    self.raw=np.concatenate([self.raw,x])[-9600:]
                    rows=decoder.feed(x,bad=bool(packet['status']) or not packet['timestamp_valid'])
                    for row in rows:
                        row.update(timeline.locate(row['sample']))
                        row['valid']=bool(row['valid'] and row['timestamp_valid'])
                        row['time_s']=(row['host_ns']-self.started_ns)/1e9
                        with self.iq_lock:self.iq.append(row)
                        self.last_iq_ns=time.perf_counter_ns()
                        if recorder:recorder.submit('iq',row)
                    sample_index+=packet['frames']
        except Exception as exc:
            self.audio_error=f'{type(exc).__name__}: {exc}'
            self.audio_status='Ошибка S/PDIF'
            self.errors.append(self.audio_error)

    def capture_background(self):
        if self.recorder:raise ValueError('Сначала остановите запись')
        if not self.latest:raise ValueError('Нет кадров камеры')
        self.background_frames=[];self.background_progress=0
        return 'Сохраняются 15 кадров пустого фона'

    def add_point(self,x,y):
        if self.recorder:raise ValueError('Сначала остановите запись')
        if not self.latest:raise ValueError('Нет кадров камеры')
        x,y=int(x),int(y)
        if not 2<=x<638 or not 2<=y<478:raise ValueError('Выберите точку внутри кадра')
        xyz=self.latest['xyz'][y-2:y+3,x-2:x+3].reshape(-1,3)
        p=xyz[xyz[:,2]>0]
        if len(p)<13:raise ValueError('В этой точке недостаточно достоверной глубины')
        point=np.median(p,axis=0)
        if np.ptp(p[:,2])>.025:raise ValueError('Точка попала на край/разрыв глубины; выберите середину поверхности')
        self.points.append(point.tolist());self.point_pixels.append((x,y))
        return {'count':len(self.points),'point_m':point.tolist()}

    def clear_points(self):
        if self.recorder:raise ValueError('Сначала остановите запись')
        self.points=[];self.point_pixels=[]

    def calibrate(self):
        if self.recorder:raise ValueError('Сначала остановите запись')
        self.plane=dict(fit_plane(self.points),camera=self.camera_info,created_at=now_iso(),pixels=self.point_pixels)
        dump(LOCAL/'plane.json',self.plane)
        return self.plane

    def restore_geometry(self):
        if self.recorder:raise ValueError('Сначала остановите запись')
        if not self.camera_info or not self.latest:raise ValueError('Сначала подключите камеру')
        plane=json.loads((LOCAL/'plane.json').read_text(encoding='utf-8'))
        if plane['camera']['serial']!=self.camera_info['serial'] or plane['camera']['intrinsics']!=self.camera_info['intrinsics']:
            raise ValueError('Сохранённая геометрия относится к другой камере/конфигурации')
        background=np.load(LOCAL/'background-m.npy',allow_pickle=False)
        if background.shape!=(480,640) or not np.isfinite(background).all():raise ValueError('Повреждён сохранённый фон')
        self.plane=plane;self.background=background
        self.points=plane.get('points_m',[]);self.point_pixels=plane.get('pixels',[])
        return 'Привязка восстановлена. Она действительна, только если камера и катушка не перемещались.'

    def manual_plane(self,distance_mm):
        if self.recorder:raise ValueError('Сначала остановите запись')
        if not 100<=distance_mm<=5000:raise ValueError('Расстояние: 100…5000 мм')
        self.plane=dict(normal=[0,0,1],offset_m=distance_mm/1000,rms_mm=None,
                        method='manual_parallel_plane_assumption',camera=self.camera_info,created_at=now_iso())
        dump(LOCAL/'plane.json',self.plane)

    def start_recording(self, display=None):
        if self.recorder:raise ValueError('Запись уже идёт')
        if self.finalizer and self.finalizer.is_alive():raise ValueError('Предыдущая запись ещё сохраняется')
        if not 0<=self.selected_item<len(self.items):raise ValueError('Добавьте и выберите предмет в таблице')
        if not self.items[self.selected_item].get('name','').strip():raise ValueError('Заполните название предмета')
        now=time.perf_counter_ns()
        if not self.latest or now-self.latest['host_arrival_ns']>1_000_000_000 or self.camera_error:
            raise ValueError('Нет свежих кадров камеры')
        if self.audio_error or now-self.last_audio_ns>1_000_000_000:raise ValueError('Нет свежих данных S/PDIF')
        if not self.plane or self.background is None:raise ValueError('Задайте плоскость катушки и сохраните пустой фон')
        with self.iq_lock: recent=list(self.iq)[-100:]
        if len(recent)<50 or sum(r['valid'] for r in recent)/len(recent)<.5:
            raise ValueError('Декодер не подтверждает устойчивый поток I/Q; проверьте DSP и оптику')
        metadata=dict(item=copy.deepcopy(self.items[self.selected_item]),display=display or {},camera=self.camera_info,
                      camera_options=self.camera_options,plane=self.plane,settings=self.config.copy(),audio=self.audio_info,
                      camera_drops_at_start=self.camera_drops,audio_flags_at_start=self.audio_flags)
        self.recorder=Recorder(RECORDINGS,metadata,self.background,self.config)
        return str(self.recorder.path)

    def stop_recording(self,reason='user'):
        recorder=self.recorder
        if not recorder:return self.last_recording
        if recorder.stop_ns is not None:return self.last_recording
        recorder.stop_ns=time.perf_counter_ns()
        recorder.submit('event',dict(type='final_counters',host_ns=time.perf_counter_ns(),camera_drops=self.camera_drops,audio_flags=self.audio_flags))
        self.last_recording=dict(path=str(recorder.path),error=None,status='finalizing')
        def finish():
            try:
                # Allow delayed WASAPI buffers and the decoder look-ahead to reach
                # the requested boundary. Timestamp filters discard later frames.
                correction=max(0,-recorder.config['camera_time_offset_ms'],-recorder.config['audio_time_offset_ms'])/1000
                time.sleep(max(.3,self.audio_info.get('latency',.1)+.15)+correction)
                result=recorder.stop(reason)
                self.last_recording=dict(result,status='closed')
                self.recorder=None
            except Exception as exc:
                self.last_recording=dict(path=str(recorder.path),error=str(exc),status='close_error')
                self.recorder=None
        self.finalizer=threading.Thread(target=finish,name='finalize-recording',daemon=False)
        self.finalizer.start()
        return self.last_recording

    def status(self):
        latest=self.latest
        with self.iq_lock:recent=list(self.iq)[-100:]
        with self.distance_lock:last_distance=dict(self.distances[-1]) if self.distances else None
        return dict(running=self.running,camera_status=self.camera_status,audio_status=self.audio_status,
                    camera_error=self.camera_error,audio_error=self.audio_error,option_error=self.option_error,
                    camera=self.camera_info,audio=self.audio_info,camera_drops=self.camera_drops,audio_flags=self.audio_flags,
                    camera_age_ms=(time.perf_counter_ns()-latest['host_arrival_ns'])/1e6 if latest else None,
                    measurement=latest['measurement'] if latest else None,plane=self.plane,
                    distance_chart=last_distance,
                    background_ready=self.background is not None,background_progress=self.background_progress,
                    plane_points=self.point_pixels,valid_iq_fraction=sum(r['valid'] for r in recent)/len(recent) if recent else 0,
                    last_iq=recent[-1] if recent else None,items=self.items,selected_item=self.selected_item,
                    recording=dict(path=str(self.recorder.path),counts=self.recorder.counts,error=self.recorder.error,
                                   stage=self.recorder.stage,export_progress=self.recorder.export_progress,
                                   stopping=self.recorder.stop_ns is not None) if self.recorder else None,
                    last_recording=self.last_recording,settings=self.config,errors=list(self.errors))
