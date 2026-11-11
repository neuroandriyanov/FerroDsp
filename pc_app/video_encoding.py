"""Portable H.264/AVC MP4 export, with checked encoder and full decode validation."""
import bootstrap
import os
from pathlib import Path
import struct
import subprocess
import cv2
import imageio_ffmpeg

def ffmpeg_run(args, **kwargs):
    return subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),*args],
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,**kwargs)

def mp4_atoms(path):
    atoms=[]
    with Path(path).open('rb') as f:
        total=Path(path).stat().st_size
        while f.tell()<total:
            header=f.read(8)
            if len(header)!=8:raise ValueError('Incomplete MP4 atom')
            size,kind=struct.unpack('>I4s',header);used=8
            if size==1:size=struct.unpack('>Q',f.read(8))[0];used=16
            if size==0:size=total-f.tell()+used
            if size<used or f.tell()+size-used>total:raise ValueError('Invalid MP4 atom size')
            atoms.append(kind.decode('ascii'));f.seek(size-used,1)
    return atoms

def validate_video(path, expected_frames, fps, size):
    # Read codec independently from OpenCV, then decode the ENTIRE stream.
    reader=imageio_ffmpeg.read_frames(str(path))
    try:meta=next(reader)
    finally:reader.close()
    if meta['codec']!='h264':raise RuntimeError(f"Expected H.264, got {meta['codec']}")
    result=ffmpeg_run(['-hide_banner','-v','error','-xerror','-i',str(path),'-map','0:v:0','-f','null','-'],
                      stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=300)
    if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace')[-2000:])
    cap=cv2.VideoCapture(str(path))
    actual=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));actual_fps=cap.get(cv2.CAP_PROP_FPS)
    actual_size=(int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    if actual!=expected_frames or abs(actual_fps-fps)>.001 or actual_size!=tuple(size):
        raise RuntimeError(f'Video mismatch: {actual} frames, {actual_fps} fps, {actual_size}')
    atoms=mp4_atoms(path)
    if atoms.index('moov')>atoms.index('mdat'):raise RuntimeError('MP4 faststart index is missing')
    return dict(codec='H.264 / AVC',codec_tag='avc1',pixel_format='yuv420p',profile='Main',level='3.1',
                faststart=True,full_decode_verified=True,frames=actual,fps=actual_fps,
                size=list(actual_size),duration_s=actual/actual_fps,bytes=Path(path).stat().st_size)

class H264Writer:
    def __init__(self,path,fps,size):
        self.path=Path(path);self.temp=self.path.with_name(self.path.stem+'.partial.mp4')
        self.fps=fps;self.size=size;self.frames=0;self.result=None
        self.log_path=self.path.with_name(self.path.stem+'-encoder.log')
        self.log=self.log_path.open('wb')
        args=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','warning','-y',
              '-f','rawvideo','-pix_fmt','bgr24','-s:v',f'{size[0]}x{size[1]}','-r',str(fps),'-i','pipe:0',
              '-an','-c:v','libx264','-preset','veryfast','-crf','20','-profile:v','main','-level:v','3.1',
              '-pix_fmt','yuv420p','-tag:v','avc1','-movflags','+faststart',str(self.temp)]
        try:
            self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self.log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except Exception:self.log.close();raise

    def write(self,frame):
        if frame.shape!=(self.size[1],self.size[0],3) or frame.dtype.name!='uint8':raise ValueError('Expected BGR uint8 frame')
        self.process.stdin.write(frame.tobytes());self.frames+=1

    def release(self):
        try:
            try:self.process.stdin.close()
            except BrokenPipeError:pass
            code=self.process.wait(timeout=120)
        except Exception:
            self.process.kill();self.process.wait();raise
        finally:self.log.close()
        if code:raise RuntimeError('H.264 encoder: '+self.log_path.read_text(encoding='utf-8',errors='replace')[-2000:])
        self.result=validate_video(self.temp,self.frames,self.fps,self.size)
        self.temp.replace(self.path)
