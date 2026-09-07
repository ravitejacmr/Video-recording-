from __future__ import annotations
import copy
import os
from pathlib import Path
import sys
import tempfile
import threading
import hashlib
from PySide6.QtCore import Qt, QUrl, QThread, Signal, QTimer, QStandardPaths
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QFileDialog, QMessageBox, QListWidget, QTabWidget,
    QFormLayout, QDoubleSpinBox, QSpinBox, QLineEdit, QPlainTextEdit, QCheckBox,
    QComboBox, QScrollArea, QSlider, QProgressBar, QInputDialog)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from .model import Project, Clip, History, split_clip, uid
from .engine import Renderer, Cancelled, probe
from .timeline import Timeline
from .captions import read_srt, write_srt, transcribe_clip

STYLE = '''
QMainWindow, QWidget {background:#101722;color:#e4ecf7;font-family:'Segoe UI';font-size:12px;}
QMenuBar, QMenu, QToolBar {background:#182232;spacing:8px;}
QPushButton {background:#25344a;border:1px solid #3a4b62;border-radius:5px;padding:7px 11px;}
QPushButton:hover {background:#354c68;} QPushButton:disabled {color:#58687a;}
QPushButton#primary {background:#168f81;border:1px solid #28bca8;font-weight:600;}
QLineEdit,QPlainTextEdit,QSpinBox,QDoubleSpinBox,QComboBox,QListWidget {background:#182334;border:1px solid #35465d;border-radius:3px;padding:4px;}
QListWidget::item {padding:7px;} QListWidget::item:selected {background:#265565;}
QTabBar::tab {background:#1c293b;padding:8px;} QTabBar::tab:selected {background:#315168;}
QLabel#heading {font-size:18px;font-weight:700;} QLabel#muted {color:#91a4bc;}
QProgressBar {border:1px solid #35465d;text-align:center;} QProgressBar::chunk {background:#169e8c;}
QSplitter::handle {background:#29364a;}
QScrollBar:horizontal {background:#142033;height:16px;}
QScrollBar:vertical {background:#142033;width:16px;}
QScrollBar::handle {background:#57748f;border-radius:4px;min-width:28px;min-height:28px;}
QScrollBar::handle:hover {background:#7a9ab7;}
'''


class Worker(QThread):
    progress = Signal(int, str)
    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, function, cancel, parent=None):
        super().__init__(parent)
        self.function, self.cancel_function = function, cancel

    def run(self):
        try:
            self.done.emit(self.function(self.progress.emit))
        except Cancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))


