"""CC0 sprite-based desktop cat/dog. Offline, non-focus-stealing, CPU-only Qt paint."""
import json
import time
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPixmap, QCursor, QFont
from PyQt5.QtWidgets import QApplication, QWidget, QMenu
from pet_scenes import ACTIVITIES, DURATIONS, activity_title, draw_scene

ASSETS = Path(__file__).resolve().parent / 'assets/pets'


class DesktopPet(QWidget):
    requested = pyqtSignal()
    changed = pyqtSignal(str)
    hidden = pyqtSignal()
    positioned = pyqtSignal(int, int)
    moved = pyqtSignal()

    def __init__(self, kind='cat'):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle('候响 · 桌面伙伴')
        self.setFixedSize(320, 238)
        self.setCursor(Qt.OpenHandCursor)
        self.frames = {}
        self.kind = ''
        self.error = ''
        self.running = 0
        self.pending = 0
        self.roam = True
        self.bubble_visible = False
        self.stale = False
        self.celebrate_until = 0
        self.preview_action = None
        self.preview_until = 0
        self.preview_epoch = 0
        self.fixed_time = None
        self.epoch = time.monotonic()
        self.drag_origin = None
        self.dragged = False
        self.load(kind)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.update)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 35, area.bottom() - self.height() - 18)

    def load(self, kind):
        kind = kind if kind in ('cat', 'dog') else 'cat'
        if self.kind == kind and self.frames:
            return
        self.frames = {}
        self.error = ''
        try:
            manifest = json.loads((ASSETS / 'manifest.json').read_text())
            for name, entry in manifest['pets'][kind]['animations'].items():
                atlas = QPixmap(str(ASSETS / entry['file']))
                if atlas.isNull():
                    raise ValueError('动画文件无法读取：' + entry['file'])
                w, h = entry['cell']
                self.frames[name] = [atlas.copy(i*w, 0, w, h) for i in range(entry['frames'])]
            if not all(k in self.frames for k in ('idle', 'walk', 'run', 'jump')):
                raise ValueError('缺少必要的动画动作')
            self.kind = kind
            self.epoch = time.monotonic()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = str(exc)
            self.frames = {}
        self.update()

    def sync(self, sessions, stale=False):
        self.running = sum(s.status == 'running' and s.tracked for s in sessions)
        self.pending = sum(s.unread for s in sessions)
        self.stale = stale
        self.timer.setInterval(50 if self.running or self.pending or time.monotonic() < self.preview_until else 160)
        self.setToolTip(('小猫' if self.kind == 'cat' else '小狗') +
                        f' · {self.running} 项工作中 · {self.pending} 项等你确认\n拖动移动；单击查看；右键点播活动、切换或收起')
        self.update()

    def celebrate(self):
        self.preview_until = 0
        self.celebrate_until = time.monotonic() + 2.4
        self.update()

    def activity(self, at=None):
        t = self.fixed_time if self.fixed_time is not None else (time.monotonic() - self.epoch if at is None else at)
        celebrating = self.fixed_time is None and time.monotonic() < self.celebrate_until
        if celebrating:
            return 'celebrate', t, 1.
        if self.preview_action and time.monotonic() < self.preview_until:
            return self.preview_action, time.monotonic()-self.preview_epoch, 1.
        if not self.running or self.stale:
            return 'idle', t, 1.
        local = t % sum(DURATIONS)
        for action, duration in zip(ACTIVITIES, DURATIONS):
            if local < duration:
                # Brief ease at scene changes keeps props from popping abruptly.
                alpha = min(1., .25+local/.2, .25+(duration-local)/.2)
                return action, local, alpha
            local -= duration
        return 'idle', t, 1.

    def preview(self, action):
        if action not in ACTIVITIES:
            return
        self.preview_action = action
        self.preview_epoch = time.monotonic()
        self.preview_until = self.preview_epoch + 12
        self.timer.setInterval(50)
        self.update()

    def paintEvent(self, event):
        if not self.frames:
            return
        action, t, alpha = self.activity()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.save()
        painter.translate(self.width()/2, 160)
        painter.setOpacity(alpha)
        draw_scene(painter, self, action, t, self.roam and not self.bubble_visible)
        painter.restore()
        text = '连接待恢复' if self.stale else (f'{self.pending} 项等你确认' if self.pending else
                (f'{self.running} 项正在忙' if self.running else '我在这里等你'))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(35, 36, 44, 225))
        painter.drawRoundedRect(QRectF(55, 186, 210, 43), 16, 16)
        painter.setPen(QColor('#f0f0f5'))
        font = QFont('Noto Sans CJK SC')
        font.setPixelSize(11)
        painter.setFont(font)
        painter.drawText(QRectF(55, 190, 210, 18), Qt.AlignCenter, text)
        painter.setPen(QColor('#bdc0d3'))
        font.setPixelSize(10)
        painter.setFont(font)
        caption = activity_title(action, self.kind)
        if time.monotonic() < self.preview_until:
            caption = '动作预览 · ' + caption
        painter.drawText(QRectF(55, 208, 210, 16), Qt.AlignCenter, caption)
        painter.end()

    def keep_on_screen(self):
        screens = QApplication.screens()
        screen = next((s for s in screens if s.availableGeometry().intersects(self.geometry())), screens[0])
        a = screen.availableGeometry()
        self.move(min(max(self.x(), a.left()), a.right()-self.width()+1),
                  min(max(self.y(), a.top()), a.bottom()-self.height()+1))

    def showEvent(self, event):
        self.keep_on_screen()
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def moveEvent(self, event):
        self.moved.emit()
        super().moveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_origin = event.globalPos() - self.pos()
            self.drag_start = event.globalPos()
            self.dragged = False
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag_origin is not None and event.buttons() & Qt.LeftButton:
            if (event.globalPos() - self.drag_start).manhattanLength() > 5:
                self.dragged = True
            if self.dragged:
                self.move(event.globalPos() - self.drag_origin)
                self.keep_on_screen()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drag_origin is not None:
            if self.dragged:
                self.positioned.emit(self.x(), self.y())
            else:
                self.requested.emit()
            self.drag_origin = None
            self.setCursor(Qt.OpenHandCursor)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('看看正在忙什么', self.requested.emit)
        activities = menu.addMenu('让它做点什么 · 预览 12 秒')
        for action in ACTIVITIES:
            activities.addAction(activity_title(action, self.kind),
                                 lambda checked=False, value=action: self.preview(value))
        menu.addSeparator()
        for title, kind in [('换成小猫', 'cat'), ('换成小狗', 'dog')]:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(self.kind == kind)
            action.triggered.connect(lambda checked=False, value=kind: self.changed.emit(value))
        menu.addSeparator()
        menu.addAction('收起宠物（继续提醒）', self.hidden.emit)
        menu.exec_(event.globalPos())
