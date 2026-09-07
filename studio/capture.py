"""Windows screen capture using the bundled FFmpeg software encoder."""
from dataclasses import dataclass
from pathlib import Path
import ctypes
import os
import re
import subprocess
import tempfile
import time
from .engine import ffmpeg_path, subprocess_options


@dataclass
class Monitor:
    name: str
    x: int
    y: int
    width: int
    height: int


def monitors():
    if os.name != 'nt': return []
    from ctypes import wintypes
    class Info(ctypes.Structure):
        _fields_ = [('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),
                    ('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD),('szDevice',wintypes.WCHAR*32)]
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HANDLE,wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
    user32 = ctypes.windll.user32
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE,ctypes.POINTER(Info)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC,ctypes.POINTER(wintypes.RECT),callback_type,wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    def visit(handle,dc,rect,data):
        info = Info()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle,ctypes.byref(info)):
            r = info.rcMonitor
            result.append(Monitor(info.szDevice,r.left,r.top,r.right-r.left,r.bottom-r.top))
        return True
    callback = callback_type(visit)
    if not user32.EnumDisplayMonitors(None,None,callback,0):
        raise RuntimeError('Windows could not list the connected monitors.')
    return result


def microphones():
    if os.name != 'nt': return []
    result = subprocess.run([ffmpeg_path(),'-hide_banner','-list_devices','true','-f','dshow','-i','dummy'],
                            capture_output=True,timeout=20,**subprocess_options())
    text = result.stderr.decode('utf-8',errors='replace')
    return list(dict.fromkeys(re.findall(r'"([^"\r\n]+)"\s+\(audio\)',text)))


def capture_command(monitor, microphone, output, max_width=1920):
    if monitor.width<=0 or monitor.height<=0: raise ValueError('Invalid monitor size.')
    args = [ffmpeg_path(),'-hide_banner','-y','-thread_queue_size','512','-f','gdigrab',
            '-framerate','30','-draw_mouse','1','-offset_x',str(monitor.x),'-offset_y',str(monitor.y),
            '-video_size',f'{monitor.width}x{monitor.height}','-i','desktop']
    if microphone:
        args += ['-thread_queue_size','512','-f','dshow','-i',f'audio={microphone}']
    ratio = min(1,max_width/monitor.width,max_width*9/16/monitor.height) if max_width else 1
    width,height = max(2,int(monitor.width*ratio)//2*2),max(2,int(monitor.height*ratio)//2*2)
    args += ['-map','0:v:0','-vf',f'scale={width}:{height},setsar=1','-c:v','libx264',
             '-preset','ultrafast','-crf','20','-pix_fmt','yuv420p','-threads','2']
    if microphone:
        args += ['-map','1:a:0','-af','aresample=async=1:first_pts=0','-c:a','aac','-b:a','192k']
    else:
        args += ['-an']
    return args + ['-movflags','+faststart',str(output)]


class ScreenRecorder:
    def __init__(self):
        self.process,self.temp,self.log = None,None,None
        self.output,self.partial = None,None
        self.started,self.stopping = 0,False

    def start(self,monitor,microphone,output,max_width=1920,command_factory=capture_command):
        if self.process is not None: raise RuntimeError('A recording is already running.')
        output = Path(output).resolve()
        if output.exists(): raise ValueError('Choose a new filename for the recording.')
        output.parent.mkdir(parents=True,exist_ok=True)
        self.output = output
        self.temp = tempfile.TemporaryDirectory(prefix='recording-',dir=output.parent)
        self.partial = Path(self.temp.name)/'capture.mp4'
        self.log = open(Path(self.temp.name)/'capture.log','w+b')
        try:
            command = command_factory(monitor,microphone,self.partial,max_width)
            self.process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,
                                            stderr=self.log,**subprocess_options())
        except Exception:
            self.cleanup()
            raise
        self.started,self.stopping = time.monotonic(),False

    def stop(self):
        if self.process and self.process.poll() is None and not self.stopping:
            self.stopping = True
            try:
                self.process.stdin.write(b'q\n')
                self.process.stdin.flush()
            except (BrokenPipeError,OSError): pass

    def poll(self):
        if self.process is None or self.process.poll() is None: return None
        code = self.process.returncode
        self.log.seek(0)
        details = self.log.read().decode('utf-8',errors='replace')[-5000:]
        output = str(self.output)
        try:
            if code!=0 or not self.partial.is_file() or self.partial.stat().st_size==0:
                raise RuntimeError(details or 'No recording was produced.')
            if self.output.exists():
                recovery = self.output.with_name(self.output.stem+'-recovered-'+str(time.time_ns())+'.mp4')
                os.replace(self.partial,recovery)
                raise RuntimeError(f'The destination now exists. Recording preserved as:\n{recovery}')
            os.replace(self.partial,self.output)
            return output
        finally:
            self.cleanup()

    def cleanup(self):
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            if self.process.stdin: self.process.stdin.close()
        if self.log: self.log.close()
        if self.temp: self.temp.cleanup()
        self.process,self.log,self.temp = None,None,None
