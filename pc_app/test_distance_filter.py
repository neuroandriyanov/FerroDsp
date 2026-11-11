import bootstrap
import unittest
import numpy as np
from distance_filter import DistanceFilter,filter_frames

class DistanceFilterTests(unittest.TestCase):
    def frames(self,values):
        return [dict(host_ns=i*33_333_333,measurement=dict(valid=value is not None,distance_mm=value)) for i,value in enumerate(values)]

    def test_impulse_removed_without_time_shift(self):
        frames=self.frames([200,200,201,600,200,199,200])
        out=filter_frames(frames,{'fps':30})
        self.assertEqual(out[3]['filtered_mm'],200)
        self.assertTrue(out[3]['corrected']);self.assertEqual(out[3]['raw_mm'],600)
        self.assertEqual([p['host_ns'] for p in out],[p['host_ns'] for p in frames])
        self.assertEqual(sum(p['corrected'] for p in out),1)

    def test_sustained_step_and_ramp_preserved(self):
        for values in [[200]*5+[450]*5,list(range(100,500,20))]:
            out=filter_frames(self.frames(values),{'fps':30})
            self.assertEqual([p['filtered_mm'] for p in out],values)
            self.assertFalse(any(p['corrected'] for p in out))

    def test_missing_depth_and_camera_gap_not_filled(self):
        frames=self.frames([200,200,600,None,600,200,200])
        out=filter_frames(frames,{'fps':30})
        self.assertIsNone(out[3]['filtered_mm']);self.assertEqual(out[2]['filtered_mm'],600)
        frames=self.frames([200,200,600,200,200]);frames[3]['host_ns']+=1_000_000_000;frames[4]['host_ns']+=1_000_000_000
        out=filter_frames(frames,{'fps':30})
        self.assertFalse(out[2]['corrected'])

    def test_streaming_matches_file_and_waits_two_frames(self):
        frames=self.frames([200,201,199,600,200,205,210,200,None,180])
        filt=DistanceFilter({'fps':30});out=[]
        for i,p in enumerate(frames):
            emitted=filt.push(p['host_ns'],p['measurement']);out.extend(emitted)
            if i<2:self.assertFalse(emitted)
            else:self.assertEqual(emitted[0]['host_ns'],frames[i-2]['host_ns'])
        out.extend(filt.flush())
        self.assertEqual(out,filter_frames(frames,{'fps':30}))
        self.assertEqual(filt.flush(),[])
        self.assertEqual(filter_frames([],{'fps':30}),[])

if __name__=='__main__':unittest.main(verbosity=2)
