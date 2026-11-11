"""Explicit clock mapping; raw observations are retained for later recalibration."""
import collections
import ctypes
import time
import numpy as np

class AudioClockMap:
    """Local robust affine map from IAudioClock samples to host QPC.

    USB position reads are quantized. Fit a moving five-second window rather than
    treating a burst of buffer reads as a burst of acquisition. Never use a
    single initial anchor for an entire recording (independent-clock drift).
    """
    def __init__(self):
        self.points=collections.deque(maxlen=2500)
        self.model=None;self.last_fit_ns=0;self.last_position=None;self.previous=None

    def update(self, packet, frequency):
        sample=packet['clock_position']*96000/frequency
        qpc=packet['clock_qpc_100ns']*100
        if packet['clock_status']==0 and sample!=self.last_position:
            self.points.append((sample,qpc));self.last_position=sample
        while len(self.points)>2 and qpc-self.points[0][1]>5e9:self.points.popleft()
        if len(self.points)>=20 and qpc-self.last_fit_ns>=50_000_000:
            xy=np.array(self.points); origin=xy[len(xy)//2]
            x=(xy[:,0]-origin[0])/96000;y=(xy[:,1]-origin[1])/1e9
            mask=np.ones(len(x),bool)
            for _ in range(3):
                rate,offset=np.polyfit(x[mask],y[mask],1)
                residual=y-(x*rate+offset)
                mad=np.median(np.abs(residual[mask]-np.median(residual[mask])))
                mask=np.abs(residual-np.median(residual[mask]))<max(.002,4*1.4826*mad)
            span=float(np.ptp(x))
            if .995<rate<1.005:
                self.model=dict(sample=float(origin[0]),host_ns=int(origin[1]+offset*1e9),
                    ns_per_sample=float(rate*1e9/96000),span_s=span,
                    residual_p95_ms=float(np.percentile(np.abs(residual[mask]),95)*1000),
                    drift_ppm=float((1/rate-1)*1e6),observations=int(mask.sum()))
            self.last_fit_ns=qpc
        model=self.model
        packet['clock_fit']=model
        if model:
            fitted=round(model['host_ns']+(packet['device_sample_start']-model['sample'])*model['ns_per_sample'])
            mapped=fitted
            if self.previous and packet['device_sample_start']>self.previous[0]:
                step=(packet['device_sample_start']-self.previous[0])*model['ns_per_sample']
                predicted=self.previous[1]+step
                # Slew, never jump the timeline when the regression updates.
                mapped=round(predicted+np.clip(fitted-predicted,-step*.02,step*.02))
            packet['host_first_sample_estimate_ns']=mapped
            packet['sample_period_ns']=model['ns_per_sample']
            packet['clock_fit_correction_ms']=(mapped-fitted)/1e6
            packet['timestamp_valid']=bool(packet['timestamp_valid'] and model['span_s']>=1 and model['residual_p95_ms']<6 and abs(mapped-fitted)<5e6)
        else:
            packet['sample_period_ns']=1e9/96000;packet['timestamp_valid']=False
            if self.previous and packet['device_sample_start']>self.previous[0]:
                packet['host_first_sample_estimate_ns']=round(self.previous[1]+(packet['device_sample_start']-self.previous[0])*1e9/96000)
        if packet['host_first_sample_estimate_ns']>packet['host_arrival_ns']+1_000_000:
            packet['timestamp_valid']=False
        packet['timestamp_source']='wasapi_audio_clock_robust_affine'
        self.previous=(packet['device_sample_start'],packet['host_first_sample_estimate_ns'])
        return packet

class SampleTimeline:
    def __init__(self):self.packets=collections.deque(maxlen=3000)
    def append(self, p):
        self.packets.append({k:p[k] for k in ['stream_sample_start','frames','host_first_sample_estimate_ns','sample_period_ns','timestamp_valid','device_sample_start']})
    def locate(self, sample):
        for p in reversed(self.packets):
            offset=sample-p['stream_sample_start']
            if 0<=offset<p['frames']:
                return dict(host_ns=round(p['host_first_sample_estimate_ns']+offset*p['sample_period_ns']),
                    timestamp_valid=p['timestamp_valid'],device_sample=p['device_sample_start']+offset)
        return dict(host_ns=0,timestamp_valid=False,device_sample=None)

def camera_stamp(frame, rs, arrival_ns):
    """Prefer exposure metadata; never label system-time arrival as exposure."""
    before=time.perf_counter_ns()
    filetime=ctypes.c_uint64()
    ctypes.windll.kernel32.GetSystemTimePreciseAsFileTime(ctypes.byref(filetime))
    wall=(filetime.value-116444736000000000)*100
    after=time.perf_counter_ns()
    offset=(before+after)//2-wall
    metadata={}
    for name in ['sensor_timestamp','frame_timestamp','backend_timestamp','time_of_arrival','actual_exposure','frame_counter']:
        key=getattr(rs.frame_metadata_value,name,None)
        if key is not None and frame.supports_frame_metadata(key):
            metadata[name]=int(frame.get_frame_metadata(key))
    stamp=frame.get_timestamp();domain=str(frame.get_frame_timestamp_domain())
    if domain.endswith('global_time'):
        host=round(stamp*1e6)+offset;source='global_time_frame'
        if 'sensor_timestamp' in metadata and 'frame_timestamp' in metadata:
            # Device timestamp counters wrap at 2**32 microseconds.
            delta=(metadata['sensor_timestamp']-metadata['frame_timestamp']+2**31)%2**32-2**31
            if abs(delta)<1_000_000:host+=delta*1000;source='global_time_middle_exposure'
    elif domain.endswith('system_time'):
        if 'backend_timestamp' in metadata:
            host=metadata['backend_timestamp']*1_000_000+offset;source='backend_transfer_not_exposure'
        else:host=round(stamp*1e6)+offset;source='system_time_arrival_not_exposure'
    else:host=arrival_ns;source='host_arrival_no_clock_mapping'
    valid=bool(0<=arrival_ns-host<2_000_000_000)
    if not valid:host=arrival_ns;source='host_arrival_invalid_native_time'
    return dict(host_ns=host,native_timestamp_ms=stamp,timestamp_domain=domain,metadata=metadata,
                timestamp_source=source,timestamp_valid=valid,exposure_time_known=source.endswith('middle_exposure'),
                wall_to_monotonic_ns=offset,clock_pair_uncertainty_ns=(after-before)//2)