class Inspector(QWidget):
    applyRequested = Signal(dict)

    def __init__(self):
        super().__init__()
        self.controls = {}
        layout = QVBoxLayout(self)
        title = QLabel('Clip inspector')
        title.setObjectName('heading')
        layout.addWidget(title)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.form('Timing')
        self.text_field('name', 'Clip name')
        self.combo('track', 'Track', [('Video 1',0),('Video 2',1),('Audio 1',2),('Audio 2',3),('Titles',4)])
        for key, label, low, high, val in [('start','Timeline start (s)',0,86400,0),
                ('source_in','Source in (s)',0,86400,0),('source_out','Source out (s)',.04,86400,5),
                ('speed','Playback speed',.25,4,1),('volume','Audio volume',0,4,1),
                ('fade_in','Fade in (s)',0,3600,0),('fade_out','Fade out (s)',0,3600,0)]:
            self.number(key,label,low,high,val)
        self.check('muted','Mute this clip')
        self.form('Transform')
        self.number('scale','Scale',.05,2,1)
        self.number('x','X offset (canvas widths)',-2,2,0)
        self.number('y','Y offset (canvas heights)',-2,2,0)
        self.number('opacity','Opacity',0,1,1)
        self.combo('rotation','Rotation',[(f'{r}°',r) for r in (0,90,180,270)])
        self.number('crop','Crop each edge (fraction)',0,.45,0)
        self.check('animate','Animate X/Y from start to end')
        self.number('end_x','End X offset',-2,2,0)
        self.number('end_y','End Y offset',-2,2,0)
        self.form('Effects')
        self.number('brightness','Brightness',-1,1,0)
        self.number('contrast','Contrast',0,3,1)
        self.number('saturation','Saturation',0,3,1)
        self.number('blur','Blur',0,20,0)
        self.check('chroma','Remove key colour (green screen)')
        self.text_field('key_color','Key colour (#RRGGBB)')
        self.number('similarity','Key similarity',.01,1,.15)
        self.file_field('lut','Colour LUT (.cube)','Cube LUT (*.cube)')
        self.form('Text')
        self.controls['text'] = QPlainTextEdit()
        self.controls['text'].setMaximumHeight(140)
        self.current.addRow('Title / caption',self.controls['text'])
        self.number('font_size','Font size at 1920px',8,240,56,integer=True)
        self.text_field('color','Text colour (#RRGGBB)')
        self.check('text_box','Dark background behind text')
        self.file_field('font','Custom font','Fonts (*.ttf *.otf)')
        button = QPushButton('Apply clip changes')
        button.setObjectName('primary')
        button.clicked.connect(lambda: self.applyRequested.emit(self.values()))
        layout.addWidget(button)
        note = QLabel('Apply changes, then render a new preview.\nX/Y values are fractions of the canvas.\nFades also fade the clip’s audio.')
        note.setObjectName('muted')
        layout.addWidget(note)
        self.setEnabled(False)

    def form(self, name):
        page = QWidget()
        self.current = QFormLayout(page)
        self.current.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll,name)

    def number(self,key,label,low,high,value,integer=False):
        w = QSpinBox() if integer else QDoubleSpinBox()
        w.setRange(low,high)
        if not integer:
            w.setDecimals(3)
            w.setSingleStep(.1)
        w.setValue(value)
        self.controls[key] = w
        self.current.addRow(label,w)

    def text_field(self,key,label):
        self.controls[key] = QLineEdit()
        self.current.addRow(label,self.controls[key])

    def check(self,key,label):
        self.controls[key] = QCheckBox(label)
        self.current.addRow(self.controls[key])

    def combo(self,key,label,items):
        w = QComboBox()
        for label_, data in items:
            w.addItem(label_,data)
        self.controls[key] = w
        self.current.addRow(label,w)

    def file_field(self,key,label,filter_):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0,0,0,0)
        edit, button = QLineEdit(), QPushButton('…')
        button.setMaximumWidth(34)
        def browse():
            path,_ = QFileDialog.getOpenFileName(self,label,'',filter_)
            if path:
                edit.setText(path)
        button.clicked.connect(browse)
        h.addWidget(edit)
        h.addWidget(button)
        self.controls[key] = edit
        self.current.addRow(label,row)

    def load(self,clip):
        self.setEnabled(clip is not None)
        if clip is None:
            return
        for key,w in self.controls.items():
            value = getattr(clip,key)
            if isinstance(w,QCheckBox): w.setChecked(value)
            elif isinstance(w,QComboBox): w.setCurrentIndex(w.findData(value))
            elif isinstance(w,(QDoubleSpinBox,QSpinBox)): w.setValue(value)
            elif isinstance(w,QPlainTextEdit): w.setPlainText(value)
            else: w.setText(value)

    def values(self):
        values = {}
        for key,w in self.controls.items():
            if isinstance(w,QCheckBox): value = w.isChecked()
            elif isinstance(w,QComboBox): value = w.currentData()
            elif isinstance(w,(QDoubleSpinBox,QSpinBox)): value = w.value()
            elif isinstance(w,QPlainTextEdit): value = w.toPlainText()
            else: value = w.text()
            values[key] = value
        return values


