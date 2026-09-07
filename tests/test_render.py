import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import pytest
from PIL import Image
from studio.model import Clip, Project
from studio.engine import Renderer, Cancelled, ffmpeg_path, probe


def run(args):
    result = subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',*args],capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return result.stdout


@pytest.fixture(scope='module')
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp('media with spaces')
    video = root / "red's test.mp4"
    silent = root / 'blue silent.mp4'
    audio = root / 'tone.wav'
    logo = root / 'logo.png'
    run(['-f','lavfi','-i','color=c=red:s=320x180:r=30:d=3','-f','lavfi','-i',
         'sine=frequency=440:duration=3','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(video)])
    run(['-f','lavfi','-i','color=c=blue:s=180x320:r=30:d=2','-c:v','libx264','-threads','2',str(silent)])
    run(['-f','lavfi','-i','sine=frequency=880:duration=1','-c:a','pcm_s16le',str(audio)])
    im = Image.new('RGBA',(100,100),(0,0,0,0))
    for x in range(25,75):
        for y in range(25,75): im.putpixel((x,y),(0,255,0,255))
    im.save(logo)
    return root,video,silent,audio,logo


def frame(path,time):
    raw = run(['-ss',str(time),'-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
    return Image.frombytes('RGB',(320,180),raw)


def test_multitrack_transparency_timing_and_audio(media,tmp_path):
    _,red,blue,tone,logo = media
    project = Project(width=320,height=180,clips=[
        Clip(path=str(red),source_out=3),
        Clip(path=str(blue),start=1,source_out=1,track=1,scale=.5,x=.25),
        Clip(kind='image',path=str(logo),track=1,source_out=3,scale=.5,x=-.25),
        Clip(kind='audio',path=str(tone),track=2,start=2,source_out=1,volume=.2),
        Clip(kind='text',track=4,start=2,source_out=1,text='Softenant',font_size=100)])
    output = tmp_path/'out.mp4'
    progress = []
    Renderer().render(project,output,lambda p,m:progress.append(p))
    info = probe(str(output))
    assert abs(info['duration']-3)<.15 and info['audio'] and info['video']
    first = frame(output,.5)
    assert first.getpixel((10,10))[0]>200  # alpha outside logo must preserve red base
    assert first.getpixel((80,90))[1]>180  # green logo centre
    during = frame(output,1.5)
    assert during.getpixel((240,90))[2]>180  # portrait overlay in second second
    after = frame(output,2.5)
    assert after.getpixel((240,90))[0]>180  # overlay disappears at its end
    assert progress[-1]==100
    raw = run(['-i',str(output),'-map','0:a','-f','s16le','-ac','1','pipe:1'])
    assert any(raw)


@pytest.mark.parametrize('speed',[.25,.5,2,4])
def test_trim_and_speed(media,tmp_path,speed):
    _,red,*_ = media
    project = Project(width=320,height=180,clips=[Clip(path=str(red),source_in=.5,source_out=1.5,speed=speed)])
    output = tmp_path/f'speed-{speed}.mp4'
    Renderer().render(project,output)
    assert abs(probe(str(output))['duration'] - 1/speed) < .15


def test_gaps_fades_effects_motion_and_green_screen(media,tmp_path):
    _,red,blue,tone,logo = media
    project = Project(width=320,height=180,clips=[
        Clip(path=str(red),source_out=2,start=.5,brightness=.05,contrast=1.1,saturation=.8,
             rotation=180,crop=.1,blur=.2,fade_in=.2,fade_out=.2),
        Clip(kind='image',path=str(logo),track=1,source_out=2,start=.5,scale=.4,chroma=True,
             animate=True,x=-.2,end_x=.2,opacity=.8)])
    output = tmp_path/'effects.mp4'
    Renderer().render(project,output)
    assert max(frame(output,.1).getpixel((160,90)))<15
    pixel = frame(output,1.0).getpixel((160,90))
    assert pixel[0]>150 and pixel[1]<90


def test_cancellation_and_failure_preserve_destination(media,tmp_path):
    _,red,*_ = media
    project = Project(width=320,height=180,clips=[Clip(path=str(red),source_out=2)])
    output = tmp_path/'existing.mp4'
    output.write_bytes(b'keep existing')
    engine = Renderer()
    engine.cancel()
    with pytest.raises(Cancelled): engine.render(project,output)
    assert output.read_bytes()==b'keep existing'
    with pytest.raises(ValueError): Renderer().render(project,red)
    project.clips[0].source_out = 50
    with pytest.raises(ValueError): Renderer().render(project,output)
    assert output.read_bytes()==b'keep existing'


def test_preview_and_audio_only(media,tmp_path):
    _,red,_,tone,_ = media
    project = Project(width=320,height=180,clips=[Clip(path=str(red),source_out=3)])
    output = tmp_path/'preview.mp4'
    Renderer().render(project,output,preview=True,start=1,length=.5)
    assert abs(probe(str(output))['duration']-.5)<.15
    project.clips = [Clip(kind='audio',track=2,path=str(tone),source_out=1,start=.5)]
    Renderer().render(project,output)
    assert abs(probe(str(output))['duration']-1.5)<.15
    assert max(frame(output,.8).getpixel((160,90)))<15
