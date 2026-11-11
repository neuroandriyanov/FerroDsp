import bootstrap
import json
from pathlib import Path
import pyrealsense2 as rs
import sounddevice as sd

def inventory():
    cameras = []
    for device in rs.context().query_devices():
        item = {'name': device.get_info(rs.camera_info.name),
                'serial': device.get_info(rs.camera_info.serial_number),
                'firmware': device.get_info(rs.camera_info.firmware_version), 'sensors': []}
        for sensor in device.query_sensors():
            profiles = []
            for p in sensor.get_stream_profiles():
                if p.is_video_stream_profile():
                    v = p.as_video_stream_profile()
                    if v.width() == 640 and v.height() == 480:
                        profiles.append({'stream': str(p.stream_type()), 'format': str(p.format()), 'fps': p.fps()})
            item['sensors'].append({'name':sensor.get_info(rs.camera_info.name), 'profiles_640x480':profiles})
        cameras.append(item)
    hosts = sd.query_hostapis()
    audio = [dict(d, index=i, hostapi_name=hosts[d['hostapi']]['name'])
             for i,d in enumerate(sd.query_devices()) if d['max_input_channels'] >= 2 and 'spdif' in d['name'].lower()]
    return {'cameras':cameras, 'spdif':audio}

if __name__ == '__main__':
    result = inventory()
    dest = bootstrap.ROOT / 'tmp' / 'research-device-inventory.json'
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
