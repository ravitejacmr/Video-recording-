"""Deterministic FFmpeg compositor. No shell commands or source-file writes."""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
from .model import Project

# Do not let a disguised playlist fetch URLs or recursively open other files.
LOCAL_MEDIA_INPUT = ['-protocol_whitelist', 'file,pipe', '-format_whitelist',
                     'mov,matroska,webm,avi,mpegts,mp3,wav,aac,flac,ogg,image2,png_pipe,jpeg_pipe,bmp_pipe,webp_pipe']

class Cancelled(Exception):
    pass


def ffmpeg_path():
    override = os.environ.get('IMAGEIO_FFMPEG_EXE')
    if override:
        return override
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        path = shutil.which('ffmpeg')
        if path:
            return path
        raise RuntimeError('FFmpeg is missing. Run Setup-Windows.bat first.')


def subprocess_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


@lru_cache(maxsize=256)
def _probe(path, modified, size):
    result = subprocess.run([ffmpeg_path(), '-hide_banner', *LOCAL_MEDIA_INPUT, '-i', path],
                            capture_output=True, text=True, errors='replace',
                            timeout=30, **subprocess_options())
    info = result.stderr
    match = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', info)
    duration = (int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])) if match else 0
    video_lines = [line for line in info.splitlines() if 'Video:' in line and 'attached pic' not in line]
    return {'duration': duration, 'audio': 'Audio:' in info, 'video': bool(video_lines)}


def probe(path):
    p = Path(path).resolve()
    s = p.stat()
    return _probe(str(p), s.st_mtime_ns, s.st_size)


def atempo(speed):
    parts = []
    while speed < .5:
        parts.append('atempo=0.5')
        speed /= .5
    while speed > 2:
        parts.append('atempo=2')
        speed /= 2
    parts.append(f'atempo={speed:.8f}')
    return ','.join(parts)


def font_path(custom=''):
    candidates = [custom, str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf'),
                  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                  '/System/Library/Fonts/Supplemental/Arial.ttf']
    return next((p for p in candidates if p and Path(p).is_file()), '')


