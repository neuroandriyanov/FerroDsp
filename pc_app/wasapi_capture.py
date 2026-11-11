"""Unconverted PCM24 capture with per-packet WASAPI device/QPC timestamps.

All COM calls and buffer releases stay on the owning capture thread. No render
endpoint is opened. QPC positions are in 100 ns units, as specified by GetBuffer.
"""
import ctypes as C
import time
import uuid

P = C.c_void_p
U32 = C.c_uint32
U64 = C.c_uint64
I64 = C.c_int64
HRESULT = C.c_int32

class GUID(C.Structure):
    _fields_ = [('bytes', C.c_ubyte * 16)]
    def __init__(self, value):
        super().__init__(); self.bytes[:] = uuid.UUID(value).bytes_le

class PropertyKey(C.Structure):
    _fields_ = [('fmtid', GUID), ('pid', U32)]

class WaveFormat(C.Structure):
    _pack_ = 1
    _fields_ = [('tag', C.c_uint16), ('channels', C.c_uint16), ('rate', U32),
                ('bytes_per_sec', U32), ('block_align', C.c_uint16), ('bits', C.c_uint16),
                ('extra', C.c_uint16), ('valid_bits', C.c_uint16), ('mask', U32), ('subformat', GUID)]

def check(hr):
    if hr < 0: raise OSError(f'WASAPI HRESULT 0x{hr & 0xffffffff:08X}')
    return hr

def call(obj, slot, types=(), *args):
    table = C.cast(obj, C.POINTER(C.POINTER(P))).contents
    fn = C.WINFUNCTYPE(HRESULT, P, *types)(table[slot])
    return check(fn(obj, *args))

def release(obj):
    if obj: call(obj, 2)

