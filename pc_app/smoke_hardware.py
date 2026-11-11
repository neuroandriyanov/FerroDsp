"""Read-only 12 second device check; does not change DSP or camera options."""
import bootstrap
import json
import time
import cv2
from engine import Engine
from recording import dump

e=Engine()
try:
    e.start()
    for _ in range(120):
        time.sleep(.1)
        if e.camera_error or e.audio_error:break
    state=e.status()
    if e.latest:
        cv2.imwrite(str(bootstrap.ROOT/'tmp/d415-color.png'),e.latest['color'])
        cv2.imwrite(str(bootstrap.ROOT/'tmp/d415-depth.png'),e.latest['depth_video'])
        import numpy as np
        np.savez_compressed(bootstrap.ROOT/'tmp/d415-geometry.npz',depth=e.latest['depth_m'],xyz=e.latest['xyz'])
    dump(bootstrap.ROOT/'tmp/lab-hardware-smoke.json',state)
    print(json.dumps({k:state[k] for k in ['camera_status','audio_status','camera_error','audio_error','camera','valid_iq_fraction','last_iq','camera_drops','audio_flags']},ensure_ascii=False,indent=2))
finally:e.stop()
