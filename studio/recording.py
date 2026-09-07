from pathlib import Path
from datetime import datetime
import time
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
                              QComboBox, QPushButton, QFileDialog, QMessageBox)
from .capture import ScreenRecorder, monitors, microphones


class DevicesWorker(QThread):
    found = Signal(object)
    def run(self):
        try: self.found.emit(microphones())
        except Exception: self.found.emit([])


class RecordingDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Record screen — Softenant Video Studio')
        self.resize(540,350)
        self.result_path = ''
        self.backend = ScreenRecorder()
        try: self.screens = monitors()
        except Exception: self.screens = []
        layout = QVBoxLayout(self)
        intro = QLabel('Record a monitor, then add the recording to your timeline.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.screen_box = QComboBox()
        for i,screen in enumerate(self.screens):
            self.screen_box.addItem(f'{i+1}: {screen.name} ({screen.width} × {screen.height})')
        form.addRow('Monitor',self.screen_box)
        self.mic_box = QComboBox()
        self.mic_box.addItem('No microphone')
        form.addRow('Microphone',self.mic_box)
        self.size_box = QComboBox()
        self.size_box.addItem('Fit within 1920 × 1080',1920)
        self.size_box.addItem('Fit within 1280 × 720',1280)
        self.size_box.addItem('Native monitor resolution',0)
        form.addRow('Recording size',self.size_box)
        layout.addLayout(form)
        note = QLabel('The selected screen and its visible windows are captured.\n'
                      'You can minimize this recorder while it runs.\n'
                      'Choose a microphone for voice. System audio is not captured.')
        note.setObjectName('muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel('Finding microphones…' if self.screens else 'Screen recording requires a Windows desktop.')
        self.status.setObjectName('heading')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.start_button = QPushButton('Start recording…')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.start_recording)
        self.stop_button = QPushButton('Stop and add to timeline')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_recording)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        self.start_button.setEnabled(False)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.poll)
        self.devices_worker = DevicesWorker(self)
        self.devices_worker.found.connect(self.devices_ready)
        self.devices_worker.start()

    def devices_ready(self,devices):
        self.mic_box.addItems(devices)
        self.start_button.setEnabled(bool(self.screens))
        if self.screens: self.status.setText('Ready · 00:00')

    def active(self):
        return self.backend.process is not None

    def start_recording(self):
        if self.active() or self.screen_box.currentIndex()<0: return
        filename = f'Screen-recording-{datetime.now():%Y%m%d-%H%M%S}.mp4'
        path,_ = QFileDialog.getSaveFileName(self,'Save new screen recording',str(Path.home()/'Videos'/filename),'MP4 video (*.mp4)')
        if not path: return
        if not path.lower().endswith('.mp4'): path += '.mp4'
        mic = self.mic_box.currentText() if self.mic_box.currentIndex()>0 else ''
        try:
            self.backend.start(self.screens[self.screen_box.currentIndex()],mic,path,self.size_box.currentData())
        except Exception as e:
            QMessageBox.warning(self,'Recording error',str(e))
            return
        for w in (self.start_button,self.screen_box,self.mic_box,self.size_box): w.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText('Recording starting…')
        self.timer.start()

    def stop_recording(self):
        self.backend.stop()
        self.stop_button.setEnabled(False)
        self.status.setText('Finishing MP4 file…')

    def poll(self):
        try: result = self.backend.poll()
        except Exception as e:
            self.timer.stop()
            self.reset()
            QMessageBox.warning(self,'Recording error',str(e))
            return
        if result:
            self.timer.stop()
            self.result_path = result
            self.accept()
        elif self.active() and not self.backend.stopping:
            elapsed = int(time.monotonic()-self.backend.started)
            self.status.setText(f'RECORDING  ·  {elapsed//60:02}:{elapsed%60:02}')

    def reset(self):
        self.status.setText('Recording stopped')
        for w in (self.start_button,self.screen_box,self.mic_box,self.size_box): w.setEnabled(True)
        self.stop_button.setEnabled(False)

    def can_close(self):
        if self.active():
            QMessageBox.information(self,'Recording active','Use Stop and add to timeline before closing this window.')
            return False
        if self.devices_worker.isRunning():
            self.status.setText('Please wait for microphone detection to finish.')
            return False
        return True

    def reject(self):
        if self.can_close(): super().reject()

    def closeEvent(self,event):
        if self.can_close(): event.accept()
        else: event.ignore()
