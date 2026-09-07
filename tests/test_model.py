import math
import pytest
from studio.model import Clip, Project, History, split_clip
from studio.captions import read_srt, write_srt


def test_split_preserves_timing_speed_and_motion():
    clip = Clip(kind='text', start=2, source_in=1, source_out=9, speed=2,
                animate=True,x=0,end_x=1,fade_in=.2,fade_out=.2)
    left,right = split_clip(clip,3)
    assert left.duration == 1 and right.duration == 3
    assert left.source_out == right.source_in == 3
    assert right.end == clip.end
    assert left.end_x == right.x == .25
    assert left.fade_out == right.fade_in == 0
    assert left.id != right.id


def test_project_portable_and_history(tmp_path):
    media = tmp_path/'media'
    media.mkdir()
    image = media/'logo.png'
    image.write_bytes(b'placeholder')
    p = Project(clips=[Clip(kind='image',path=str(image))])
    path = tmp_path/'project.svs'
    p.save(path)
    assert 'media' in path.read_text()
    assert Project.load(path).clips[0].path == str(image)
    h = History()
    h.record(p)
    p.clips[0].start = 5
    p = h.undo(p)
    assert p.clips[0].start == 0
    assert h.redo(p).clips[0].start == 5


def test_validation_rejects_invalid_values():
    for changes in ({'speed':0},{'start':-1},{'volume':math.inf}, {'fade_in':4,'fade_out':4},
                    {'color':'red'},{'scale':-1},{'track':2}):
        with pytest.raises(ValueError):
            Clip(kind='text',**changes).validate()


def test_srt_round_trip(tmp_path):
    p = tmp_path/'captions.srt'
    clips = [Clip(kind='text',track=4,start=1.123,source_out=2.5,text='Hello\nVizag')]
    write_srt(clips,p)
    restored = read_srt(p)
    assert restored[0].start == 1.123
    assert restored[0].duration == 2.5
    assert restored[0].text == 'Hello\nVizag'
    p.write_text('1\n00:00:02,000 --> 00:00:01,000\nbad')
    with pytest.raises(ValueError): read_srt(p)
