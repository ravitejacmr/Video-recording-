from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QBrush, QPen, QPainter
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem

TRACKS = [4, 1, 0, 2, 3]
NAMES = {4: 'T   TITLES', 1: 'V2   OVERLAY', 0: 'V1   VIDEO', 2: 'A1   AUDIO', 3: 'A2   MUSIC'}
COLORS = {4: '#ad77ed', 1: '#517cdb', 0: '#27b5a0', 2: '#e6a748', 3: '#e0805c'}
LEFT, TOP, ROW = 110, 30, 52


class ClipItem(QGraphicsRectItem):
    def __init__(self, clip, timeline):
        super().__init__(0, 0, max(12, clip.duration * timeline.zoom), ROW-10)
        self.clip, self.timeline = clip, timeline
        self.setPos(LEFT + clip.start * timeline.zoom, TOP + TRACKS.index(clip.track) * ROW + 5)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        self.setBrush(QBrush(QColor(COLORS[clip.track])))
        self.setPen(QPen(QColor('#e7fff9') if clip.id == timeline.selected else QColor('#182330'), 2))
        self.setToolTip(f'{clip.name}\n{clip.start:.2f}–{clip.end:.2f}s • {clip.speed:g}×')
        label = timeline.scene().addText(clip.name[:44])
        label.setDefaultTextColor(QColor('#08111d'))
        label.setParentItem(self)
        label.setPos(6, 4)
        label.setFlag(QGraphicsItem.ItemClipsToShape, True)
        self.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)

    def mousePressEvent(self, event):
        self.timeline.selected = self.clip.id
        self.timeline.selectedClip.emit(self.clip.id)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        start = max(0, (self.x()-LEFT)/self.timeline.zoom)
        start = round(start * self.timeline.project.fps)/self.timeline.project.fps
        row = max(0, min(4, round((self.y()-TOP-5)/ROW)))
        track = TRACKS[row]
        if (self.clip.kind == 'audio') != (track in (2, 3)):
            track = self.clip.track
        timeline, clip_id = self.timeline, self.clip.id
        QTimer.singleShot(0, lambda: timeline.movedClip.emit(clip_id, start, track))


class Timeline(QGraphicsView):
    selectedClip = Signal(str)
    movedClip = Signal(str, float, int)
    seek = Signal(float)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(320)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.zoom, self.selected, self.project, self.playhead = 55, '', None, 0
        self.line = None
        self.setBackgroundBrush(QBrush(QColor('#101722')))

    def refresh(self, project, selected=''):
        self.project, self.selected = project, selected
        self.scene().clear()
        end = max(20, project.duration+5)
        extent = LEFT + end * self.zoom
        self.scene().setSceneRect(0, 0, extent, TOP+ROW*5)
        step = 1 if self.zoom >= 45 else 5
        for t in range(0, int(end)+1, step):
            x = LEFT + t*self.zoom
            self.scene().addLine(x, TOP, x, TOP+ROW*5, QPen(QColor('#263143')))
            text = self.scene().addText(f'{t}s')
            text.setDefaultTextColor(QColor('#8092aa'))
            text.setPos(x, 0)
        for row, track in enumerate(TRACKS):
            y = TOP+row*ROW
            self.scene().addLine(0, y, extent, y, QPen(QColor('#344055')))
            text = self.scene().addText(NAMES[track])
            text.setDefaultTextColor(QColor(COLORS[track]))
            text.setPos(4, y+14)
        for clip in project.clips:
            self.scene().addItem(ClipItem(clip, self))
        self.line = self.scene().addLine(0, 0, 0, TOP+ROW*5, QPen(QColor('#ff626c'), 2))
        self.line.setZValue(100)
        self.set_playhead(self.playhead)

    def set_playhead(self, value):
        self.playhead = value
        if self.line:
            self.line.setPos(LEFT + value*self.zoom, 0)

    def mousePressEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        item = self.itemAt(event.position().toPoint())
        while item and item.parentItem():
            item = item.parentItem()
        if not isinstance(item, ClipItem) and point.x() >= LEFT:
            self.seek.emit(max(0, (point.x()-LEFT)/self.zoom))
        super().mousePressEvent(event)
