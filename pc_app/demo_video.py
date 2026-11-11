"""Reproducible presentation video rendered AFTER capture on the saved timeline."""
import bootstrap
import json
import math
import os
from pathlib import Path
import cv2
import h5py
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from analysis_data import read_rows, nearest_indices
from processing import preview
from video_encoding import H264Writer
from distance_filter import filter_frames,filter_metadata

COLORS=[(54,207,189),(242,188,103),(110,171,255),(214,148,242)]
LABELS=['RX0','RX1','TX катушка','TX усилитель']

def font(size):
    for path in [Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeui.ttf',Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]:
        if path.exists():return ImageFont.truetype(str(path),size)
    raise RuntimeError('Не найден шрифт Unicode для демонстрационного видео')

def plot(image,times,values,t,seconds,rect,limits,channels,phase=False,max_gap_s=.025):
    x,y,w,h=rect;low,high=limits
    cv2.rectangle(image,(x,y),(x+w,y+h),(65,79,94),1)
    for k in [1,2,3]:cv2.line(image,(x,y+k*h//4),(x+w,y+k*h//4),(38,50,64),1)
    lo=np.searchsorted(times,t-seconds);hi=np.searchsorted(times,t,side='right')
    ts=times[lo:hi];v=values[lo:hi]
    for ch in channels:
        if not len(ts):continue
        xx=np.rint(x+(ts-(t-seconds))*w/seconds).astype(int)
        yy=y+h-(v[:,ch]-low)*h/(high-low)
        ok=np.isfinite(yy)
        # Missing data, time gaps and wrapped phase are visible line breaks.
        connected=ok[1:] & ok[:-1] & (np.diff(ts)>0) & (np.diff(ts)<=max_gap_s)
        if phase:connected &= np.abs(np.diff(v[:,ch]))<180
        starts=np.r_[0,np.flatnonzero(~connected)+1];ends=np.r_[np.flatnonzero(~connected)+1,len(ts)]
        for begin,end in zip(starts,ends):
            if end-begin<2 or not ok[begin:end].all():continue
            points=np.column_stack([xx[begin:end],np.rint(yy[begin:end]).clip(y,y+h)]).astype(np.int32)
            cv2.polylines(image,[points],False,COLORS[ch][::-1],1,cv2.LINE_AA)
    cv2.line(image,(x+w,y),(x+w,y+h),(100,100,240),1)

def limits(values, channels, phase=False):
    v=values[:,channels];finite=v[np.isfinite(v)]
    low,high=(float(finite.min()),float(finite.max())) if len(finite) else (-1.,1.)
    margin=max((high-low)*.08,.01 if phase else .00001)
    return low-margin,high+margin

def render_demo(path, meta, progress=None, output_dir=None):
    path=Path(path);dest=Path(output_dir) if output_dir is not None else path
    dest.mkdir(parents=True,exist_ok=True)
    cfg=meta['settings'];fps=cfg['fps']
    rows=read_rows(path/'camera.jsonl')
    distance_rows=filter_frames(rows,cfg)
    with (dest/'distance-chart.jsonl').open('w',encoding='utf-8') as f:
        for row in distance_rows:f.write(json.dumps(row,allow_nan=False)+'\n')
    start=meta['start_monotonic_ns'];stop=meta.get('requested_stop_monotonic_ns') or meta['stop_monotonic_ns']
    count=max(1,math.ceil((stop-start)/1e9*fps))
    target=start+np.rint(np.arange(count)*1e9/fps).astype(np.int64)
    distance_times=np.array([(r['host_ns']-start)/1e9 for r in distance_rows])
    distance_values=np.array([r['filtered_mm'] for r in distance_rows],float).reshape(-1,1)
    indices=nearest_indices([r['host_ns'] for r in rows],target,round(.6e9/fps))
    channels=meta.get('display',{}).get('settings',{}).get('channels',[0,1,2,3]) or [0,1,2,3]
    baseline=meta.get('display',{}).get('phase_baseline')
    big=font(25);medium=font(18);small=font(15)
    writer=H264Writer(dest/'demonstration.mp4',fps,(1280,640))
    mapping=(dest/'demonstration-timeline.jsonl').open('w',encoding='utf-8')
    item=meta.get('item',{});seconds=cfg.get('demo_seconds',8.)
    try:
        with h5py.File(path/'analysis.h5') as a,h5py.File(path/'camera.h5') as camera:
            times=a['signals/time_s'][:];valid=a['signals/valid'][:]
            phases=a['signals/delta_phase_tx_deg' if baseline else 'signals/phase_tx_deg'][:]
            amplitudes=a['signals/amplitude'][:]
            phases[~valid]=np.nan;amplitudes[~valid]=np.nan
            phase_limits=limits(phases,channels,True);amp_limits=limits(amplitudes,channels)
            distance_limits=limits(distance_values,[0])
            distance_limits=(max(0,distance_limits[0]-2),max(10,distance_limits[1]+2))
            display=meta.get('display',{}).get('settings',{})
            if not display.get('distance_auto',True):distance_limits=tuple(display['distance_limits'])
            phase_quantity='Δ фазы RX/TX, °' if baseline else 'Фаза RX/TX, °'
            for panel,key in enumerate(['top','bottom']):
                if not display.get('auto',[True,True])[panel]:
                    if display.get(key)==phase_quantity:phase_limits=tuple(display['limits'][panel])
                    if display.get(key)=='Амплитуда |Z|':amp_limits=tuple(display['limits'][panel])
            last_index=-2;left=None
            for j,(ns,index) in enumerate(zip(target,indices)):
                t=(int(ns)-start)/1e9
                frame=np.full((640,1280,3),(29,22,16),np.uint8)
                if index>=0:
                    if index!=last_index:
                        row=rows[index];depth=camera['depth_z16'][index].astype(np.float32)*row['depth_scale_m']
                        color=cv2.imdecode(camera['aligned_color_jpeg'][index],cv2.IMREAD_COLOR) if 'aligned_color_jpeg' in camera else np.zeros((480,640,3),np.uint8)
                        viewcfg=dict(cfg)
                        if 'aligned_color_jpeg' not in camera:viewcfg['view']='depth'
                        left,_=preview(color,depth,row['measurement'],viewcfg)
                        last_index=index
                    frame[100:580,:640]=left
                plot(frame,times,phases,t,seconds,(708,132,544,96),phase_limits,channels,True)
                plot(frame,times,amplitudes,t,seconds,(708,292,544,96),amp_limits,channels)
                plot(frame,distance_times,distance_values,t,seconds,(708,452,544,96),distance_limits,[0],max_gap_s=1.8/fps)
                im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(im)
                title=item.get('name','Без названия')
                material=item.get('material','')
                if material and material.lower() not in title.lower():title+=' · '+material
                draw.text((16,12),title[:90],font=big,fill='#ecf2f8')
                planned=item.get('distance_mm','')
                subtitle=item.get('orientation','')+(f'  ·  задано: {planned} мм' if planned else '')
                draw.text((16,48),subtitle[:120],font=medium,fill='#a6b6c7')
                distance=rows[index]['measurement'].get('distance_mm') if index>=0 else None
                label=f'До катушки: {distance:.1f} мм' if distance is not None else 'До катушки: нет достоверной глубины'
                draw.text((16,76),label,font=medium,fill='#5ee1d1')
                if index<0:draw.text((100,300),'НЕТ КАДРА В ЭТОТ МОМЕНТ',font=big,fill='#f7bd74')
                draw.text((708,104),'Δ фазы относительно фона, °' if baseline else 'Фаза относительно TX катушки, °',font=medium,fill='#ecf2f8')
                draw.text((708,264),'Амплитуда |I + jQ|, единицы DSP',font=medium,fill='#ecf2f8')
                draw.text((708,424),'Расстояние, мм · фильтр выбросов',font=medium,fill='#5ee1d1')
                for (low,high),y in [(phase_limits,132),(amp_limits,292),(distance_limits,452)]:
                    draw.text((646,y-5),f'{high:.3g}',font=small,fill='#b7c5d3')
                    draw.text((646,y+81),f'{low:.3g}',font=small,fill='#b7c5d3')
                    draw.text((708,y+99),f'{t-seconds:.1f} с',font=small,fill='#b7c5d3')
                    draw.text((1190,y+99),f'{t:.1f} с',font=small,fill='#b7c5d3')
                x=690
                for ch in channels:
                    draw.text((x,581),LABELS[ch],font=small,fill=COLORS[ch]);x+=135
                draw.text((16,586),f'Время опыта: {t:07.3f} с',font=medium,fill='#ecf2f8')
                draw.text((16,615),'Общая шкала ПК · физическая задержка камеры/тракта пока не откалибрована',font=small,fill='#a6b6c7')
                output=cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2BGR)
                writer.write(output)
                if j==min(count-1,fps*2):cv2.imwrite(str(dest/'demonstration-preview.jpg'),output)
                mapping.write(json.dumps(dict(video_frame=j,time_s=t,host_ns=int(ns),camera_index=int(index),
                    camera_delta_ms=(rows[index]['host_ns']-int(ns))/1e6 if index>=0 else None))+'\n')
                if progress and j%fps==0:progress(j/max(1,count))
    finally:
        try:writer.release()
        finally:mapping.close()
    check=cv2.VideoCapture(str(dest/'demonstration.mp4'))
    actual=int(check.get(cv2.CAP_PROP_FRAME_COUNT));ok,_=check.read();check.release()
    if not ok or actual!=count:raise RuntimeError(f'Проверка демонстрационного видео: {actual}/{count} кадров')
    return dict(file='demonstration.mp4',frames=count,fps=fps,duration_s=count/fps,
                camera_missing_frames=int((indices<0).sum()),size=[1280,640],codec='H.264 / AVC',encoding=writer.result,
                graph_window_s=seconds,channels=channels,phase_limits=list(phase_limits),amplitude_limits=list(amp_limits),
                distance_limits=list(distance_limits),distance_filter=filter_metadata(cfg),
                distance_spikes_corrected=sum(r['corrected'] for r in distance_rows))
