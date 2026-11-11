"""Derived values and explicit, bounded nearest-neighbour time joins."""
import bootstrap
import json
from pathlib import Path
import h5py
import numpy as np
from distance_filter import filter_frames,filter_metadata

def read_rows(path):
    with Path(path).open(encoding='utf-8') as f:return [json.loads(line) for line in f if line.strip()]

def features(iq, baseline=None):
    x=np.asarray(iq,float).reshape(-1,8)
    z=x[:,0::2]+1j*x[:,1::2]
    amp=np.abs(z);phase_valid=amp>1e-8
    ratio=np.full_like(z,np.nan);good=amp[:,2]>1e-8
    ratio[good]=z[good]/z[good,2,None]
    phase=np.where(phase_valid,np.angle(z,deg=True),np.nan)
    relative=np.where(phase_valid & good[:,None],np.angle(ratio,deg=True),np.nan)
    delta=np.full_like(relative,np.nan);dz=np.full_like(z,np.nan)
    if baseline is not None:
        b=np.asarray(baseline,float);b=b[:,0]+1j*b[:,1]
        delta=np.where((np.abs(b)>1e-8)[None,:] & phase_valid & good[:,None],np.angle(ratio*b.conj(),deg=True),np.nan)
        dz=ratio-b
    return dict(amplitude=amp,phase_deg=phase,phase_tx_deg=relative,delta_phase_tx_deg=delta,
                amplitude_tx_ratio=np.abs(ratio),delta_z_tx_real=dz.real,delta_z_tx_imag=dz.imag,
                phase_valid=phase_valid & good[:,None])

def nearest_indices(source, queries, tolerance_ns):
    """Missing/remote values yield -1. No interpolation over dropouts."""
    source=np.asarray(source,np.int64);queries=np.asarray(queries,np.int64)
    if not len(source):return np.full(len(queries),-1,np.int64)
    if np.any(np.diff(source)<=0):raise ValueError('Non-monotonic source timeline')
    right=np.searchsorted(source,queries).clip(0,len(source)-1)
    left=(right-1).clip(0,len(source)-1)
    choose=np.where(np.abs(source[left]-queries)<=np.abs(source[right]-queries),left,right)
    return np.where(np.abs(source[choose]-queries)<=tolerance_ns,choose,-1)