def title_image(clip, width, height, dest):
    im = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(im)
    path = font_path(clip.font)
    size = max(8, int(clip.font_size * width / 1920))
    font = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    # Wrap paragraphs to the canvas; explicit newline breaks are retained.
    lines = []
    for paragraph in clip.text.split('\n'):
        line = ''
        for word in paragraph.split(' '):
            candidate = (line + ' ' + word).strip()
            if draw.textlength(candidate, font=font) > width * .88 and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    text = '\n'.join(lines)
    box = draw.multiline_textbbox((0, 0), text, font=font, align='center', spacing=8)
    x = (width - box[2] + box[0]) / 2
    y = height * .78 - (box[3] - box[1]) / 2
    pad = max(8, size // 3)
    if clip.text_box:
        draw.rounded_rectangle((x - pad, y - pad, x + box[2] + pad, y + box[3] + pad),
                               radius=pad, fill=(5, 10, 20, 190))
    draw.multiline_text((x, y), text, font=font, fill=clip.color, align='center',
                        spacing=8, stroke_width=1, stroke_fill=(0, 0, 0, 160))
    im.save(dest)


class Renderer:
    def __init__(self):
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def build_command(self, project, output, workdir, preview=False, start=0, length=None, quality=20):
        project.validate()
        total = project.duration
        width, height = project.width, project.height
        if preview:
            ratio = min(1, 640 / width, 360 / height)
            width, height = max(64, int(width * ratio) // 2 * 2), max(64, int(height * ratio) // 2 * 2)
        fps = project.fps
        args = [ffmpeg_path(), '-hide_banner', '-nostdin', '-y', '-filter_complex_threads', '2',
                '-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}:r={fps}:d={total:.8f}',
                '-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo:d={total:.8f}']
        graph = ['[0:v]format=rgba[base]', '[1:a]anull[silence]']
        base, audio, input_index = 'base', ['silence'], 2
        for index, clip in enumerate(sorted(project.clips, key=lambda c: c.track)):
            if self.cancel_event.is_set():
                raise Cancelled()
            media = clip.path
            is_still = clip.kind in ('text', 'image')
            if clip.kind == 'text':
                media = str(Path(workdir) / f'title-{index}.png')
                title_image(clip, width, height, media)
            if is_still:
                args += ['-loop', '1', '-framerate', str(fps), '-t', f'{clip.duration:.8f}', *LOCAL_MEDIA_INPUT, '-i', media]
                info = {'audio': False, 'video': True}
            else:
                info = probe(media)
                if clip.kind == 'video' and not info['video']:
                    raise ValueError(f'{clip.name}: no video stream found.')
                if clip.kind == 'audio' and not info['audio']:
                    raise ValueError(f'{clip.name}: no audio stream found.')
                if info['duration'] <= 0 or clip.source_out > info['duration'] + .08:
                    raise ValueError(f'{clip.name}: trim end exceeds the source duration.')
                args += ['-ss', f'{clip.source_in:.8f}', '-t', f'{clip.source_out - clip.source_in:.8f}', *LOCAL_MEDIA_INPUT, '-i', media]
            if clip.kind != 'audio':
                chain = [f'setpts=(PTS-STARTPTS)/{1 if is_still else clip.speed:.8f}', f'fps={fps}']
                if clip.crop:
                    factor = 1 - 2 * clip.crop
                    chain.append(f'crop=trunc(iw*{factor}/2)*2:trunc(ih*{factor}/2)*2')
                if clip.rotation == 90:
                    chain.append('transpose=1')
                elif clip.rotation == 180:
                    chain += ['hflip', 'vflip']
                elif clip.rotation == 270:
                    chain.append('transpose=2')
                w, h = max(2, int(width * clip.scale) // 2 * 2), max(2, int(height * clip.scale) // 2 * 2)
                chain += [f'scale={w}:{h}:force_original_aspect_ratio=decrease', 'setsar=1',
                          f'eq=brightness={clip.brightness}:contrast={clip.contrast}:saturation={clip.saturation}']
                if clip.lut:
                    # Copy to a controlled relative name so filter syntax never contains a user path.
                    lut = f'grade-{index}.cube'
                    shutil.copyfile(clip.lut, Path(workdir) / lut)
                    chain.append(f'lut3d=file={lut}')
                if clip.blur:
                    chain.append(f'gblur=sigma={clip.blur}')
                chain.append('format=rgba')
                source_label = f'[{input_index}:v:0]'
                if clip.chroma:
                    # Keying replaces alpha; multiply with the original alpha so
                    # transparent PNG regions remain transparent after keying.
                    graph.append(source_label + ','.join(chain) + f'[keysrc{index}]')
                    graph += [f'[keysrc{index}]split[kr{index}][ko{index}]',
                              f'[ko{index}]alphaextract[oa{index}]',
                              f'[kr{index}]colorkey=0x{clip.key_color[1:]}:{clip.similarity}:0.08,split[kv{index}][ka{index}]',
                              f'[ka{index}]alphaextract[na{index}]',
                              f'[oa{index}][na{index}]blend=all_mode=multiply[ma{index}]',
                              f'[kv{index}][ma{index}]alphamerge[keyed{index}]']
                    source_label, chain = f'[keyed{index}]', []
                chain.append(f'colorchannelmixer=aa={clip.opacity}')
                if clip.fade_in:
                    chain.append(f'fade=t=in:st=0:d={clip.fade_in}:alpha=1')
                if clip.fade_out:
                    chain.append(f'fade=t=out:st={clip.duration - clip.fade_out}:d={clip.fade_out}:alpha=1')
                chain.append(f'setpts=PTS+{clip.start}/TB')
                graph.append(source_label + ','.join(chain) + f'[v{index}]')
                x = f'(W-w)/2+W*{clip.x}'
                y = f'(H-h)/2+H*{clip.y}'
                if clip.animate:
                    factor = f'clip((t-{clip.start})/{clip.duration},0,1)'
                    x += f'+W*({clip.end_x - clip.x})*{factor}'
                    y += f'+H*({clip.end_y - clip.y})*{factor}'
                graph.append(f'[{base}][v{index}]overlay=x=\'{x}\':y=\'{y}\':eof_action=pass:repeatlast=0:'
                             f'enable=\'gte(t,{clip.start})*lt(t,{clip.end})\'[b{index}]')
                base = f'b{index}'
            if info['audio'] and not clip.muted and clip.volume > 0:
                chain = [f'asetpts=PTS-STARTPTS', atempo(clip.speed), 'aresample=48000',
                         'aformat=sample_fmts=fltp:channel_layouts=stereo', f'volume={clip.volume}',
                         f'apad=whole_dur={clip.duration}', f'atrim=duration={clip.duration}']
                if clip.fade_in:
                    chain.append(f'afade=t=in:d={clip.fade_in}')
                if clip.fade_out:
                    chain.append(f'afade=t=out:st={clip.duration - clip.fade_out}:d={clip.fade_out}')
                chain.append(f'adelay={round(clip.start * 1000)}:all=1')
                graph.append(f'[{input_index}:a:0]' + ','.join(chain) + f'[a{index}]')
                audio.append(f'a{index}')
            input_index += 1
        graph += [f'[{base}]format=yuv420p[vout]',
                  ''.join(f'[{a}]' for a in audio) + f'amix=inputs={len(audio)}:duration=first:normalize=0,'
                  'alimiter=limit=0.95:level=false:latency=true[aout]']
        graph_path = Path(workdir) / 'filters.txt'
        graph_path.write_text(';\n'.join(graph), encoding='utf-8')
        args += ['-filter_complex_script', str(graph_path), '-map', '[vout]', '-map', '[aout]']
        if start:
            args += ['-ss', f'{start:.8f}']
        render_duration = min(length if length is not None else total, total - start)
        if render_duration <= 0:
            raise ValueError('Preview starts beyond the end of the project.')
        args += ['-t', f'{render_duration:.8f}', '-c:v', 'libx264', '-preset', 'ultrafast' if preview else 'medium',
                 '-crf', str(26 if preview else quality), '-pix_fmt', 'yuv420p', '-threads', '2',
                 '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart',
                 '-progress', 'pipe:1', '-nostats', str(output)]
        return args, render_duration

    def render(self, project, output, progress=lambda value, message: None, **kwargs):
        output = Path(output).resolve()
        media_paths = [Path(p).resolve() for c in project.clips for p in (c.path, c.font, c.lut) if p]
        if output in media_paths:
            raise ValueError('Choose a different export path; source media cannot be overwritten.')
        output.parent.mkdir(parents=True, exist_ok=True)
        # Render beside the destination, then atomically replace only after success.
        with tempfile.TemporaryDirectory(prefix='softenant-', dir=output.parent) as temp:
            partial = Path(temp) / 'render.mp4'
            command, duration = self.build_command(project, partial, temp, **kwargs)
            if self.cancel_event.is_set():
                raise Cancelled()
            progress(0, 'Rendering video and audio…')
            with open(Path(temp) / 'ffmpeg.log', 'w+', encoding='utf-8') as log:
                proc = subprocess.Popen(command, cwd=temp, stdout=subprocess.PIPE, stderr=log,
                                        text=True, errors='replace', **subprocess_options())
                # Reader thread keeps cancellation responsive even if decoding stalls.
                import queue
                events = queue.Queue()
                def read_progress():
                    for line in proc.stdout:
                        events.put(line)
                reader = threading.Thread(target=read_progress, daemon=True)
                reader.start()
                try:
                    while proc.poll() is None or not events.empty():
                        if self.cancel_event.is_set():
                            proc.terminate()
                            raise Cancelled()
                        try:
                            line = events.get(timeout=.1)
                        except queue.Empty:
                            continue
                        if line.startswith('out_time_us='):
                            try:
                                progress(min(99, max(0, int(float(line.split('=')[1]) / 1e6 / duration * 100))),
                                         'Rendering video and audio…')
                            except ValueError:
                                pass
                    if proc.wait() != 0:
                        log.seek(0)
                        raise RuntimeError(log.read()[-6000:])
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait()
                    reader.join(timeout=2)
                    proc.stdout.close()
            if self.cancel_event.is_set():
                raise Cancelled()
            os.replace(partial, output)
        progress(100, 'Finished')
        return str(output)
