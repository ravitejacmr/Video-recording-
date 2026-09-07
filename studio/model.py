"""Portable, versioned project model. Times are seconds; source media is never edited."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
import copy
import json
import math
import os
import uuid


def uid():
    return uuid.uuid4().hex[:12]


@dataclass
class Clip:
    id: str = field(default_factory=uid)
    kind: str = 'video'
    name: str = 'Clip'
    path: str = ''
    track: int = 0
    start: float = 0.0
    source_in: float = 0.0
    source_out: float = 5.0
    speed: float = 1.0
    volume: float = 1.0
    x: float = 0.0
    y: float = 0.0
    end_x: float = 0.0
    end_y: float = 0.0
    animate: bool = False
    scale: float = 1.0
    opacity: float = 1.0
    rotation: int = 0
    crop: float = 0.0
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    blur: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    chroma: bool = False
    key_color: str = '#00ff00'
    similarity: float = 0.15
    lut: str = ''
    text: str = 'Softenant Technologies'
    font_size: int = 56
    color: str = '#ffffff'
    font: str = ''
    text_box: bool = True
    muted: bool = False

    @property
    def duration(self):
        return (self.source_out - self.source_in) / self.speed

    @property
    def end(self):
        return self.start + self.duration

    def validate(self):
        if self.kind not in ('video', 'audio', 'image', 'text'):
            raise ValueError('Unsupported clip type.')
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, (int, float)) and not math.isfinite(v):
                raise ValueError(f'{self.name}: {f.name} must be finite.')
        if not 0.25 <= self.speed <= 4 or self.source_in < 0 or self.source_out <= self.source_in:
            raise ValueError(f'{self.name}: use a valid trim range and speed from 0.25 to 4.')
        if self.start < 0 or self.duration < 0.04:
            raise ValueError(f'{self.name}: duration must be at least 0.04 seconds.')
        if self.track not in range(5):
            raise ValueError('Track must be between 0 and 4.')
        if self.kind == 'audio' and self.track not in (2, 3):
            raise ValueError('Audio clips belong on A1 or A2.')
        if self.kind != 'audio' and self.track not in (0, 1, 4):
            raise ValueError('Visual clips belong on V1, V2 or Titles.')
        limits = {'volume': (0, 4), 'scale': (.05, 2), 'opacity': (0, 1),
                  'crop': (0, .45), 'brightness': (-1, 1), 'contrast': (0, 3),
                  'saturation': (0, 3), 'blur': (0, 20), 'similarity': (.01, 1),
                  'font_size': (8, 240), 'x': (-2, 2), 'y': (-2, 2),
                  'end_x': (-2, 2), 'end_y': (-2, 2)}
        for key, (low, high) in limits.items():
            if not low <= getattr(self, key) <= high:
                raise ValueError(f'{self.name}: {key} must be in {low}..{high}.')
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError('Rotation must be 0, 90, 180 or 270.')
        if min(self.fade_in, self.fade_out) < 0 or self.fade_in + self.fade_out > self.duration:
            raise ValueError(f'{self.name}: combined fades cannot exceed clip duration.')
        import re
        for color in (self.color, self.key_color):
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                raise ValueError('Colours must use #RRGGBB.')
        if self.kind != 'text' and not Path(self.path).is_file():
            raise ValueError(f'Missing media: {self.path}\nUse Relink selected media.')
        for path in (self.lut, self.font):
            if path and not Path(path).is_file():
                raise ValueError(f'Missing file: {path}')


@dataclass
class Project:
    version: int = 1
    name: str = 'Untitled project'
    width: int = 1920
    height: int = 1080
    fps: int = 30
    clips: list[Clip] = field(default_factory=list)

    @property
    def duration(self):
        return max((c.end for c in self.clips), default=0.0)

    def validate(self):
        if self.version != 1:
            raise ValueError('This project version is not supported.')
        if self.width not in range(64, 4097, 2) or self.height not in range(64, 4097, 2):
            raise ValueError('Use even dimensions from 64 to 4096.')
        if self.fps not in (24, 25, 30, 60):
            raise ValueError('Frame rate must be 24, 25, 30 or 60.')
        if not self.clips:
            raise ValueError('Add at least one clip before rendering.')
        if len({c.id for c in self.clips}) != len(self.clips):
            raise ValueError('Clip IDs must be unique.')
        for c in self.clips:
            c.validate()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if data.get('version') != 1:
            raise ValueError('Unsupported project version.')
        data = copy.deepcopy(data)
        data['clips'] = [Clip(**c) for c in data.get('clips', [])]
        return cls(**data)

    def save(self, path, expected_revision=None):
        path = Path(path).resolve()
        data = self.to_dict()
        for c in data['clips']:
            for key in ('path', 'font', 'lut'):
                if c[key]:
                    try:
                        c[key] = os.path.relpath(c[key], path.parent)
                    except ValueError:  # Windows media on another drive
                        c[key] = str(Path(c[key]).resolve())
        from filelock import FileLock
        import hashlib
        with FileLock(str(path)+'.lock', timeout=5):
            if expected_revision is not None:
                current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                if current != expected_revision:
                    raise ValueError('Project changed in another editor. Reload it or Save as a new project.')
            temp = path.with_name(path.name + '.tmp')
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, path)
            return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        data = json.loads(path.read_text(encoding='utf-8'))
        for c in data.get('clips', []):
            for key in ('path', 'font', 'lut'):
                if c.get(key):
                    p = Path(c[key])
                    c[key] = str((path.parent / p).resolve()) if not p.is_absolute() else str(p)
        return cls.from_dict(data)


def split_clip(clip, timeline_time):
    if not clip.start + .04 < timeline_time < clip.end - .04:
        raise ValueError('Place the playhead inside the clip, away from its edges.')
    left, right = copy.deepcopy(clip), copy.deepcopy(clip)
    point = clip.source_in + (timeline_time - clip.start) * clip.speed
    left.source_out = point
    right.source_in = point
    right.start = timeline_time
    right.id = uid()
    if clip.animate:
        ratio = (timeline_time - clip.start) / clip.duration
        left.end_x = right.x = clip.x + (clip.end_x - clip.x) * ratio
        left.end_y = right.y = clip.y + (clip.end_y - clip.y) * ratio
    # A split keeps existing boundary fades and avoids introducing a new transition.
    left.fade_in = min(left.fade_in, left.duration)
    left.fade_out = 0
    right.fade_in = 0
    right.fade_out = min(right.fade_out, right.duration)
    return left, right


class History:
    def __init__(self):
        self.undo_stack, self.redo_stack = [], []

    def record(self, project):
        self.undo_stack.append(project.to_dict())
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def undo(self, project):
        if not self.undo_stack:
            return project
        self.redo_stack.append(project.to_dict())
        return Project.from_dict(self.undo_stack.pop())

    def redo(self, project):
        if not self.redo_stack:
            return project
        self.undo_stack.append(project.to_dict())
        return Project.from_dict(self.redo_stack.pop())
