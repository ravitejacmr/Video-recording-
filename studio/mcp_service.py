"""Workspace-scoped editing operations shared by the MCP transports."""
from __future__ import annotations
from dataclasses import asdict, fields
from pathlib import Path
import copy
import hashlib
import math
import os
import re
import subprocess
import sys
import threading
import time
from PIL import Image
from .model import Project, Clip, split_clip, uid
from .engine import Renderer, Cancelled, probe, ffmpeg_path, subprocess_options, LOCAL_MEDIA_INPUT
from .capture import ScreenRecorder, monitors, microphones
from .captions import read_srt

MEDIA = {'.mp4','.mov','.mkv','.avi','.webm','.m4v','.mp3','.wav','.m4a','.aac','.flac','.ogg',
         '.png','.jpg','.jpeg','.webp','.bmp','.srt','.cube','.ttf','.otf'}
STILLS = {'.png','.jpg','.jpeg','.webp','.bmp'}


def workspace_path():
    return Path(os.environ.get('SOFTENANT_WORKSPACE',str(Path.home()/'Documents'/'SoftenantStudio'))).resolve()


def revision(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bounded(value,minimum,maximum,name):
    if not math.isfinite(value) or not minimum<=value<=maximum:
        raise ValueError(f'{name} must be in {minimum}..{maximum}.')
    return value


class StudioService:
    def __init__(self,root=None,allow_recording=False):
        self.root = Path(root or workspace_path()).resolve()
        for folder in ('Media','Projects','Exports'):
            p = self.root/folder
            p.mkdir(parents=True,exist_ok=True)
            if not p.resolve().is_relative_to(self.root):
                raise ValueError('Workspace folders cannot link outside the workspace.')
        self.allow_recording = allow_recording
        self.lock = threading.RLock()
        self.jobs,self.undo_stack,self.redo_stack = {},{},{}
        self.history_heads = {}
        self.recording = None
        self.devices = None

    def scoped(self,value,folder=None,must_exist=True):
        # Reject UNC, drive paths, traversal and symlinks/junctions leaving the root.
        if not value or '\\' in value or ':' in value or Path(value).is_absolute() or '..' in Path(value).parts:
            raise ValueError('Use a relative workspace path returned by list_media, with forward slashes.')
        path = (self.root/value).resolve()
        base = (self.root/folder).resolve() if folder else self.root
        if not path.is_relative_to(base) or not path.is_relative_to(self.root):
            raise ValueError('Path is outside the permitted workspace folder.')
        if must_exist and not path.is_file(): raise ValueError(f'File not found: {value}')
        return path

    def project_file(self,id_):
        if not re.fullmatch('[0-9a-f]{12}',id_): raise ValueError('Invalid project ID. Use list_projects.')
        return self.scoped(f'Projects/{id_}.svs','Projects',False)

    def validate_scope(self,p):
        for c in p.clips:
            for key in ('path','font','lut'):
                value = getattr(c,key)
                if value:
                    full = Path(value).resolve()
                    if not full.is_relative_to(self.root/'Media'):
                        raise ValueError('Project references media outside the Media folder. Copy media into the workspace first.')

    def read(self,id_):
        path = self.project_file(id_)
        if not path.is_file(): raise ValueError('Project not found.')
        before = revision(path)
        p = Project.load(path)
        if revision(path)!=before: raise ValueError('Project changed while loading. Try get_project again.')
        self.validate_scope(p)
        return p,before

    def describe(self,id_,p,rev):
        data = p.to_dict()
        for c in data['clips']:
            for key in ('path','font','lut'):
                if c[key]: c[key] = Path(c[key]).resolve().relative_to(self.root).as_posix()
            c['duration'] = (c['source_out']-c['source_in'])/c['speed']
        return {'project_id':id_,'revision':rev,'project_file':f'Projects/{id_}.svs',
                'duration':p.duration,**data}

    def get_project(self,id_):
        with self.lock:
            p,rev = self.read(id_)
            return self.describe(id_,p,rev)

    def list_projects(self):
        result = []
        for path in sorted((self.root/'Projects').glob('*.svs')):
            if re.fullmatch('[0-9a-f]{12}',path.stem):
                try:
                    p,rev = self.read(path.stem)
                    result.append({'project_id':path.stem,'name':p.name,'duration':p.duration,'revision':rev})
                except (ValueError,OSError): continue
        return {'projects':result}

    def list_media(self,offset=0,limit=100):
        bounded(offset,0,100000,'offset');bounded(limit,1,200,'limit')
        result = []
        for path in sorted((self.root/'Media').rglob('*')):
            if path.is_file() and path.suffix.lower() in MEDIA and path.resolve().is_relative_to(self.root/'Media'):
                result.append({'media_path':path.relative_to(self.root).as_posix(),'bytes':path.stat().st_size})
        return {'files':result[offset:offset+limit],'total':len(result),
                'next_offset':offset+limit if offset+limit<len(result) else None}

    def create_project(self,name,width=1920,height=1080,fps=30):
        if not 1<=len(name.strip())<=120: raise ValueError('Use a project name with 1–120 characters.')
        p = Project(name=name.strip(),width=width,height=height,fps=fps)
        self.validate_project(p)
        id_ = uid()
        p.save(self.project_file(id_))
        return self.get_project(id_)

    def validate_project(self,p):
        self.validate_scope(p)
        # Reuse full validation for empty projects via a temporary harmless title.
        check = copy.deepcopy(p)
        if not check.clips: check.clips = [Clip(kind='text',track=4)]
        check.validate()
        if len(p.clips)>300 or p.duration>14400:
            raise ValueError('MCP projects are limited to 300 clips and four hours.')
        for c in p.clips:
            if len(c.text)>8000: raise ValueError('A title is limited to 8000 characters.')
            if c.kind in ('video','audio'):
                info = probe(c.path)
                if c.source_out>info['duration']+.08:
                    raise ValueError(f'{c.name}: trim end exceeds the source duration.')

    def mutate(self,id_,expected,operation):
        with self.lock:
            p,rev = self.read(id_)
            if expected!=rev: raise ValueError('Project changed. Call get_project and retry with its revision.')
            previous = copy.deepcopy(p)
            operation(p)
            self.validate_project(p)
            new_revision = p.save(self.project_file(id_),expected_revision=expected)
            if self.history_heads.get(id_)!=rev:
                self.undo_stack[id_],self.redo_stack[id_] = [],[]
            self.history_heads[id_] = new_revision
            self.undo_stack.setdefault(id_,[]).append(previous)
            self.undo_stack[id_] = self.undo_stack[id_][-50:]
            self.redo_stack[id_] = []
            return self.get_project(id_)

    def add_media(self,id_,expected,media_path,start=0,track=0,source_in=0,source_out=None):
        path = self.scoped(media_path,'Media')
        ext = path.suffix.lower()
        if ext not in MEDIA or ext in ('.srt','.cube','.ttf','.otf'): raise ValueError('Choose video, audio or an image.')
        if ext in STILLS:
            with Image.open(path) as image: image.verify()
            kind,end = 'image',5.0
        else:
            info = probe(str(path))
            if info['duration']<=0: raise ValueError('Cannot determine media duration.')
            kind,end = ('video' if info['video'] else 'audio'),info['duration']
        c = Clip(kind=kind,path=str(path),name=path.name,track=track,start=start,
                 source_in=source_in,source_out=end if source_out is None else source_out)
        return self.mutate(id_,expected,lambda p:p.clips.append(c))

    def add_title(self,id_,expected,text,start,duration):
        c = Clip(kind='text',track=4,name='Title',text=text,start=start,source_out=duration)
        return self.mutate(id_,expected,lambda p:p.clips.append(c))

    def update_clip(self,id_,expected,clip_id,changes):
        allowed = {f.name for f in fields(Clip)}-{'id','kind','path'}
        if not changes or set(changes)-allowed: raise ValueError('Unsupported clip fields.')
        def operation(p):
            c = next((c for c in p.clips if c.id==clip_id),None)
            if c is None: raise ValueError('Clip not found.')
            defaults = Clip()
            for k,v in changes.items():
                baseline = getattr(defaults,k)
                if isinstance(baseline,bool): valid = type(v) is bool
                elif isinstance(baseline,int): valid = type(v) is int
                elif isinstance(baseline,float): valid = type(v) in (int,float)
                else: valid = isinstance(v,str)
                if not valid: raise ValueError(f'Invalid type for {k}.')
                if k in ('font','lut') and v: v = str(self.scoped(v,'Media'))
                setattr(c,k,v)
        return self.mutate(id_,expected,operation)

    def split(self,id_,expected,clip_id,seconds):
        def operation(p):
            index = next((i for i,c in enumerate(p.clips) if c.id==clip_id),None)
            if index is None: raise ValueError('Clip not found.')
            p.clips[index:index+1] = split_clip(p.clips[index],seconds)
        return self.mutate(id_,expected,operation)

    def remove(self,id_,expected,clip_id):
        def operation(p):
            c = next((c for c in p.clips if c.id==clip_id),None)
            if c is None: raise ValueError('Clip not found.')
            p.clips.remove(c)
        return self.mutate(id_,expected,operation)

    def settings(self,id_,expected,width,height,fps):
        def operation(p): p.width,p.height,p.fps = width,height,fps
        return self.mutate(id_,expected,operation)

    def captions(self,id_,expected,media_path):
        path = self.scoped(media_path,'Media')
        if path.suffix.lower()!='.srt': raise ValueError('Choose an SRT file.')
        return self.mutate(id_,expected,lambda p:p.clips.extend(read_srt(path)))

    def undo(self,id_,expected,redo=False):
        with self.lock:
            p,rev = self.read(id_)
            if rev!=expected: raise ValueError('Project changed. Call get_project again.')
            if self.history_heads.get(id_)!=rev:
                raise ValueError('Project changed outside this MCP history; older edits cannot be undone safely.')
            source = self.redo_stack if redo else self.undo_stack
            target = self.undo_stack if redo else self.redo_stack
            if not source.get(id_): raise ValueError('No history for this project in this MCP session.')
            restore = source[id_][-1]
            self.validate_project(restore)
            self.history_heads[id_] = restore.save(self.project_file(id_),expected_revision=expected)
            source[id_].pop()
            target.setdefault(id_,[]).append(p)
            return self.get_project(id_)

    def render(self,id_,expected,preview=False,start=0,length=12):
        with self.lock:
            p,rev = self.read(id_)
            if expected!=rev: raise ValueError('Project changed. Call get_project again.')
            self.validate_project(p);p.validate()
            if any(j['status'] in ('queued','running') for j in self.jobs.values()):
                raise ValueError('A render is already running. Wait or cancel it.')
            bounded(start,0,max(0,p.duration-.04),'start')
            bounded(length,.04,60,'length')
            job_id = uid()
            relative = f'Exports/{id_}-{"preview" if preview else "export"}-{job_id}.mp4'
            output = self.scoped(relative,'Exports',False)
            renderer = Renderer()
            job = {'job_id':job_id,'project_id':id_,'revision':rev,'status':'queued','progress':0,
                   'output':relative,'error':'','renderer':renderer}
            self.jobs[job_id] = job
            def update(value,message):
                with self.lock: job['progress'] = value
            def work():
                with self.lock: job['status'] = 'running'
                try:
                    renderer.render(p,output,update,preview=preview,start=start if preview else 0,
                                    length=length if preview else None)
                    with self.lock: job['status'] = 'completed'
                except Cancelled:
                    with self.lock: job['status'] = 'cancelled'
                except Exception as error:
                    with self.lock: job['status'],job['error'] = 'failed',str(error)[-2000:]
            thread = threading.Thread(target=work,daemon=True)
            job['thread'] = thread
            thread.start()
            return self.job_status(job_id)

    def job_status(self,id_):
        with self.lock:
            job = self.jobs.get(id_)
            if not job: raise ValueError('Job not found in this MCP session.')
            return {k:v for k,v in job.items() if k not in ('renderer','thread')}

    def cancel(self,id_):
        with self.lock:
            if id_ not in self.jobs: raise ValueError('Job not found.')
            self.jobs[id_]['renderer'].cancel()
            return self.job_status(id_)

    def preview_frame(self,job_id,seconds):
        job = self.job_status(job_id)
        if job['status']!='completed': raise ValueError('Wait until the render is completed.')
        source = self.scoped(job['output'],'Exports')
        bounded(seconds,0,max(0,probe(str(source))['duration']-.04),'seconds')
        result = subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-ss',str(seconds),
                                 *LOCAL_MEDIA_INPUT,'-i',str(source),'-frames:v','1','-vf','scale=640:-2',
                                 '-f','image2pipe','-vcodec','mjpeg','pipe:1'],capture_output=True,
                                timeout=60,**subprocess_options())
        if result.returncode or not result.stdout: raise ValueError('Could not extract a preview frame.')
        return result.stdout

    def open_in_editor(self,id_):
        self.get_project(id_)
        project = str(self.project_file(id_))
        if getattr(sys,'frozen',False):
            executable = Path(sys.executable).parent.parent/'SoftenantVideoStudio.exe'
            if not executable.is_file(): raise ValueError('Keep the MCP folder beside SoftenantVideoStudio.exe.')
            command = [str(executable),'--project',project]
        else:
            command = [sys.executable,str(Path(__file__).resolve().parent.parent/'main.py'),'--project',project]
        subprocess.Popen(command,**subprocess_options())
        return {'opened':True,'project_file':f'Projects/{id_}.svs'}

    def recording_devices(self):
        if not self.allow_recording: raise ValueError('Recording is disabled. Start the service with --allow-recording locally.')
        self.devices = (monitors(),microphones())
        return {'monitors':[{'monitor_id':i,**asdict(m)} for i,m in enumerate(self.devices[0])],
                'microphones':[{'microphone_id':i,'name':m} for i,m in enumerate(self.devices[1])]}

    def start_recording(self,monitor_id,microphone_id=None,max_minutes=10):
        if not self.allow_recording: raise ValueError('Recording is disabled in this service.')
        bounded(max_minutes,1,60,'max_minutes')
        with self.lock:
            if self.recording and self.recording['status'] in ('recording','stopping'):
                raise ValueError('A recording is already active.')
            if not self.devices: raise ValueError('Call list_recording_devices first.')
            screens,mics = self.devices
            if monitor_id not in range(len(screens)): raise ValueError('Invalid monitor ID.')
            if microphone_id is not None and microphone_id not in range(len(mics)): raise ValueError('Invalid microphone ID.')
            id_ = uid()
            relative = f'Media/recording-{id_}.mp4'
            backend = ScreenRecorder()
            backend.start(screens[monitor_id],mics[microphone_id] if microphone_id is not None else '',
                          self.scoped(relative,'Media',False))
            state = {'recording_id':id_,'status':'recording','media_path':relative,'error':'',
                     'backend':backend,'started':time.monotonic()}
            self.recording = state
            print(f'RECORDING STARTED: monitor {monitor_id}, microphone {microphone_id}, limit {max_minutes} minutes',file=sys.stderr,flush=True)
            def monitor():
                while True:
                    with self.lock:
                        try:
                            if time.monotonic()-state['started']>=max_minutes*60 and not backend.stopping:
                                backend.stop();state['status']='stopping'
                            result = backend.poll()
                            if result:
                                state['status'] = 'completed'
                                print('RECORDING SAVED: '+relative,file=sys.stderr,flush=True)
                                break
                        except Exception as error:
                            state['status'],state['error'] = 'failed',str(error)[-2000:]
                            break
                    time.sleep(.2)
            thread = threading.Thread(target=monitor,daemon=True)
            state['thread'] = thread
            thread.start()
            return self.recording_status()

    def recording_status(self):
        with self.lock:
            if not self.recording: return {'status':'idle'}
            return {k:v for k,v in self.recording.items() if k not in ('backend','thread','started')}

    def stop_recording(self,id_):
        with self.lock:
            if not self.recording or self.recording['recording_id']!=id_: raise ValueError('Recording not found.')
            if self.recording['status']=='recording':
                self.recording['backend'].stop()
                self.recording['status']='stopping'
            return self.recording_status()

    def close(self):
        with self.lock:
            for job in self.jobs.values(): job['renderer'].cancel()
            if self.recording and self.recording['status']=='recording':
                self.stop_recording(self.recording['recording_id'])
            threads = [j['thread'] for j in self.jobs.values()]
            if self.recording: threads.append(self.recording['thread'])
        for thread in threads: thread.join(timeout=10)
        if self.recording and self.recording['thread'].is_alive():
            with self.lock: self.recording['backend'].cleanup()
