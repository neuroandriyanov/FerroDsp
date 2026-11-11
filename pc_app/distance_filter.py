"""Centred distance outlier filter; timestamps and raw measurements stay intact."""
import bootstrap
import collections
import numpy as np

def filter_metadata(config):
    return dict(method='centred_hampel_v1',window_frames=5,
                minimum_deviation_mm=float(config.get('distance_spike_mm',15.)),mad_factor=3.,
                lookahead_frames=2,max_gap_seconds=1.8/config['fps'],
                timestamp='original centre frame; no time-axis shift',
                boundaries='shortened window; never fill invalid depth or cross a gap')

class DistanceFilter:
    def __init__(self,config):
        self.spec=filter_metadata(config);self.points=collections.deque(maxlen=5)
        self.sequence=-1;self.emitted=-1

    def _result(self,sequence):
        points=list(self.points);i=next(j for j,p in enumerate(points) if p['sequence']==sequence)
        p=points[i];result={k:v for k,v in p.items() if k!='sequence'}
        result.update(filtered_mm=p['raw_mm'],corrected=False,context_frames=1)
        if not p['valid']:return result
        left=right=i;gap=self.spec['max_gap_seconds']*1e9
        while left>max(0,i-2) and points[left-1]['valid'] and 0<points[left]['host_ns']-points[left-1]['host_ns']<=gap:left-=1
        while right<min(len(points)-1,i+2) and points[right+1]['valid'] and 0<points[right+1]['host_ns']-points[right]['host_ns']<=gap:right+=1
        result['context_frames']=right-left+1
        # Require a neighbour on each side: do not extrapolate an endpoint.
        if left==i or right==i:return result
        values=np.array([v['raw_mm'] for v in points[left:right+1]])
        median=float(np.median(values));mad=float(np.median(np.abs(values-median)))
        threshold=max(self.spec['minimum_deviation_mm'],3*1.4826*mad)
        if abs(p['raw_mm']-median)>threshold:
            result['filtered_mm']=median;result['corrected']=True
        return result

    def push(self,host_ns,measurement):
        value=measurement.get('distance_mm')
        valid=bool(measurement.get('valid') and value is not None and np.isfinite(value))
        self.sequence+=1
        self.points.append(dict(sequence=self.sequence,host_ns=int(host_ns),raw_mm=float(value) if valid else None,valid=valid))
        if self.sequence<2:return []
        self.emitted=self.sequence-2
        return [self._result(self.emitted)]

    def flush(self):
        rows=[self._result(i) for i in range(self.emitted+1,self.sequence+1)]
        self.emitted=self.sequence
        return rows

def filter_frames(frames,config):
    filt=DistanceFilter(config);rows=[]
    for frame in frames:rows.extend(filt.push(frame['host_ns'],frame['measurement']))
    return rows+filt.flush()
