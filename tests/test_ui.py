import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from studio.app import MainWindow, STYLE
from studio.model import Clip


def test_inspector_timeline_undo_and_project_settings(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName('SoftenantTests')
    app.setApplicationName('TestStudio')
    app.setStyleSheet(STYLE)
    window = MainWindow(recover=False)
    window.autosave_path = tmp_path/'recovery.svs'
    clip = Clip(kind='text',track=4,text='Softenant Technologies',source_out=5)
    window.project.clips = [clip]
    window.selected = clip.id
    window.refresh()
    window.show()
    app.processEvents()
    values = window.inspector.values()
    values['start'] = 1
    window.apply_properties(values)
    assert window.get_clip().start==1
    window.undo()
    assert window.get_clip().start==0
    window.redo()
    assert window.get_clip().start==1
    window.seek(3)
    window.split()
    assert len(window.project.clips)==2
    window.autosave()
    assert window.autosave_path.exists()
    window.project_path = str(tmp_path/'saved.svs')
    assert window.save_project()
    assert not window.dirty
    if os.environ.get('STUDIO_SCREENSHOT'):
        window.grab().save(os.environ['STUDIO_SCREENSHOT'])
    window.close()
    app.processEvents()


def test_scrollbars_and_recording_dialog(tmp_path):
    from PySide6.QtCore import Qt
    from studio.recording import RecordingDialog
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName('SoftenantTests')
    app.setApplicationName('TestStudio')
    window = MainWindow(recover=False)
    window.autosave_path = tmp_path/'recovery.svs'
    window.resize(800,600)
    window.show()
    app.processEvents()
    assert window.canvas.currentIndex()==0
    assert window.timeline.horizontalScrollBarPolicy()==Qt.ScrollBarAlwaysOn
    assert window.page_scroll.horizontalScrollBar().maximum()>0
    assert window.page_scroll.verticalScrollBar().maximum()>0
    dialog = RecordingDialog(window)
    assert dialog.mic_box.itemText(0)=='No microphone'
    assert not dialog.active()
    assert not dialog.stop_button.isEnabled()
    assert dialog.result_path==''
    dialog.devices_worker.wait(25000)
    app.processEvents()
    dialog.reject()
    window.close()
    app.processEvents()


def test_external_mcp_edits_refresh_and_protect_local_changes(tmp_path,monkeypatch):
    from studio.mcp_service import StudioService
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName('SoftenantTests')
    app.setApplicationName('TestStudio')
    service = StudioService(tmp_path/'workspace')
    data = service.create_project('Shared project')
    window = MainWindow(recover=False)
    window.autosave_path = tmp_path/'recovery.svs'
    window.load_project_file(service.project_file(data['project_id']))
    data = service.add_title(data['project_id'],data['revision'],'MCP title',0,2)
    window.reload_external_changes()
    assert window.project.clips[0].text=='MCP title'
    window.project.clips[0].text='Unsaved local title'
    window.dirty = True
    data = service.update_clip(data['project_id'],data['revision'],data['clips'][0]['id'],{'text':'New remote title'})
    window.reload_external_changes()
    assert window.project.clips[0].text=='Unsaved local title'
    errors = []
    monkeypatch.setattr(window,'error',errors.append)
    assert not window.save_project()
    assert errors and 'changed' in errors[0]
    assert service.get_project(data['project_id'])['clips'][0]['text']=='New remote title'
    window.dirty = False
    window.close()
    service.close()