def write_analysis(path, meta):
    path=Path(path);frames=read_rows(path/'camera.jsonl');signals=read_rows(path/'iq.jsonl')
    packets=read_rows(path/'audio-timing.jsonl')
    start=meta['start_monotonic_ns']
    ft=np.array([r['host_ns'] for r in frames],np.int64)
    st=np.array([r['host_ns'] for r in signals],np.int64)
    iq=np.array([r['iq'] for r in signals],float).reshape(-1,8)
    values=features(iq,meta.get('display',{}).get('phase_baseline'))
    valid=np.array([r['valid'] for r in signals],bool)
    signal_time_valid=np.array([r.get('timestamp_valid',False) for r in signals],bool)
    join=nearest_indices(st,ft,15_000_000)
    distance=np.array([r['measurement'].get('distance_mm',np.nan) for r in frames])
    filtered=filter_frames(frames,meta['settings'])
    geometry_valid=np.array([r['measurement'].get('valid',False) for r in frames],bool)
    xyz=np.array([r['measurement'].get('point_xyz_m',[np.nan]*3) for r in frames]).reshape(-1,3)
    xy=np.array([[r['measurement'].get('x',-1),r['measurement'].get('y',-1)] for r in frames],np.int32).reshape(-1,2)
    camera_time_valid=np.array([r.get('depth_clock',{}).get('timestamp_valid',False) for r in frames],bool)
    matched=join>=0
    aligned_valid=np.zeros(len(ft),bool);aligned_valid[matched]=valid[join[matched]] & signal_time_valid[join[matched]] & camera_time_valid[matched]
    delta_ms=np.full(len(ft),np.nan);delta_ms[matched]=(st[join[matched]]-ft[matched])/1e6
    with h5py.File(path/'analysis.h5','w') as h:
        h.attrs['schema']='ferrodsp-analysis-v2'
        h.attrs['time_origin']='session.json start_monotonic_ns; times are seconds from requested record start'
        h.attrs['channels']=json.dumps(['RX0','RX1','TX_coil','TX_amplifier'])
        h.attrs['phase_reference']='TX_coil; wrapped degrees [-180,180]; NaN when phase is undefined'
        h.attrs['alignment']='Nearest I/Q centre within 15 ms, no interpolation; source validity is separate from geometry validity'
        h.attrs['physical_sync_calibrated']=False
        h.attrs['item_json']=json.dumps(meta.get('item',{}),ensure_ascii=False)
        h.attrs['baseline_json']=json.dumps(meta.get('display',{}).get('phase_baseline'))
        h.attrs['distance_filter_json']=json.dumps(filter_metadata(meta['settings']))
        s=h.create_group('signals');f=h.create_group('frames');a=h.create_group('aligned_frames')
        for name,value in dict(host_ns=st,time_s=(st-start)/1e9,iq=iq,valid=valid,timestamp_valid=signal_time_valid,
                               stream_sample=[r['sample'] for r in signals],device_sample=[r.get('device_sample',np.nan) for r in signals],**values).items():s.create_dataset(name,data=value)
        for name,value in dict(host_ns=ft,time_s=(ft-start)/1e9,source_frame_index=np.arange(len(ft)),
                               distance_mm=distance,geometry_valid=geometry_valid,point_xyz_m=xyz,point_pixel_xy=xy,
                               distance_filtered_mm=np.array([r['filtered_mm'] for r in filtered],float),
                               distance_spike_corrected=[r['corrected'] for r in filtered],
                               timestamp_valid=camera_time_valid,
                               color_minus_depth_ms=[(r.get('color_host_ns',r['host_ns'])-r['host_ns'])/1e6 for r in frames]).items():f.create_dataset(name,data=value)
        for name,value in dict(signal_index=join,signal_minus_frame_ms=delta_ms,signal_valid=aligned_valid,
                               complete_observation=aligned_valid & geometry_valid).items():a.create_dataset(name,data=value)
        for name,array in values.items():
            dest=np.full((len(ft),4),np.nan)
            dest[matched]=array[join[matched]]
            a.create_dataset(name,data=dest)
        # A reciprocal map supports signal-rate analysis without copying video.
        s.create_dataset('nearest_frame_index',data=nearest_indices(ft,st,round(0.6/meta['settings']['fps']*1e9)))
        audio=h.create_group('audio_packets')
        for key in ['wav_sample_start','stream_sample_start','device_sample_start','frames','sample_period_ns',
                    'host_first_sample_estimate_ns','device_gap_samples','wasapi_flags','timestamp_valid']:
            audio.create_dataset(key,data=[p.get(key,False if key=='timestamp_valid' else 0) for p in packets])
        audio.attrs['source_file']='spdif.wav, packed PCM24 stereo 96000 Hz'
        audio.attrs['padding_ms']=meta.get('raw_audio_padding_ms',0)
        # Exact PCM support of each centred Hann window, including fractional centre.
        centres=np.array([r['sample'] for r in signals])
        wav_centres=np.full(len(centres),np.nan)
        if packets:
            begins=np.array([p.get('stream_sample_start',0) for p in packets])
            pi=np.searchsorted(begins,centres,side='right')-1
            for i,j in enumerate(pi):
                if j>=0 and centres[i]<begins[j]+packets[j]['frames']:
                    wav_centres[i]=packets[j]['wav_sample_start']+centres[i]-begins[j]
        s.create_dataset('wav_center_sample',data=wav_centres)
        s.attrs['raw_window_samples']=3840
        s.attrs['raw_window_start_formula']='wav_center_sample - (3840-1)/2; windows crossing discontinuity remain invalid'
    return dict(frames=len(ft),signals=len(st),valid_signal_fraction=float(valid.mean()) if len(st) else 0,
                aligned_frames=int(aligned_valid.sum()),complete_observations=int((aligned_valid&geometry_valid).sum()),
                max_pair_difference_ms=float(np.max(np.abs(delta_ms[matched]))) if matched.any() else None,
                distance_spikes_corrected=sum(r['corrected'] for r in filtered),
                physical_sync_calibrated=False)
