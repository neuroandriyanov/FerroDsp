"""Geometry and streaming decoding. No device I/O or UI dependencies."""
import bootstrap
import collections
import json
from pathlib import Path
import cv2
import numpy as np

CALIBRATION = Path(__file__).parent / 'resources/transport-calibration.json'
FREQUENCIES = np.array([1500., 3700., 5900., 8100., 10300.])
CHANNELS = ['RX0', 'RX1', 'TX катушка', 'TX усилитель']

def unpack24(payload):
    b = np.frombuffer(payload, np.uint8).reshape(-1, 3).astype(np.int32)
    x = b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16
    return (((x ^ 0x800000) - 0x800000) / 8388608.).reshape(-1, 2)

class LiveDecoder:
    """100 Hz I/Q, 40 ms Hann; delay 70 ms to flag both sides of timing jumps."""
    def __init__(self, calibration=CALIBRATION, fs=96000):
        self.cal = json.loads(Path(calibration).read_text(encoding='utf-8-sig'))
        if self.cal['protocol'] != 'ferrodsp-am-iq-v1' or fs != 96000:
            raise ValueError('Expected ferrodsp-am-iq-v1 / 96000 Hz')
        slope=np.asarray(self.cal['slope']);intercept=np.asarray(self.cal['intercept'])
        if slope.shape!=(8,) or intercept.shape!=(8,) or not np.isfinite([slope,intercept]).all() or np.any(slope<=0):
            raise ValueError('Invalid optical transport calibration')
        self.fs, self.n, self.hop = fs, 3840, 960
        w = np.hanning(self.n)
        self.kernel = (np.exp(-2j*np.pi*np.arange(self.n)[:,None]*FREQUENCIES/fs)*w[:,None]*(2/w.sum())).T.copy()
        self.data = np.empty((0,2))
        self.offset = 0
        self.previous = None
        self.steps = collections.deque(maxlen=201)
        self.pending = collections.deque()
        self.guard_until = -1
        self.pilot_history = collections.deque(maxlen=100)
        self.last_bad_end = -1

    def feed(self, x, bad=False):
        if bad:
            self.last_bad_end = self.offset + len(self.data) + len(x) + self.n
            for row in self.pending:
                row['valid'] = False
        self.data = np.concatenate([self.data, x])
        output = []
        while len(self.data) >= self.n:
            block = self.data[:self.n]
            z = self.kernel @ block
            pilot = np.abs(z[4])
            ratio = (np.abs(z[:4]) / np.maximum(pilot[None,:], 1e-10)).reshape(8)
            iq = (ratio-self.cal['intercept']) / self.cal['slope']
            jump = False
            if self.previous is not None:
                dp = np.angle(z[4]*self.previous.conj()*np.exp(-2j*np.pi*10300*self.hop/self.fs))
                nominal = np.median(np.array(self.steps),axis=0) if self.steps else np.zeros(2)
                jump = bool(np.any(np.abs(np.angle(np.exp(1j*(dp-nominal)))) > .025))
                if not jump:
                    self.steps.append(dp)
            self.previous = z[4]
            if jump:
                self.guard_until = self.offset + 7*self.hop
                for row in self.pending:
                    row['valid'] = False
                    row['timing_guard'] = True
            # Observe all non-silent pilot levels, not just accepted levels: otherwise
            # the capture startup ramp can lock the reference to the wrong amplitude.
            nominal_pilot = np.median(np.array(self.pilot_history),axis=0) if self.pilot_history else np.array([.05,.05])
            pilot_ok = bool(np.all(pilot > .001) and np.all(pilot > nominal_pilot*.8) and np.all(pilot < nominal_pilot*1.2))
            if np.all(pilot > .001) and np.all(pilot < .9):
                self.pilot_history.append(pilot)
            guarded = self.offset <= self.guard_until
            valid = bool(pilot_ok and not guarded and self.offset >= .5*self.fs and
                         self.offset > self.last_bad_end and np.max(np.abs(block)) < .98 and np.all(np.abs(iq) <= .56))
            self.pending.append(dict(sample=float(self.offset+(self.n-1)/2), iq=iq.tolist(),
                                     valid=valid, pilot=pilot.tolist(), timing_jump=jump, timing_guard=guarded,
                                     pilot_ok=pilot_ok, pcm_peak=float(np.max(np.abs(block))),
                                     callback_guard=self.offset <= self.last_bad_end))
            if len(self.pending) > 7:
                output.append(self.pending.popleft())
            self.offset += self.hop
            self.data = self.data[self.hop:]
        return output

