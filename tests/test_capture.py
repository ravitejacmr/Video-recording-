import time
import pytest
from studio.capture import Monitor, ScreenRecorder, capture_command
from studio.engine import ffmpeg_path, probe


def test_capture_uses_monitor_offsets_and_optional_microphone():
    monitor = Monitor('Left monitor',-1920,0,1920,1080)
    command = capture_command(monitor,'Microphone (USB)','record.mp4',1280)
    assert command[command.index('-offset_x')+1]=='-1920'
    assert 'audio=Microphone (USB)' in command
    assert 'scale=1280:720,setsar=1' in command
    assert '-an' in capture_command(monitor,'','silent.mp4')


def test_recording_stop_finalizes_real_mp4(tmp_path):
    def synthetic(monitor,mic,output,size):
        return [ffmpeg_path(),'-hide_banner','-y','-re','-f','lavfi','-i',
                'testsrc2=s=160x90:r=30','-c:v','libx264','-preset','ultrafast',
                '-threads','2','-pix_fmt','yuv420p',str(output)]
    backend = ScreenRecorder()
    output = tmp_path/'recording.mp4'
    try:
        backend.start(Monitor('test',0,0,160,90),'',output,command_factory=synthetic)
        time.sleep(.7)
        backend.stop()
        deadline = time.monotonic()+10
        result = None
        while result is None and time.monotonic()<deadline:
            result = backend.poll()
            time.sleep(.05)
        assert result==str(output)
        assert probe(str(output))['duration']>0
        assert backend.process is None
        with pytest.raises(ValueError):
            backend.start(Monitor('test',0,0,160,90),'',output,command_factory=synthetic)
    finally:
        backend.cleanup()
