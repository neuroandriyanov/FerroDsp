import bootstrap
import json
import tempfile
import unittest
import wave
from pathlib import Path
import cv2
import h5py
import numpy as np
from processing import LiveDecoder,FREQUENCIES,nearest_point,fit_plane,unpack24,preview
from engine import DEFAULTS
from recording import Recorder

class ProcessingTests(unittest.TestCase):
    def signal(self,seconds=2,jump=None):
        dec=LiveDecoder();reference=np.array([.137,-.257,.071,.318,-.29,.203,.016,-.083])
        a=(np.array(dec.cal['intercept'])+np.array(dec.cal['slope'])*reference).reshape(4,2)*.05
        t=np.arange(int(seconds*96000))/96000
        if jump is not None:t[t>=jump]+=1/96000
        x=np.sin(2*np.pi*t[:,None]*FREQUENCIES[:4])@a + .05*np.sin(2*np.pi*10300*t[:,None])
        return dec,reference,x
    def test_decoder_independent_values_and_delayed_guard(self):
        dec,ref,x=self.signal(3,jump=1.7);rows=[]
        for start in range(0,len(x),2053):rows+=dec.feed(x[start:start+2053])
        good=[r for r in rows if r['valid']]
        self.assertGreater(len(good),180)
        self.assertLess(np.max(np.abs(np.array([r['iq'] for r in good])-ref)),1e-5)
        guarded=[r for r in rows if abs(r['sample']/96000-1.7)<.06]
        self.assertTrue(guarded);self.assertTrue(all(not r['valid'] for r in guarded))
    def test_silence_invalid(self):
        d=LiveDecoder();rows=d.feed(np.zeros((192000,2)))
        self.assertFalse(any(r['valid'] for r in rows))
    def test_pilot_recovers_after_startup_gain_ramp(self):
        dec,_,x=self.signal(3)
        x[:24000]*=.81
        rows=dec.feed(x)
        self.assertTrue(all(r['valid'] for r in rows if r['sample']/96000>2))
    def test_pcm24_signed(self):
        ints=np.array([-8388608,-1,0,1,8388607,123456],np.int32)
        bytes_=np.column_stack([ints&255,(ints>>8)&255,(ints>>16)&255]).astype(np.uint8).tobytes()
        np.testing.assert_array_equal(unpack24(bytes_).reshape(-1)*8388608,ints)
    def test_plane_and_visible_foreground(self):
        plane=fit_plane([[-.1,-.1,.65],[.1,-.1,.65],[-.1,.1,.65],[.1,.1,.65]])
        shape=(60,80);bg=np.ones(shape,np.float32)*.65;depth=bg.copy()
        depth[20:40,30:50]=.45
        xyz=np.zeros((*shape,3));xyz[:,:,2]=depth
        cfg=dict(DEFAULTS,roi=[0,0,80,60])
        result=nearest_point(depth,xyz,bg,plane,cfg)
        self.assertTrue(result['valid']);self.assertAlmostEqual(result['distance_mm'],200,places=3)
        depth[5,5]=.64;xyz[:,:,2]=depth
        self.assertGreater(nearest_point(depth,xyz,bg,plane,cfg)['distance_mm'],190)
        self.assertFalse(nearest_point(bg,np.dstack([bg*0,bg*0,bg]),bg,plane,cfg)['valid'])
        self.assertFalse(nearest_point(depth,xyz,None,plane,cfg)['valid'])
        with self.assertRaises(ValueError):fit_plane([[0,0,.65],[.1,0,.65],[.2,0,.65]])
    def test_zero_depth_excluded_and_overlay(self):
        depth=np.zeros((480,640),np.float32);xyz=np.zeros((480,640,3))
        plane=fit_plane([[-.1,-.1,.65],[.1,-.1,.65],[-.1,.1,.65]])
        m=nearest_point(depth,xyz,np.ones_like(depth),plane,DEFAULTS)
        self.assertFalse(m['valid'])
        color=np.full((480,640,3),100,np.uint8)
        cfg=dict(DEFAULTS,alpha_color=1.)
        frame,_=preview(color,depth,m,cfg)
        np.testing.assert_array_equal(frame[200,200],color[200,200])

class RecordingTests(unittest.TestCase):
    def test_roundtrip_depth_audio_video_and_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=dict(DEFAULTS,minimum_disk_gb=.2)
            raw_depth=np.full((480,640),451,np.uint16)
            recorder=Recorder(Path(folder),{'item':{'name':'synthetic-test'}},raw_depth*.001,cfg)
            for i in range(4):
                recorder.submit('camera',dict(depth_raw=raw_depth,color=np.zeros((480,640,3),np.uint8),depth_video=np.zeros((480,640,3),np.uint8),
                                             host_ns=recorder.start_ns+i*33333333,depth_scale_m=.001,
                                             depth_clock={'timestamp_valid':True},
                                             measurement=dict(valid=True,x=320,y=240,distance_mm=200-i*10,point_xyz_m=[0,0,.45+i*.01])))
            for i in range(14):
                recorder.submit('iq',dict(host_ns=recorder.start_ns+i*10_000_000,sample=i*960,
                                         iq=[.1,.2,.2,.1,.3,.2,.2,.3],valid=i not in [3,4],timestamp_valid=True))
            recorder.submit('audio',dict(payload=bytes(9600*6),frames=9600,host_first_sample_estimate_ns=recorder.start_ns))
            recorder.stop_ns=recorder.start_ns+133333334
            result=recorder.stop()
            self.assertIsNone(result['error'])
            with h5py.File(recorder.path/'camera.h5') as f:
                self.assertEqual(f['depth_z16'].shape,(4,480,640));np.testing.assert_array_equal(f['depth_z16'][1],raw_depth)
            with wave.open(str(recorder.path/'spdif.wav')) as f:
                self.assertEqual(f.getnframes(),9600);self.assertEqual(f.getsampwidth(),3)
            cap=cv2.VideoCapture(str(recorder.path/'demonstration.mp4'))
            self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),5);cap.release()
            with h5py.File(recorder.path/'analysis.h5') as f:
                self.assertEqual(len(f['frames/time_s']),4)
                np.testing.assert_array_equal(f['aligned_frames/complete_observation'][:],[True,False,True,True])
                np.testing.assert_allclose(f['frames/distance_mm'][:],[200,190,180,170])
                self.assertTrue(np.isnan(f['signals/delta_phase_tx_deg'][:]).all())
            self.assertEqual(json.loads((recorder.path/'session.json').read_text(encoding='utf-8'))['status'],'completed')
            self.assertTrue((recorder.path/'manifest.json').exists())

if __name__=='__main__':unittest.main(verbosity=2)