def fit_plane(points):
    p = np.asarray(points, float)
    if len(p) < 3 or not np.isfinite(p).all():
        raise ValueError('Нужны минимум три точки с достоверной глубиной')
    center = p.mean(axis=0)
    _, s, vh = np.linalg.svd(p-center)
    if s[1] < .015:
        raise ValueError('Точки слишком близки или лежат на одной линии; разнесите их по катушке')
    normal = vh[-1]
    if normal[2] < 0:
        normal = -normal
    if normal[2] < .5:
        raise ValueError('Плоскость слишком наклонена к камере; проверьте выбранные точки')
    offset = float(center @ normal)
    rms = float(np.sqrt(np.mean((p@normal-offset)**2)))
    if rms > .008:
        raise ValueError('Точки не образуют плоскость: ошибка больше 8 мм')
    return dict(normal=normal.tolist(), offset_m=offset, rms_mm=rms*1000,
                points_m=p.tolist(), method='selected_depth_surface_points')

def nearest_point(depth, xyz, background, plane, cfg):
    """Minimum visible foreground-to-plane gap, after rejecting isolated pixels.

    Depth is optical Z; xyz uses SDK deprojection. Invisible top surfaces and
    object thickness cannot be inferred from a camera below the object.
    """
    if plane is None:
        return {'valid':False, 'reason':'Задайте плоскость катушки'}
    if background is None:
        return {'valid':False, 'reason':'Сохраните пустой фон'}
    if background.shape != depth.shape:
        return {'valid':False, 'reason':'Размер фона не совпадает'}
    gap = (plane['offset_m'] - np.einsum('ijk,k->ij',xyz,np.asarray(plane['normal'])))*1000
    x,y,w,h = cfg['roi']
    roi = np.zeros(depth.shape,bool)
    roi[y:y+h,x:x+w] = True
    valid = (roi & (depth >= cfg['min_depth_m']) & (depth <= cfg['max_depth_m']) &
             (background > 0) & ((background-depth)*1000 > cfg['foreground_mm']) &
             (gap >= cfg['minimum_gap_mm']) & (gap <= cfg['maximum_gap_mm']))
    # Require a complete 3x3 neighborhood. Zero-depth holes never become measurements.
    supported = cv2.erode(valid.astype(np.uint8),np.ones((3,3),np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(supported,8)
    accepted = np.zeros_like(supported,bool)
    for label in range(1,count):
        if stats[label,cv2.CC_STAT_AREA] >= cfg['min_area_px']:
            accepted |= labels == label
    if not accepted.any():
        return {'valid':False, 'reason':'Нет видимого предмета в области'}
    local_gap = cv2.medianBlur(gap.astype(np.float32),3)
    masked = np.where(accepted,local_gap,np.inf)
    py,px = np.unravel_index(np.argmin(masked),masked.shape)
    return dict(valid=True, x=int(px), y=int(py), distance_mm=float(local_gap[py,px]),
                camera_z_mm=float(depth[py,px]*1000), support_pixels=int(accepted.sum()),
                point_xyz_m=xyz[py,px].astype(float).tolist(),
                reason='Видимая поверхность → плоскость катушки')

COLORMAPS = {'Turbo':cv2.COLORMAP_TURBO, 'Jet':cv2.COLORMAP_JET,
             'Viridis':cv2.COLORMAP_VIRIDIS, 'Серый':None}

def depth_image(depth, cfg):
    v = np.clip((depth-cfg['color_min_m']) / max(.001,cfg['color_max_m']-cfg['color_min_m']),0,1)
    gray = np.uint8((1-v)*255)
    cm = COLORMAPS[cfg['colormap']]
    color = cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR) if cm is None else cv2.applyColorMap(gray,cm)
    color[depth <= 0] = 0
    return color

def annotate(image, measurement, cfg, points=()):
    out = image.copy()
    x,y,w,h = cfg['roi']
    cv2.rectangle(out,(x,y),(x+w-1,y+h-1),(140,150,150),1)
    if measurement.get('valid'):
        x,y = measurement['x'],measurement['y']
        # Exactly 30 pixels in each direction, in the original 640x480 frame.
        cv2.line(out,(x-15,y),(x+14,y),(0,255,255),1)
        cv2.line(out,(x,y-15),(x,y+14),(0,255,255),1)
    # Absence of valid depth is labelled in the localized UI/video header.
    for i,(x,y) in enumerate(points):
        cv2.circle(out,(int(x),int(y)),5,(255,180,0),2)
        cv2.putText(out,str(i+1),(int(x)+7,int(y)),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,180,0),1)
    return out

def preview(color, depth, measurement, cfg, points=()):
    d = depth_image(depth,cfg)
    if cfg['view'] == 'color':
        frame = np.uint8(color.astype(float)*cfg['alpha_color'])
    elif cfg['view'] == 'depth':
        frame = np.uint8(d.astype(float)*cfg['alpha_depth'])
    else:
        # True color-over-depth alpha compositing on black, not additive saturation.
        a,b = cfg['alpha_color'],cfg['alpha_depth']
        frame = np.uint8(np.clip(color*a+d*b*(1-a),0,255))
    return annotate(frame,measurement,cfg,points), annotate(d,measurement,cfg,points)