class Capture:
    """Exclusive 96 kHz stereo packed 24-bit. No rate/format conversion."""
    def __init__(self, name_contains='sound blaster g3', endpoint_id=None):
        self.name_contains, self.endpoint_id = name_contains.lower(), endpoint_id
        self.enum = P(); self.device = P(); self.client = P(); self.capture = P(); self.clock = P()
        self.initialized = False; self.started = False

    def __enter__(self):
        self.ole = C.OleDLL('ole32')
        self.ole.CoInitializeEx.argtypes = [P, U32]; self.ole.CoInitializeEx.restype = HRESULT
        self.ole.CoCreateInstance.argtypes = [C.POINTER(GUID),P,U32,C.POINTER(GUID),C.POINTER(P)]
        self.ole.CoCreateInstance.restype = HRESULT
        self.ole.CoTaskMemFree.argtypes = [P]
        self.ole.PropVariantClear.argtypes = [P]
        try:
            check(self.ole.CoInitializeEx(None, 0)); self.initialized = True
            clsid = GUID('bcde0395-e52f-467c-8e3d-c4579291692e')
            iid = GUID('a95664d2-9614-4f35-a746-de8db63617e6')
            check(self.ole.CoCreateInstance(C.byref(clsid),None,1,C.byref(iid),C.byref(self.enum)))
            collection = P()
            call(self.enum,3,(C.c_int,U32,C.POINTER(P)),1,1,C.byref(collection))
            candidates = []
            try:
                n=U32(); call(collection,3,(C.POINTER(U32),),C.byref(n))
                for index in range(n.value):
                    dev=P(); store=P(); idptr=P()
                    call(collection,4,(U32,C.POINTER(P)),index,C.byref(dev))
                    try:
                        call(dev,5,(C.POINTER(P),),C.byref(idptr))
                        identity=C.wstring_at(idptr);self.ole.CoTaskMemFree(idptr)
                        call(dev,4,(U32,C.POINTER(P)),0,C.byref(store))
                        key=PropertyKey(GUID('a45c254e-df1c-4efd-8020-67d146a850e0'),14)
                        variant=C.create_string_buffer(24)
                        call(store,5,(C.POINTER(PropertyKey),P),C.byref(key),variant)
                        try:
                            if C.c_uint16.from_buffer(variant).value!=31:continue
                            name=C.wstring_at(P.from_buffer(variant,8).value)
                        finally:self.ole.PropVariantClear(variant)
                        if 'spdif' in name.lower() and (identity==self.endpoint_id if self.endpoint_id else self.name_contains in name.lower()):
                            candidates.append(dict(name=name,endpoint_id=identity))
                    finally:release(store);release(dev)
            finally:release(collection)
            if len(candidates)!=1:raise RuntimeError('Не найден единственный вход S/PDIF; микрофон не используется')
            self.device_info=candidates[0]
            call(self.enum,5,(C.c_wchar_p,C.POINTER(P)),self.device_info['endpoint_id'],C.byref(self.device))
            audio_iid=GUID('1cb9ad4c-dbfa-4c32-b178-c2f568a703b2')
            fmt=WaveFormat(0xfffe,2,96000,576000,6,24,22,24,3,GUID('00000001-0000-0010-8000-00aa00389b71'))
            duration=1_000_000 # 100 ms capacity; packets normally arrive every 10 ms
            for attempt in range(2):
                call(self.device,3,(C.POINTER(GUID),U32,P,C.POINTER(P)),C.byref(audio_iid),1,None,C.byref(self.client))
                call(self.client,7,(C.c_int,P,P),1,C.byref(fmt),None)
                default=I64(); minimum=I64()
                call(self.client,9,(C.POINTER(I64),C.POINTER(I64)),C.byref(default),C.byref(minimum))
                try:
                    call(self.client,3,(C.c_int,U32,I64,I64,P,P),1,0x80000,duration,minimum.value,C.byref(fmt),None)
                    break
                except OSError as exc:
                    if '88890019' not in str(exc) or attempt:raise
                    frames=U32();call(self.client,4,(C.POINTER(U32),),C.byref(frames))
                    duration=round(frames.value/96000*10_000_000)
                    release(self.client);self.client=P()
            frames=U32();latency=I64()
            call(self.client,4,(C.POINTER(U32),),C.byref(frames))
            call(self.client,5,(C.POINTER(I64),),C.byref(latency))
            cap_iid=GUID('c8adbd64-e71e-48a0-a4de-185c395cd317')
            call(self.client,14,(C.POINTER(GUID),C.POINTER(P)),C.byref(cap_iid),C.byref(self.capture))
            clock_iid=GUID('cd63314f-3fba-4a1b-812c-ef96358728e7')
            call(self.client,14,(C.POINTER(GUID),C.POINTER(P)),C.byref(clock_iid),C.byref(self.clock))
            self.frequency=U64();call(self.clock,3,(C.POINTER(U64),),C.byref(self.frequency))
            self.info=dict(device=self.device_info,sample_rate=96000,bits=24,channels=2,exclusive=True,
                           latency=latency.value/1e7,buffer_frames=frames.value,backend='native WASAPI IAudioCaptureClient',
                           clock_frequency=self.frequency.value,
                           timestamp_source='IAudioClock position/QPC mapped to packet device position')
            call(self.client,10);self.started=True
            return self
        except Exception:
            self.__exit__(None,None,None);raise

    def packets(self, stop_event):
        last=time.perf_counter()
        while not stop_event.is_set():
            available=U32()
            call(self.capture,5,(C.POINTER(U32),),C.byref(available))
            if not available.value:
                if time.perf_counter()-last>3:raise RuntimeError('Нет пакетов S/PDIF более 3 секунд')
                stop_event.wait(.002);continue
            data=P();frames=U32();flags=U32();device=U64();qpc=U64()
            call(self.capture,3,(C.POINTER(P),C.POINTER(U32),C.POINTER(U32),C.POINTER(U64),C.POINTER(U64)),
                 C.byref(data),C.byref(frames),C.byref(flags),C.byref(device),C.byref(qpc))
            arrival=time.perf_counter_ns()
            if not frames.value:continue
            position=U64();clock_qpc=U64()
            clock_status=call(self.clock,4,(C.POINTER(U64),C.POINTER(U64)),C.byref(position),C.byref(clock_qpc))
            try:
                payload=bytes(frames.value*6) if flags.value&2 else C.string_at(data,frames.value*6)
            finally:call(self.capture,4,(U32,),frames.value)
            first=clock_qpc.value*100+round((device.value/96000-position.value/self.frequency.value)*1e9)
            timing_valid=bool(clock_status==0 and first>0 and first<=arrival+1_000_000 and arrival-first<2_000_000_000 and not flags.value&4)
            names=[name for bit,name in [(1,'discontinuity'),(2,'silent'),(4,'timestamp_error')] if flags.value&bit]
            if not timing_valid:names.append('untrusted_qpc')
            last=time.perf_counter()
            yield dict(payload=payload,frames=frames.value,host_arrival_ns=arrival,
                       host_first_sample_estimate_ns=first if timing_valid else arrival-round(frames.value/96000*1e9),
                       qpc_100ns=qpc.value,device_sample_start=device.value,wasapi_flags=flags.value,
                       clock_position=position.value,clock_qpc_100ns=clock_qpc.value,clock_status=clock_status,
                       timestamp_valid=timing_valid,timestamp_source='wasapi_audio_clock' if timing_valid else 'arrival_fallback_invalid',
                       status=','.join(names))

    def __exit__(self, *_):
        if self.started:
            try:call(self.client,11)
            except OSError:pass
        for p in [self.clock,self.capture,self.client,self.device,self.enum]:release(p)
        self.clock=self.capture=self.client=self.device=self.enum=P()
        if self.initialized:self.ole.CoUninitialize()
        self.initialized=False;self.started=False

if __name__=='__main__':
    import json, threading
    stop=threading.Event(); rows=[]
    with Capture() as capture:
        print(json.dumps(capture.info,ensure_ascii=False))
        for packet in capture.packets(stop):
            rows.append({k:v for k,v in packet.items() if k!='payload'})
            if len(rows)>=300:break
    print(json.dumps(dict(packets=len(rows),first=rows[:3],last=rows[-1],
                         flagged=sum(bool(r['status']) for r in rows),
                         arrival_delay_ms=[round((r['host_arrival_ns']-r['host_first_sample_estimate_ns'])/1e6,3) for r in rows[::30]]),ensure_ascii=False))
