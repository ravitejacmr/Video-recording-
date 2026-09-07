"""SRT interchange, plus optional local Whisper transcription."""
from pathlib import Path
import re
from .model import Clip


def seconds(value):
    h, m, s, ms = re.split('[:,.]', value.strip())
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def stamp(value):
    ms = max(0, round(value * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def read_srt(path, offset=0):
    text = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    clips = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.splitlines()
        row = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if row is None:
            continue
        times = re.findall(r'\d+:\d{2}:\d{2}[,.]\d{3}', lines[row])
        if len(times) != 2:
            raise ValueError('Invalid SRT timestamp.')
        a, b = map(seconds, times)
        if b <= a:
            raise ValueError('Subtitle end must follow its start.')
        clips.append(Clip(kind='text', track=4, name=f'Caption {len(clips)+1}',
                          start=a + offset, source_out=b-a, text='\n'.join(lines[row+1:]), font_size=56))
    if not clips:
        raise ValueError('No valid subtitles found in this SRT file.')
    return clips


def write_srt(clips, path):
    blocks = []
    for c in sorted((c for c in clips if c.kind == 'text'), key=lambda c: c.start):
        blocks.append(f'{len(blocks)+1}\n{stamp(c.start)} --> {stamp(c.end)}\n{c.text}\n')
    Path(path).write_text('\n'.join(blocks), encoding='utf-8')


def transcribe_clip(clip, progress, cancelled):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError('Automatic captions need the optional package. Run Enable-Auto-Captions.bat, then restart.')
    progress(0, 'Loading Whisper base model (first use downloads the model)…')
    model = WhisperModel('base', device='cpu', compute_type='int8')
    segments, _ = model.transcribe(clip.path, vad_filter=True,
                                  clip_timestamps=f'{clip.source_in},{clip.source_out}')
    result = []
    for s in segments:
        if cancelled.is_set():
            from .engine import Cancelled
            raise Cancelled()
        start, end = max(s.start, clip.source_in), min(s.end, clip.source_out)
        if end > start:
            result.append(Clip(kind='text', track=4, name='Auto caption',
                               start=clip.start+(start-clip.source_in)/clip.speed,
                               source_out=(end-start)/clip.speed, text=s.text.strip()))
            progress(min(99, int((end-clip.source_in)/(clip.source_out-clip.source_in)*100)), 'Transcribing speech…')
    return result