class MainWindow(QMainWindow):
    def __init__(self, recover=True):
        super().__init__()
        self.project, self.history = Project(), History()
        self.selected, self.project_path, self.dirty = '', '', False
        self.saved_revision = None
        self.worker, self.render_engine = None, None
        self.preview_offset, self.preview_valid = 0, False
        self.playhead, self.source_clip = 0, None
        self.temp = tempfile.TemporaryDirectory(prefix='softenant-preview-')
        state = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
        state.mkdir(parents=True,exist_ok=True)
        self.autosave_path = state / 'recovery.svs'
        self.setWindowTitle('Softenant Video Studio')
        self.resize(1440,920)
        self.build_ui()
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.autosave)
        self.timer.start(30000)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.reload_external_changes)
        self.sync_timer.start(2000)
        if recover and self.autosave_path.is_file():
            QTimer.singleShot(0,self.recover)

    def action(self,menu,label,function,shortcut=None):
        a = QAction(label,self)
        a.triggered.connect(function)
        if shortcut: a.setShortcut(QKeySequence(shortcut))
        menu.addAction(a)
        return a

    def build_ui(self):
        filemenu = self.menuBar().addMenu('File')
        self.action(filemenu,'New project',self.new_project,'Ctrl+N')
        self.action(filemenu,'Open project…',self.open_project,'Ctrl+O')
        self.action(filemenu,'Save project',self.save_project,'Ctrl+S')
        self.action(filemenu,'Save project as…',lambda:self.save_project(True),'Ctrl+Shift+S')
        filemenu.addSeparator()
        self.action(filemenu,'Import media…',self.import_media,'Ctrl+I')
        self.action(filemenu,'Record screen…',self.record_screen,'Ctrl+R')
        self.action(filemenu,'Open MCP workspace',self.open_mcp_workspace)
        self.action(filemenu,'Open MCP project…',self.open_mcp_project)
        self.action(filemenu,'Import subtitles (.srt)…',self.import_srt)
        self.action(filemenu,'Export subtitles (.srt)…',self.export_srt)
        self.action(filemenu,'Export video…',self.export_video,'Ctrl+E')
        edit = self.menuBar().addMenu('Edit')
        self.action(edit,'Undo',self.undo,'Ctrl+Z')
        self.action(edit,'Redo',self.redo,'Ctrl+Shift+Z')
        self.action(edit,'Split at playhead',self.split,'Ctrl+B')
        self.action(edit,'Duplicate selected',self.duplicate,'Ctrl+D')
        self.action(edit,'Delete selected',self.delete_clip,'Ctrl+Delete')
        self.action(edit,'Relink selected media…',self.relink)
        self.action(edit,'Automatic captions for selected clip…',self.auto_captions)
        helpmenu = self.menuBar().addMenu('Help')
        self.action(helpmenu,'Quick guide',self.help)
        self.action(helpmenu,'Open recovery folder',lambda: self.open_folder(self.autosave_path.parent))
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16,12,16,12)
        top = QHBoxLayout()
        heading = QLabel('SOFTENANT  /  VIDEO STUDIO')
        heading.setObjectName('heading')
        top.addWidget(heading)
        top.addStretch()
        record = QPushButton('Record screen')
        record.clicked.connect(self.record_screen)
        top.addWidget(record)
        self.canvas = QComboBox()
        for text,shape in [('1080p · Landscape',(1920,1080)),('720p · Landscape',(1280,720)),
                           ('4K · Landscape',(3840,2160)),('1080p · Portrait',(1080,1920)),('Square',(1080,1080))]:
            self.canvas.addItem(text,shape)
        self.canvas.activated.connect(self.change_settings)
        top.addWidget(self.canvas)
        self.fps = QComboBox()
        self.fps.addItems(['24','25','30','60'])
        self.fps.setCurrentText('30')
        self.fps.activated.connect(self.change_settings)
        top.addWidget(self.fps)
        export = QPushButton('Export MP4')
        export.setObjectName('primary')
        export.clicked.connect(self.export_video)
        top.addWidget(export)
        outer.addLayout(top)
        middle = QSplitter()
        left = QWidget()
        left.setMinimumWidth(190)
        l = QVBoxLayout(left)
        l.addWidget(QLabel('PROJECT CLIPS'))
        self.bin = QListWidget()
        self.bin.currentRowChanged.connect(self.bin_selected)
        l.addWidget(self.bin)
        for label,fn in [('+ Import video / audio / image',self.import_media),('+ Add title',self.add_title),
                         ('Import SRT captions',self.import_srt),('Play selected source',self.play_source),
                         ('Relink selected media',self.relink)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            l.addWidget(b)
        middle.addWidget(left)
        center = QWidget()
        c = QVBoxLayout(center)
        self.preview_label = QLabel('PREVIEW  ·  Add media to begin')
        self.preview_label.setObjectName('muted')
        c.addWidget(self.preview_label)
        self.video = QVideoWidget()
        self.video.setMinimumSize(360,220)
        c.addWidget(self.video,1)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.position_changed)
        self.player.errorOccurred.connect(lambda *_: self.statusBar().showMessage(self.player.errorString(),15000))
        controls = QHBoxLayout()
        play = QPushButton('▶ / Ⅱ')
        play.clicked.connect(self.toggle_play)
        controls.addWidget(play)
        self.time_label = QLabel('00:00.00')
        controls.addWidget(self.time_label)
        self.preview_button = QPushButton('Render 12-second preview')
        self.preview_button.clicked.connect(self.render_preview)
        controls.addWidget(self.preview_button)
        c.addLayout(controls)
        self.seekbar = QSlider(Qt.Horizontal)
        self.seekbar.setRange(0,1000)
        self.seekbar.sliderMoved.connect(lambda x:self.seek(x/1000*self.project.duration))
        c.addWidget(self.seekbar)
        middle.addWidget(center)
        self.inspector = Inspector()
        self.inspector.setMinimumWidth(340)
        self.inspector.applyRequested.connect(self.apply_properties)
        middle.addWidget(self.inspector)
        middle.setSizes([225,750,365])
        outer.addWidget(middle,1)
        strip = QHBoxLayout()
        strip.addWidget(QLabel('TIMELINE  ·  Drag clips to move • Click ruler to seek'))
        strip.addStretch()
        for label,fn in [('Split',self.split),('Duplicate',self.duplicate),('Delete',self.delete_clip),('Undo',self.undo),('Redo',self.redo)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            strip.addWidget(b)
        strip.addWidget(QLabel('Zoom'))
        zoom = QSlider(Qt.Horizontal)
        zoom.setRange(10,160)
        zoom.setValue(55)
        zoom.setFixedWidth(100)
        zoom.valueChanged.connect(self.zoom_timeline)
        strip.addWidget(zoom)
        outer.addLayout(strip)
        self.timeline = Timeline()
        self.timeline.selectedClip.connect(self.select)
        self.timeline.movedClip.connect(self.move_clip)
        self.timeline.seek.connect(self.seek)
        outer.addWidget(self.timeline)
        status = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setValue(0)
        status.addWidget(self.progress)
        self.cancel_button = QPushButton('Cancel task')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_task)
        status.addWidget(self.cancel_button)
        outer.addLayout(status)
        root.setMinimumSize(1060,800)
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setWidget(root)
        self.setCentralWidget(self.page_scroll)
        self.statusBar().showMessage('Ready. Import media, edit clips, render a preview, then export.')

    def get_clip(self):
        return next((c for c in self.project.clips if c.id==self.selected),None)

    def open_mcp_workspace(self):
        from .mcp_service import StudioService
        service = StudioService()
        self.open_folder(service.root)
        service.close()

    def open_mcp_project(self):
        if not self.can_edit() or not self.confirm_discard(): return
        from .mcp_service import workspace_path
        path,_ = QFileDialog.getOpenFileName(self,'Open MCP project',str(workspace_path()/'Projects'),'Softenant project (*.svs)')
        if path: self.load_project_file(path)

    def load_project_file(self,path):
        try:
            raw = Path(path).read_bytes()
            project = Project.load(path)
            if Path(path).read_bytes()!=raw: raise ValueError('Project changed while opening. Try again.')
        except Exception as e: return self.error(str(e))
        self.project,self.project_path,self.history = project,str(path),History()
        self.saved_revision = hashlib.sha256(raw).hexdigest()
        self.selected,self.playhead = '',0
        self.changed()
        self.dirty = False
        self.refresh()
        self.seek(0)

    def reload_external_changes(self):
        if not self.project_path or not self.saved_revision or self.busy(): return
        try: current = hashlib.sha256(Path(self.project_path).read_bytes()).hexdigest()
        except OSError: return
        if current==self.saved_revision: return
        if self.dirty:
            self.statusBar().showMessage('This project changed through MCP. Save your edits as a new project or reopen it.')
            return
        self.load_project_file(self.project_path)
        self.statusBar().showMessage('Project refreshed from MCP changes.')

    def busy(self):
        return self.worker is not None

    def can_edit(self):
        if self.busy():
            self.statusBar().showMessage('Wait for the current task, or cancel it first.')
            return False
        return True

    def checkpoint(self):
        self.history.record(self.project)

    def changed(self):
        self.dirty = True
        self.preview_valid = False
        self.source_clip = None
        self.player.stop()
        self.player.setSource(QUrl())
        self.preview_label.setText('PREVIEW  ·  Changes pending — render to see the edit')
        self.refresh()

    def refresh(self):
        self.timeline.refresh(self.project,self.selected)
        self.bin.blockSignals(True)
        self.bin.clear()
        for c in self.project.clips:
            self.bin.addItem(f'{c.kind.upper()}  {c.name}\n{c.start:.2f}s  ·  {c.duration:.2f}s')
            if c.id == self.selected: self.bin.setCurrentRow(self.bin.count()-1)
        self.bin.blockSignals(False)
        self.inspector.load(self.get_clip())
        shape = (self.project.width,self.project.height)
        self.canvas.setCurrentIndex(next((i for i in range(self.canvas.count())
                                         if tuple(self.canvas.itemData(i))==shape),-1))
        self.fps.setCurrentText(str(self.project.fps))
        self.setWindowTitle(f'{"* " if self.dirty else ""}{self.project.name} — Softenant Video Studio')

    def select(self, id_):
        self.selected = id_
        self.inspector.load(self.get_clip())
        self.bin.blockSignals(True)
        for i,c in enumerate(self.project.clips):
            if c.id==id_: self.bin.setCurrentRow(i)
        self.bin.blockSignals(False)

    def bin_selected(self,row):
        if 0 <= row < len(self.project.clips):
            self.select(self.project.clips[row].id)
            self.timeline.refresh(self.project,self.selected)

    def import_media(self):
        if not self.can_edit(): return
        paths,_ = QFileDialog.getOpenFileNames(self,'Import media','','Media (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mp3 *.wav *.m4a *.aac *.flac *.ogg *.png *.jpg *.jpeg *.webp *.bmp);;All files (*)')
        if not paths: return
        # Probe asynchronously so a slow/corrupt file never freezes the interface.
        def load(progress):
            result = []
            for i,path in enumerate(paths):
                if cancel.is_set(): raise Cancelled()
                progress(int(i/len(paths)*100),'Reading media…')
                if Path(path).suffix.lower() in ('.png','.jpg','.jpeg','.webp','.bmp'):
                    from PIL import Image
                    with Image.open(path) as im: im.verify()
                    result.append((path,'image',5.0))
                else:
                    info = probe(path)
                    if info['duration']<=0 or not (info['video'] or info['audio']):
                        raise ValueError(f'Cannot read media: {path}')
                    result.append((path,'video' if info['video'] else 'audio',info['duration']))
            return result
        def done(result):
            self.checkpoint()
            for path,kind,duration in result:
                track = {'video':0,'image':1,'audio':2}[kind]
                start = max((c.end for c in self.project.clips if c.track==track),default=0) if kind=='video' else self.playhead
                clip = Clip(path=path,name=Path(path).name,kind=kind,track=track,start=start,source_out=duration)
                self.project.clips.append(clip)
                self.selected = clip.id
            self.changed()
        cancel = threading.Event()
        self.start_worker(load,cancel.set,done)

    def add_title(self):
        if not self.can_edit(): return
        text,ok = QInputDialog.getMultiLineText(self,'Add title','Text:','Softenant Technologies')
        if not ok or not text.strip(): return
        self.checkpoint()
        clip = Clip(kind='text',track=4,name='Title',text=text,start=self.playhead)
        self.project.clips.append(clip)
        self.selected = clip.id
        self.changed()

    def record_screen(self):
        if not self.can_edit(): return
        from .recording import RecordingDialog
        self.player.pause()
        dialog = RecordingDialog(self)
        if dialog.exec() and dialog.result_path:
            path = dialog.result_path
            cancel = threading.Event()
            def done(info):
                if not info['video'] or info['duration']<=0:
                    return self.error(f'The recording was saved but could not be imported: {path}')
                self.checkpoint()
                start = max((c.end for c in self.project.clips if c.track==0),default=0)
                clip = Clip(path=path,name=Path(path).name,start=start,source_out=info['duration'])
                self.project.clips.append(clip)
                self.selected = clip.id
                self.changed()
                self.statusBar().showMessage('Recording saved and added to V1.')
            self.start_worker(lambda progress:probe(path),cancel.set,done)
        dialog.deleteLater()

    def apply_properties(self,values):
        if not self.can_edit(): return
        clip = self.get_clip()
        if not clip: return
        proposed = copy.deepcopy(clip)
        for k,v in values.items(): setattr(proposed,k,v)
        try: proposed.validate()
        except Exception as e: return self.error(str(e))
        self.checkpoint()
        self.project.clips[self.project.clips.index(clip)] = proposed
        self.changed()

    def move_clip(self,id_,start,track):
        if not self.can_edit():
            self.timeline.refresh(self.project,self.selected)
            return
        clip = next(c for c in self.project.clips if c.id==id_)
        if clip.start!=start or clip.track!=track:
            self.checkpoint()
            clip.start,clip.track = start,track
            self.changed()
        else:
            self.timeline.refresh(self.project,self.selected)

    def split(self):
        if not self.can_edit(): return
        clip = self.get_clip()
        if not clip: return
        try: parts = split_clip(clip,self.playhead)
        except Exception as e: return self.error(str(e))
        self.checkpoint()
        index = self.project.clips.index(clip)
        self.project.clips[index:index+1] = parts
        self.changed()

    def duplicate(self):
        if not self.can_edit(): return
        clip = self.get_clip()
        if not clip: return
        self.checkpoint()
        new = copy.deepcopy(clip)
        new.id,new.start = uid(),clip.end
        self.project.clips.append(new)
        self.selected = new.id
        self.changed()

    def delete_clip(self):
        if not self.can_edit(): return
        clip = self.get_clip()
        if not clip: return
        self.checkpoint()
        self.project.clips.remove(clip)
        self.selected = ''
        self.changed()

    def undo(self):
        if self.can_edit() and self.history.undo_stack:
            self.project = self.history.undo(self.project)
            self.changed()

    def redo(self):
        if self.can_edit() and self.history.redo_stack:
            self.project = self.history.redo(self.project)
            self.changed()

    def relink(self):
        if not self.can_edit(): return
        clip = self.get_clip()
        if not clip or clip.kind=='text': return
        path,_ = QFileDialog.getOpenFileName(self,'Locate replacement media')
        if path:
            self.checkpoint()
            clip.path = path
            self.changed()

    def change_settings(self,*_):
        if not self.can_edit(): return self.refresh()
        shape = self.canvas.currentData()
        if shape:
            self.checkpoint()
            self.project.width,self.project.height = shape
            self.project.fps = int(self.fps.currentText())
            self.changed()

    def zoom_timeline(self,value):
        self.timeline.zoom = value
        self.timeline.refresh(self.project,self.selected)

    def seek(self,time):
        self.playhead = max(0,min(time,self.project.duration))
        self.timeline.set_playhead(self.playhead)
        self.time_label.setText(f'{int(self.playhead//60):02}:{self.playhead%60:05.2f}')
        self.seekbar.setValue(round(self.playhead/max(.001,self.project.duration)*1000))
        if self.preview_valid:
            pos = (self.playhead-self.preview_offset)*1000
            if 0<=pos<=self.player.duration(): self.player.setPosition(round(pos))

    def position_changed(self,position):
        if self.source_clip:
            clip = self.source_clip
            if position/1000 > clip.source_out:
                self.player.pause()
            t = clip.start + (position/1000-clip.source_in)/clip.speed
        elif self.preview_valid:
            t = position/1000+self.preview_offset
        else: return
        self.playhead = max(0,t)
        self.timeline.set_playhead(self.playhead)
        self.time_label.setText(f'{int(self.playhead//60):02}:{self.playhead%60:05.2f}')
        self.seekbar.setValue(round(self.playhead/max(.001,self.project.duration)*1000))

    def toggle_play(self):
        if self.player.playbackState()==QMediaPlayer.PlayingState: self.player.pause()
        else: self.player.play()

    def play_source(self):
        clip = self.get_clip()
        if not clip or clip.kind not in ('video','audio'): return
        self.preview_valid = False
        self.source_clip = copy.deepcopy(clip)
        self.player.setSource(QUrl.fromLocalFile(clip.path))
        self.player.setPosition(round(clip.source_in*1000))
        self.player.setPlaybackRate(clip.speed)
        self.preview_label.setText('SOURCE  ·  Original media, without applied effects')
        self.player.play()

    def start_worker(self,function,cancel,done):
        if self.busy(): return
        self.worker = Worker(function,cancel,self)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(done)
        self.worker.failed.connect(self.error)
        self.worker.cancelled.connect(lambda:self.statusBar().showMessage('Task cancelled.'))
        self.worker.finished.connect(self.worker_finished)
        self.cancel_button.setEnabled(True)
        self.preview_button.setEnabled(False)
        self.progress.setValue(0)
        self.worker.start()

    def on_progress(self,value,message):
        self.progress.setValue(value)
        self.statusBar().showMessage(message)

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        self.cancel_button.setEnabled(False)
        self.preview_button.setEnabled(True)
        if worker: worker.deleteLater()

    def cancel_task(self):
        if self.worker:
            self.worker.cancel_function()
            self.statusBar().showMessage('Cancelling… model downloads may take time to stop.')

    def render_preview(self):
        if not self.can_edit(): return
        self.render(preview=True)

    def export_video(self):
        if not self.can_edit(): return
        path,_ = QFileDialog.getSaveFileName(self,'Export MP4',self.project.name+'.mp4','MP4 video (*.mp4)')
        if path:
            if not path.lower().endswith('.mp4'): path += '.mp4'
            self.render(output=path)

    def render(self,preview=False,output=''):
        try: self.project.validate()
        except Exception as e: return self.error(str(e))
        if output and self.project_path and Path(output).resolve()==Path(self.project_path).resolve():
            return self.error('Choose an export filename different from the project file.')
        snapshot = copy.deepcopy(self.project)
        start = min(self.playhead,max(0,snapshot.duration-.1)) if preview else 0
        self.player.stop()
        self.player.setSource(QUrl())
        if preview: output = str(Path(self.temp.name)/f'preview-{uid()}.mp4')
        engine = Renderer()
        def done(path):
            self.progress.setValue(100)
            if preview:
                self.preview_offset,self.preview_valid,self.source_clip = start,True,None
                self.player.setPlaybackRate(1)
                self.player.setSource(QUrl.fromLocalFile(path))
                self.preview_label.setText(f'EDITED PREVIEW  ·  {start:.1f}s–{min(start+12,snapshot.duration):.1f}s · draft resolution')
                self.player.play()
            else:
                QMessageBox.information(self,'Export complete',f'Video saved to:\n{path}')
            self.statusBar().showMessage('Preview ready.' if preview else 'Export complete.')
        self.start_worker(lambda progress:engine.render(snapshot,output,progress,preview=preview,start=start,
                                                       length=12 if preview else None),engine.cancel,done)

    def import_srt(self):
        if not self.can_edit(): return
        path,_ = QFileDialog.getOpenFileName(self,'Import captions (times start at project zero)','','SRT captions (*.srt)')
        if not path: return
        try: clips = read_srt(path)
        except Exception as e: return self.error(str(e))
        self.checkpoint()
        self.project.clips.extend(clips)
        self.selected = clips[0].id
        self.changed()

    def export_srt(self):
        path,_ = QFileDialog.getSaveFileName(self,'Export all text clips as SRT','captions.srt','SRT captions (*.srt)')
        if path:
            try: write_srt(self.project.clips,path)
            except Exception as e: self.error(str(e))

    def auto_captions(self):
        if not self.can_edit(): return
        clip = self.get_clip()
        if not clip or clip.kind not in ('video','audio'):
            return self.error('Select a video or audio clip first.')
        snapshot = copy.deepcopy(clip)
        cancel = threading.Event()
        def done(clips):
            if not clips:
                return self.error('No speech was detected in this clip.')
            self.checkpoint()
            self.project.clips.extend(clips)
            self.changed()
        self.start_worker(lambda progress:transcribe_clip(snapshot,progress,cancel),cancel.set,done)

    def confirm_discard(self):
        if not self.dirty: return True
        result = QMessageBox.question(self,'Unsaved project','Save your changes?',
                                      QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
        if result==QMessageBox.Cancel: return False
        return self.save_project() if result==QMessageBox.Save else True

    def new_project(self):
        if not self.can_edit() or not self.confirm_discard(): return
        self.player.stop()
        self.player.setSource(QUrl())
        self.project,self.history = Project(),History()
        self.project_path,self.selected,self.dirty = '','',False
        self.saved_revision = None
        self.preview_valid,self.source_clip,self.playhead = False,None,0
        self.autosave_path.unlink(missing_ok=True)
        self.refresh()
        self.seek(0)
        self.preview_label.setText('PREVIEW  ·  Add media to begin')

    def open_project(self):
        if not self.can_edit() or not self.confirm_discard(): return
        path,_ = QFileDialog.getOpenFileName(self,'Open project','','Softenant project (*.svs)')
        if not path: return
        self.load_project_file(path)
        self.autosave_path.unlink(missing_ok=True)
        self.refresh()
        self.seek(0)

    def save_project(self,save_as=False):
        path = self.project_path
        if save_as or not path:
            path,_ = QFileDialog.getSaveFileName(self,'Save project',self.project.name+'.svs','Softenant project (*.svs)')
            if not path: return False
            if not path.lower().endswith('.svs'): path += '.svs'
        try:
            if save_as or not self.project_path: self.project.name = Path(path).stem
            expected = self.saved_revision if path==self.project_path else None
            self.project.save(path,expected_revision=expected)
            self.saved_revision = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            self.project_path,self.dirty = path,False
            self.autosave_path.unlink(missing_ok=True)
            self.refresh()
            self.statusBar().showMessage('Project saved. Keep its source media available.')
            return True
        except Exception as e:
            self.error(str(e))
            return False

    def autosave(self):
        if not self.dirty: return
        try: self.project.save(self.autosave_path)
        except Exception as e: self.statusBar().showMessage(f'Autosave failed: {e}')

    def recover(self):
        if QMessageBox.question(self,'Recover project','Restore the autosaved project from your last session?')==QMessageBox.Yes:
            try:
                self.project = Project.load(self.autosave_path)
                self.changed()
            except Exception as e: self.error(str(e))
        else:
            self.autosave_path.unlink(missing_ok=True)

    def open_folder(self,path):
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def error(self,text):
        self.statusBar().showMessage('The operation could not be completed.')
        QMessageBox.warning(self,'Softenant Video Studio',text)

    def help(self):
        QMessageBox.information(self,'Quick guide',
            '1. Import videos, audio or images. Videos append on V1.\n'
            '2. Drag clips on the timeline; click the ruler to place the playhead.\n'
            '3. Select a clip, adjust the inspector, then click Apply.\n'
            '4. Use Split, Duplicate, Delete and Undo to assemble your edit.\n'
            '5. Put logos or picture-in-picture clips on V2; reduce their Scale.\n'
            '6. Overlap V2 and V1 with a fade for a dissolve. Same-track clips layer in import order.\n'
            '7. Add titles or import SRT captions; use X/Y offsets to position them.\n'
            '8. Render a 12-second preview from the playhead, then Export MP4.\n\n'
            'Use Record screen (Ctrl+R) to record a monitor with an optional microphone.\n'
            'The timeline scrolls horizontally; smaller windows scroll in both directions.\n'
            'Autosave runs every 30 seconds. Save .svs projects and keep source media.\n'
            'Automatic captions are optional: run Enable-Auto-Captions.bat first.\n'
            'This version uses CPU export and rendered previews. See README for limitations.')

    def closeEvent(self,event):
        if self.busy():
            self.error('Cancel the current task and wait for it to finish before closing.')
            event.ignore()
            return
        if not self.confirm_discard():
            event.ignore()
            return
        self.timer.stop()
        self.sync_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.autosave_path.unlink(missing_ok=True)
        try: self.temp.cleanup()
        except PermissionError: pass  # Windows decoder may release its handle asynchronously.
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName('Softenant')
    app.setApplicationName('Video Studio')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    smoke = os.environ.get('STUDIO_SMOKE_TEST') == '1'
    window = MainWindow(recover=not smoke)
    if '--project' in sys.argv:
        index = sys.argv.index('--project')
        if index+1<len(sys.argv): window.load_project_file(sys.argv[index+1])
    window.show()
    if smoke:
        QTimer.singleShot(750, app.quit)
    return app.exec()
