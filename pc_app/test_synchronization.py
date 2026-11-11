import bootstrap
import unittest
import numpy as np
from analysis_data import features,nearest_indices
from timing import AudioClockMap,SampleTimeline

class SynchronizationTests(unittest.TestCase):
    def test_phase_wrap_reference_and_baseline(self):
        angles=np.radians([[-179,20,40,-90]])
        z=np.exp(1j*angles)*np.array([.1,.2,.3,.4])
        iq=np.empty((1,8));iq[:,0::2]=z.real;iq[:,1::2]=z.imag
        base=np.exp(1j*np.radians([139,-20,0,-130]))
        f=features(iq,np.column_stack([base.real,base.imag]))
        np.testing.assert_allclose(f['amplitude'],[[.1,.2,.3,.4]])
        np.testing.assert_allclose(f['phase_tx_deg'],[[141,-20,0,-130]],atol=1e-10)
        np.testing.assert_allclose(f['delta_phase_tx_deg'],[[2,0,0,0]],atol=1e-10)
        f=features(np.zeros((1,8)))
        self.assertTrue(np.isnan(f['phase_tx_deg']).all());self.assertFalse(f['phase_valid'].any())

    def test_join_does_not_bridge_gap_or_extrapolate(self):
        src=np.array([100,110,120,200])*1_000_000
        queries=np.array([50,109,131,180,201])*1_000_000
        np.testing.assert_array_equal(nearest_indices(src,queries,15_000_000),[-1,1,2,-1,3])
        with self.assertRaises(ValueError):nearest_indices([2,1],[1],1)

    def test_clock_drift_quantization_and_bursts(self):
        m=AudioClockMap();rows=[];rng=np.random.default_rng(8761)
        origin=3_000_000_000_000;rate=1e9/(96000*1.00015)
        for i in range(4000):
            pos=i*288
            qpc=round((origin+pos*rate+rng.uniform(-4e6,4e6))/100)
            p=dict(device_sample_start=pos,clock_position=pos,clock_qpc_100ns=qpc,clock_status=0,
                   timestamp_valid=True,host_arrival_ns=origin+round(pos*rate)+20_000_000,
                   host_first_sample_estimate_ns=qpc*100)
            m.update(p,96000);rows.append(p)
        times=np.array([r['host_first_sample_estimate_ns'] for r in rows])
        self.assertTrue(np.all(np.diff(times)>0))
        error=times[-1000:]-(origin+np.arange(3000,4000)*288*rate)
        self.assertLess(np.max(np.abs(error)),1e6)
        self.assertTrue(all(r['timestamp_valid'] for r in rows[-1000:]))

    def test_sample_mapping_tracks_packet_discontinuity(self):
        timeline=SampleTimeline()
        timeline.append(dict(stream_sample_start=0,frames=960,host_first_sample_estimate_ns=100_000_000,
                             sample_period_ns=1e9/96000,timestamp_valid=True,device_sample_start=0))
        timeline.append(dict(stream_sample_start=960,frames=960,host_first_sample_estimate_ns=200_000_000,
                             sample_period_ns=1e9/96000,timestamp_valid=False,device_sample_start=9600))
        self.assertEqual(timeline.locate(1440)['host_ns'],205_000_000)
        self.assertFalse(timeline.locate(1440)['timestamp_valid'])
        self.assertEqual(timeline.locate(1440)['device_sample'],10080)

if __name__=='__main__':unittest.main(verbosity=2)
