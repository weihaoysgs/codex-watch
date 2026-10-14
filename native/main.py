#!/usr/bin/python3
"""Codex Watch / 候响 — a local, read-only desktop companion."""
import argparse
import html
import json
import os
import signal
import sys
import time
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal, QUrl, QLockFile, QT_VERSION
from PyQt5.QtGui import QColor, QPainter, QPen, QIcon, QPixmap, QDesktopServices
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QSystemTrayIcon, QMenu, QDialog, QCheckBox, QComboBox, QMessageBox,
    QTextBrowser, QSplitter, QSizeGrip, QShortcut, QAbstractItemView, QStackedWidget)

from core import Reader, Inbox, Session, LABELS, ATTENTION, dump_sessions
from reminder import ReminderCard
from version import VERSION
from pet import DesktopPet
from history import HistoryPanel

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'codex-watch'
AUTOSTART = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'autostart/io.local.CodexWatch.desktop'
COLORS = {'running': '#7d8ccd', 'waiting': '#b68a51', 'completed': '#739885',
          'failed': '#bb7e89', 'interrupted': '#bb7e89', 'unknown': '#8e94a7', 'idle': '#8e94a7'}


def icon(color='#7d8ccd'):
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(4, 4, 56, 56, 17, 17)
    p.setPen(QPen(QColor('white'), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(17, 26, 24, 32)
    p.drawLine(24, 32, 17, 38)
    p.drawLine(31, 38, 40, 38)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor('#e1e6ff'))
    p.drawEllipse(43, 15, 7, 7)
    p.end()
    return QIcon(pix)


def label(text, name='', wrap=False):
    w = QLabel(text)
    w.setTextFormat(Qt.PlainText)
    w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def button(text, callback, name=''):
    b = QPushButton(text)
    b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(callback)
    return b


def age(timestamp):
    delta = max(0, int(time.time() - timestamp))
    if delta < 60:
        return '刚刚'
    if delta < 3600:
        return f'{delta // 60} 分钟前'
    if delta < 86400:
        return f'{delta // 3600} 小时前'
    return f'{delta // 86400} 天前'


class ScanWorker(QThread):
    result = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, reader, parent):
        super().__init__(parent)
        self.reader = reader

    def run(self):
        try:
            sessions, warnings = self.reader.scan()
            self.result.emit(sessions, warnings)
        except Exception as exc:
            self.failed.emit(str(exc))


class Chrome(QFrame):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.drag_offset = None
        self.setFixedHeight(42)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 10, 0)
        row.addWidget(label('候响  /  CODEX WATCH  ' + VERSION, 'chromeCaption'))
        row.addStretch()
        for text, fn in [('−', window.showMinimized), ('□', self.maximize), ('×', window.close)]:
            b = button(text, fn, 'windowControl')
            b.setFixedSize(32, 28)
            row.addWidget(b)

    def maximize(self):
        self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()

    def mousePressEvent(self, event):
        self.drag_offset = None
        if event.button() == Qt.LeftButton:
            handle = self.window.windowHandle()
            start_move = getattr(handle, 'startSystemMove', None)
            if start_move and start_move():
                return
            # Qt 5.12 (Ubuntu 20.04) has no startSystemMove; retain title-bar dragging.
            if not self.window.isMaximized():
                self.drag_offset = event.globalPos() - self.window.pos()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window.move(event.globalPos() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = None

    def mouseDoubleClickEvent(self, event):
        self.maximize()


class SessionRow(QFrame):
    def __init__(self, session, selected, dark=False):
        super().__init__()
        self.setObjectName('sessionRowSelected' if selected else 'sessionRow')
        v = QVBoxLayout(self)
        v.setContentsMargins(15, 14, 15, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        color = COLORS[session.status]
        status = label('●  ' + LABELS[session.status])
        status.setStyleSheet(f'color:{color};font-size:11px;font-weight:600;')
        top.addWidget(status)
        top.addStretch()
        if session.unread:
            dot = label('未处理', 'unread')
            top.addWidget(dot)
        v.addLayout(top)
        self.title = label(session.title, 'taskTitle')
        self.title.setToolTip(session.title)
        v.addWidget(self.title)
        bottom = QHBoxLayout()
        project = label(session.project + ('  ·  ' + session.tty if session.tty else ''), 'muted')
        project.setToolTip(session.cwd)
        bottom.addWidget(project, 1)
        bottom.addWidget(label(age(session.updated), 'tiny'))
        v.addLayout(bottom)
        self.raw_title = session.title

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.title.setText(self.title.fontMetrics().elidedText(self.raw_title, Qt.ElideRight, max(80, self.width() - 30)))


class Window(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.inbox = Inbox(DATA / ('demo-state.json' if demo else 'state.json'))
        self.prefs = self.inbox.data['preferences']
        self.reader = Reader()
        self.sessions = []
        self.selected = None
        self.view = 0
        self.worker = None
        self.last_reminder = time.monotonic()
        self.quit_requested = False
        self.pause_until = 0
        self.failed_scan = False
        self.detail_signature = None
        self.reminder = ReminderCard()
        self.destroyed.connect(self.reminder.deleteLater)
        self.reminder.acknowledged.connect(self.acknowledge_reminder)
        self.reminder.requested.connect(self.open_session)
        self.pet = DesktopPet(self.prefs.get('pet_kind', 'cat'))
        self.destroyed.connect(self.pet.deleteLater)
        self.reminder.companion = self.pet
        self.pet.requested.connect(self.pet_clicked)
        self.pet.changed.connect(self.set_pet)
        self.pet.hidden.connect(lambda: self.set_pet('none'))
        self.pet.positioned.connect(self.save_pet_position)
        self.pet.moved.connect(self.move_pet_bubble)
        self.setWindowTitle('候响 · Codex Watch')
        self.setWindowIcon(icon())
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1240, 860)
        self.setMinimumSize(1060, 760)
        shell = QFrame()
        shell.setObjectName('shell')
        self.setCentralWidget(shell)
        vertical = QVBoxLayout(shell)
        vertical.setContentsMargins(1, 1, 1, 1)
        vertical.setSpacing(0)
        vertical.addWidget(Chrome(self))
        body = QHBoxLayout()
        body.setSpacing(0)
        vertical.addLayout(body, 1)
        side = QFrame()
        side.setObjectName('sidebar')
        side.setFixedWidth(215)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(24, 28, 22, 20)
        sl.setSpacing(10)
        sl.addWidget(label('候响', 'brand'))
        sl.addWidget(label('安心去忙，有进展叫你。', 'muted'))
        sl.addSpacing(26)
        self.nav = QListWidget()
        self.nav.setObjectName('nav')
        self.nav.setFixedHeight(200)
        for text in ['当前关注', '等你确认', '正在工作', '会话目录']:
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(165, 43))
            self.nav.addItem(item)
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self.change_view)
        sl.addWidget(self.nav)
        sl.addStretch()
        card = QFrame()
        card.setObjectName('companion')
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 14, 14, 14)
        cv.addWidget(label('不用守着每个窗口', 'sectionLabel'))
        cv.addWidget(label('工作交给 Codex，\n下一步留给你。', 'muted'))
        self.pause_button = button('暂停提醒 30 分钟', self.toggle_pause, 'petButton')
        cv.addWidget(self.pause_button)
        sl.addWidget(card)
        sl.addSpacing(10)
        sl.addWidget(button('外观与提醒', self.settings, 'textButton'))
        sl.addWidget(label('仅此设备  ·  只读监控', 'tiny'))
        body.addWidget(side)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 26, 28, 14)
        cl.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(label(time.strftime('%m 月 %d 日') + '  /  实时工作提醒', 'eyebrow'))
        top.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName('search')
        self.search.setPlaceholderText('搜索项目、会话、终端…')
        self.search.setFixedWidth(235)
        self.search.textChanged.connect(self.render)
        top.addWidget(self.search)
        cl.addLayout(top)
        cl.addSpacing(8)
        title = QHBoxLayout()
        self.heading = label('安心工作，完成叫你。', 'heading')
        title.addWidget(self.heading, 1)
        self.ack_all = button('全部知道了', self.acknowledge_all)
        title.addWidget(self.ack_all)
        cl.addLayout(title)
        self.description = label('只关注正在工作的会话。完成后提醒，知道了就收起。', 'muted')
        cl.addWidget(self.description)
        cl.addSpacing(8)
        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.stats = []
        for text in ['正在工作', '等你确认']:
            box = QFrame()
            box.setObjectName('statCard')
            bv = QHBoxLayout(box)
            bv.setContentsMargins(16, 13, 16, 13)
            number = label('—', 'statNumber')
            bv.addWidget(number)
            bv.addWidget(label(text, 'muted'))
            bv.addStretch()
            stats.addWidget(box, 1)
            self.stats.append(number)
        cl.addLayout(stats)
        filters = QHBoxLayout()
        self.count = label('正在读取会话…', 'sectionLabel')
        filters.addWidget(self.count, 1)
        self.list_hint = label('不展示历史记录', 'tiny')
        filters.addWidget(self.list_hint)
        cl.addLayout(filters)
        self.splitter = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setObjectName('sessions')
        self.list.setSpacing(7)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.currentItemChanged.connect(self.selection_changed)
        self.splitter.addWidget(self.list)
        detail = QFrame()
        detail.setObjectName('detail')
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(20, 18, 20, 16)
        dv.setSpacing(9)
        self.detail_status = label('会话详情', 'sectionLabel')
        dv.addWidget(self.detail_status)
        self.detail_title = label('有任务在忙时，会出现在这里', 'detailTitle', True)
        self.detail_title.setWordWrap(False)
        self.detail_title.setFixedHeight(29)
        dv.addWidget(self.detail_title)
        self.detail_meta = label('最近回复和需要你处理的事，会显示在这里。', 'muted', True)
        self.detail_meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_meta.setFixedHeight(38)
        dv.addWidget(self.detail_meta)
        self.question = label('', 'question', True)
        self.question.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.question.hide()
        dv.addWidget(self.question)
        dv.addWidget(label('最近回复', 'eyebrow'))
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        self.preview.setOpenExternalLinks(False)
        self.preview.setPlaceholderText('还没有可显示的回复。')
        self.preview.setMinimumHeight(100)
        dv.addWidget(self.preview, 1)
        self.note = label('', 'tiny', True)
        self.note.hide()
        dv.addWidget(self.note)
        self.ack = button('知道了，移出列表', self.acknowledge, 'primary')
        dv.addWidget(self.ack)
        actions = QHBoxLayout()
        self.copy = button('复制续接命令', self.copy_resume)
        self.folder = button('打开项目目录', self.open_folder)
        actions.addWidget(self.copy)
        actions.addWidget(self.folder)
        dv.addLayout(actions)
        for b in (self.ack, self.copy, self.folder):
            b.setEnabled(False)
        self.splitter.addWidget(detail)
        self.splitter.setSizes([430, 440])
        self.splitter.setChildrenCollapsible(False)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.splitter)
        self.history = HistoryPanel(self.reader.home, demo_sessions() if demo else None)
        self.history.summaryChanged.connect(lambda text: self.count.setText(text) if self.view == 3 else None)
        self.history.workersChanged.connect(self.scan_finished)
        self.pages.addWidget(self.history)
        cl.addWidget(self.pages, 1)
        self.banner = label('', 'banner', True)
        self.banner.hide()
        cl.addWidget(self.banner)
        bottom = QHBoxLayout()
        self.health = label('连接本地 Codex…', 'tiny')
        bottom.addWidget(self.health, 1)
        self.refresh = button('刷新', self.refresh_view, 'textButton')
        bottom.addWidget(self.refresh)
        grip = QSizeGrip(self)
        grip.setFixedSize(14, 14)
        bottom.addWidget(grip)
        cl.addLayout(bottom)
        body.addWidget(content, 1)
        self.tray = QSystemTrayIcon(icon(), self)
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(self.update_tray_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda reason: self.reveal() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.messageClicked.connect(self.show_attention)
        if not demo:
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan)
        self.timer.start(2500)
        QShortcut('Ctrl+K', self, activated=self.search.setFocus)
        QShortcut('Ctrl+R', self, activated=self.refresh_view)
        QShortcut('Ctrl+Q', self, activated=self.quit)
        self.apply_theme(self.prefs.get('theme', 'light'))
        position = self.prefs.get('pet_position')
        if isinstance(position, list) and len(position) == 2 and all(isinstance(v, int) for v in position):
            self.pet.move(*position)
        self.configure_pet()
        if demo:
            self.timer.stop()
            # Seed a live turn so the completion demo follows the same lifecycle as real work.
            self.inbox.data['sessions']['demo-2'] = {'watched_turn': 't2', 'observed': 't2:running:'}
            self.receive(demo_sessions(), [])
        else:
            QTimer.singleShot(100, self.scan)

    def apply_theme(self, mode):
        text = (ROOT / 'native/theme.qss').read_text()
        if QT_VERSION < 0x050F00:
            # Older QSS engines otherwise emit this warning on every repolish.
            text = text.replace('letter-spacing:1px;', '')
        if mode == 'dark':
            replacements = {'#fdfdfe': '#1e1e1e', '#fdfdff': '#252526', '#f4f5f9': '#252526',
                '#f6f7fa': '#2d2d2d', '#f1f3f8': '#2d2d2d', '#eef0f8': '#292b31', '#e5eaf8': '#333a4b',
                '#e9ecf5': '#333333', '#e0e2e9': '#3c3c3c', '#eceef5': '#363636', '#e8ebf5': '#3c3c3c',
                '#343746': '#f0f0f0', '#434758': '#eeeeee', '#363847': '#cccccc', '#4d5368': '#dedee5',
                '#747a91': '#b1b1bc', '#8c8f9f': '#a2a2ae', '#a2a6b6': '#9999a6', '#777c90': '#b4b4bf',
                '#7d8ccd': '#8295de', '#fff6e9': '#3d3327', '#9c774b': '#e0bd8f', '#f8edf1': '#3b2727'}
            for old, new in replacements.items():
                text = text.replace(old, new)
        QApplication.instance().setStyleSheet(text)
        self.prefs['theme'] = mode

    def save(self):
        try:
            self.inbox.save()
        except OSError as exc:
            self.error('本地标记保存失败：' + str(exc))

    def scan(self):
        if self.demo or self.quit_requested or (self.worker and self.worker.isRunning()):
            return
        if self.worker:
            self.worker.deleteLater()
        self.worker = ScanWorker(self.reader, self)
        self.worker.result.connect(self.receive)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.scan_finished)
        self.worker.start()

    def scan_finished(self):
        if self.quit_requested and not (self.worker and self.worker.isRunning()) and not self.history.busy():
            QApplication.quit()

    def refresh_view(self):
        if self.view == 3:
            self.history.refresh()
        else:
            self.scan()

    def receive(self, sessions, warnings):
        self.failed_scan = False
        self.sessions = sessions
        try:
            self.inbox.reconcile(sessions)
            alerts = self.inbox.pending_alerts(sessions)
        except OSError as exc:
            self.error('无法保存提醒标记：' + str(exc))
            alerts = []
        alerts = [s for s in alerts if self.allowed_source(s)]
        self.pet.sync(sessions)
        if alerts:
            self.notify(alerts)
        pending = [s for s in sessions if s.unread and self.allowed_source(s)]
        if self.prefs.get('repeat', True) and pending and time.monotonic() - self.last_reminder >= 600:
            self.notify(pending, repeat=True)
        self.reminder.update_pending(pending)
        self.banner.setText('\n'.join(warnings))
        self.banner.setVisible(bool(warnings))
        self.health.setText(('演示数据  ·  不连接真实会话' if self.demo else '● 本地已连接  ·  每 2.5 秒刷新  ·  ' + time.strftime('%H:%M:%S')))
        self.render()

    def error(self, text):
        self.failed_scan = True
        self.pet.sync(self.sessions, stale=True)
        self.banner.setText(text + '\n保留上次结果，正在重试；此时显示的状态可能已过时。')
        self.banner.show()
        self.health.setText('连接异常 · 上次状态已冻结')

    def allowed_source(self, s):
        # Newer CLI frontends may be persisted as vscode by the shared daemon.
        # Reader already excludes internal subagents; source is not a visibility gate.
        return True

    def visible_sessions(self):
        query = self.search.text().strip().lower()
        result = []
        for s in self.sessions:
            if not s.tracked:
                continue
            if query and query not in ' '.join([s.title, s.cwd, s.id, s.tty]).lower():
                continue
            if self.view == 1 and not s.unread:
                continue
            if self.view == 2 and s.status != 'running':
                continue
            result.append(s)
        priority = {'waiting': 0, 'failed': 1, 'interrupted': 2, 'completed': 3, 'running': 4, 'unknown': 5, 'idle': 6}
        return sorted(result, key=lambda s: (0 if s.unread else 1, priority[s.status], -s.updated))

    def render(self):
        self.pet.sync(self.sessions, stale=self.failed_scan)
        allowed = [s for s in self.sessions if s.tracked]
        values = [sum(s.status == 'running' for s in allowed), sum(s.unread for s in allowed)]
        for widget, value in zip(self.stats, values):
            widget.setText(str(value))
        unread = sum(s.unread for s in allowed)
        self.nav.item(1).setText(f'等你确认   {unread}' if unread else '等你确认')
        self.tray.setToolTip(f'候响 · {values[0]} 个进行中 · {unread} 个待处理')
        self.tray.setIcon(icon('#b68a51' if unread else '#7d8ccd'))
        if self.view == 3:
            self.history.filter(self.search.text())
            return
        shown = self.visible_sessions()
        self.count.setText(f'{len(shown)} 个会话' if shown else ('没有匹配的工作' if self.search.text() else '暂时没有需要关注的工作'))
        scroll = self.list.verticalScrollBar().value()
        self.list.blockSignals(True)
        self.list.clear()
        selected_item = None
        for s in shown:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, s.id)
            item.setSizeHint(QSize(320, 114))
            self.list.addItem(item)
            self.list.setItemWidget(item, SessionRow(s, s.id == self.selected))
            if s.id == self.selected:
                selected_item = item
        if not selected_item and shown:
            self.selected = shown[0].id
            selected_item = self.list.item(0)
        if not shown:
            self.selected = None
        if selected_item:
            self.list.setCurrentItem(selected_item)
        self.list.blockSignals(False)
        self.list.verticalScrollBar().setValue(scroll)
        self.show_detail()
        self.ack_all.setEnabled(any(s.unread for s in shown))

    def current(self):
        return next((s for s in self.sessions if s.id == self.selected), None)

    def selection_changed(self, item, old):
        if item:
            self.selected = item.data(Qt.UserRole)
            # Selection is not acknowledgement: leave the inbox intact until explicitly handled.
            self.show_detail()

    def show_detail(self):
        s = self.current()
        if not s:
            self.detail_title.setText('放心去忙，我会留意新任务。')
            self.detail_meta.setText('有会话开始工作时自动出现。\n完成后通知你；点击“知道了”就移出列表。')
            self.preview.clear()
            self.question.hide()
            self.note.clear()
            self.detail_status.setText('会话详情')
            for b in (self.ack, self.copy, self.folder):
                b.setEnabled(False)
            self.detail_signature = None
            return
        self.detail_status.setText('●  ' + LABELS[s.status] + ('  ·  未处理' if s.unread else ''))
        self.detail_status.setStyleSheet('color:' + COLORS[s.status])
        self.detail_title.setText(self.detail_title.fontMetrics().elidedText(s.title, Qt.ElideRight, max(200, self.detail_title.width())))
        self.detail_title.setToolTip(s.title)
        terminal = f'{s.tty}  ·  PID {s.pid}' if s.tty else ('已连接运行中的 Codex 后台' if s.pid else '本地会话 · 实时监控')
        self.detail_meta.setText(self.detail_meta.fontMetrics().elidedText(s.cwd, Qt.ElideMiddle, max(200, self.detail_meta.width())) + '\n' + terminal)
        self.detail_meta.setToolTip(s.cwd + '\n会话 ID：' + s.id)
        self.question.hide()
        signature = (s.id, s.preview, s.question, s.status, s.note)
        if signature != self.detail_signature:
            # Plain text prevents local transcript HTML/images from triggering network access.
            question = ('【需要你回复】\n' + s.question + '\n\n────────────\n\n') if s.question and s.status == 'waiting' else ''
            explanation = ('【状态说明】\n' + s.note + '\n\n────────────\n\n') if s.note and s.status != 'waiting' else ''
            self.preview.setPlainText(question + explanation + (s.preview[:50000] or '还没有可显示的回复。'))
            self.detail_signature = signature
        note = s.note or ('已收到本轮完成事件；请查看结果后再标记。' if s.status == 'completed' else '这里只读状态，不会向 Codex 发送内容。')
        self.note.setText(note)
        self.detail_status.setToolTip(note)
        self.ack.setEnabled(s.unread)
        self.ack.setText('知道了，移出列表' if s.unread else '正在工作，完成后会提醒')
        self.copy.setEnabled(True)
        self.copy.setToolTip('仅复制命令；原终端还开着时，请直接回到原终端操作。')
        self.folder.setEnabled(Path(s.cwd).is_dir())

    def acknowledge(self):
        if self.view == 3:
            return
        s = self.current()
        if s:
            try:
                self.inbox.acknowledge(s)
            except OSError as exc:
                self.error(str(exc))
            self.render()
            self.reminder.update_pending([s for s in self.sessions if s.unread])

    def acknowledge_reminder(self, sid, token):
        s = next((s for s in self.sessions if s.id == sid and s.token == token and s.unread), None)
        if s:
            try:
                self.inbox.acknowledge(s)
            except OSError as exc:
                self.error(str(exc))
            self.render()
        self.reminder.update_pending([s for s in self.sessions if s.unread])

    def acknowledge_all(self):
        if self.view == 3:
            return
        for s in self.visible_sessions():
            if s.unread:
                self.inbox.data['sessions'].setdefault(s.id, {})['seen'] = s.token
                s.unread = False
                s.tracked = s.status == 'running'
        self.save()
        self.render()
        self.reminder.update_pending([s for s in self.sessions if s.unread])

    def copy_resume(self):
        s = self.current()
        if s:
            QApplication.clipboard().setText(s.resume_command)
            self.health.setText('已复制续接命令 · 原终端还开着时，请回原终端继续')

    def open_folder(self):
        s = self.current()
        if s and Path(s.cwd).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(s.cwd))

    def change_view(self, index):
        self.view = index
        self.heading.setText(['安心工作，完成叫你。', '这一轮，轮到你了。', '让它们，安心工作。', '按目录，找回每一段工作。'][index])
        self.pages.setCurrentIndex(1 if index == 3 else 0)
        self.ack_all.setVisible(index != 3)
        self.description.setText('浏览当前用户的 Codex 会话，点选后查看信息，不参与提醒。' if index == 3 else
                                 '只关注正在工作的会话。完成后提醒，知道了就收起。')
        self.list_hint.setText('只读浏览 · 按需加载' if index == 3 else '不展示历史记录')
        if index == 3:
            self.count.setText('正在读取会话目录…')
            self.history.refresh()
        self.render()

    def notify(self, sessions, repeat=False):
        if self.demo or not self.prefs.get('notifications', True) or time.time() < self.pause_until:
            return False
        self.last_reminder = time.monotonic()
        if len(sessions) == 1:
            s = sessions[0]
            title = '候响 · ' + ('别忘了处理' if repeat else LABELS[s.status])
            text = s.project + ' · ' + s.title[:90]
        else:
            title = f'候响 · {len(sessions)} 个会话需要处理'
            text = '\n'.join(f'{LABELS[s.status]} · {s.project}' for s in sessions[:3])
        # Show an actual window first; a tray API call alone is not proof of a visible alert.
        pending = [s for s in self.sessions if s.unread]
        if any(s.status == 'completed' for s in sessions) and not repeat:
            self.pet.celebrate()
        self.reminder.update_pending(pending, reveal=True)
        if not self.reminder.isVisible():
            print('reminder_not_visible; delivery will be retried', flush=True)
            return False
        try:
            self.inbox.mark_presented(pending)
        except OSError as exc:
            self.error('提醒已弹出，但发送状态保存失败：' + str(exc))
        print('reminder_shown ' + json.dumps({'count': len(pending), 'events': [s.token for s in pending]}, ensure_ascii=False), flush=True)
        self.tray.showMessage(title, text, QSystemTrayIcon.Information, 10000)
        if self.prefs.get('sound', False):
            QApplication.beep()
        return True

    def toggle_pause(self):
        self.pause_until = 0 if self.pause_until > time.time() else time.time() + 1800
        self.pause_button.setText('恢复提醒' if self.pause_until else '暂停提醒 30 分钟')
        if self.pause_until:
            self.reminder.hide()
        else:
            pending = self.inbox.pending_alerts(self.sessions)
            if pending:
                self.notify(pending)

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_attention(self):
        self.nav.setCurrentRow(1)
        self.reveal()

    def update_tray_menu(self):
        m = self.tray_menu
        m.clear()
        m.addAction('打开候响', self.reveal)
        m.addAction('查看等你确认的提醒', self.show_attention)
        m.addSeparator()
        pending = [s for s in self.sessions if s.unread and self.allowed_source(s)][:5]
        for s in pending:
            m.addAction(f'{LABELS[s.status]} · {s.project}', lambda checked=False, sid=s.id: self.open_session(sid))
        if pending:
            m.addSeparator()
        m.addAction('恢复提醒' if self.pause_until > time.time() else '暂停提醒 30 分钟', self.toggle_pause)
        m.addAction('外观与提醒', self.settings)
        pets = m.addMenu('桌面伙伴')
        for title, kind in [('小猫', 'cat'), ('小狗', 'dog'), ('不显示宠物', 'none')]:
            action = pets.addAction(title)
            action.setCheckable(True)
            action.setChecked(self.prefs.get('pet_kind', 'cat') == kind)
            action.triggered.connect(lambda checked=False, value=kind: self.set_pet(value))
        m.addSeparator()
        m.addAction('退出候响', self.quit)

    def open_session(self, sid):
        self.selected = sid
        self.search.clear()
        self.nav.setCurrentRow(0)
        self.render()
        self.reveal()

    def configure_pet(self):
        kind = self.prefs.get('pet_kind', 'cat')
        self.pet.roam = self.prefs.get('pet_roam', True)
        if kind == 'none':
            self.pet.hide()
        else:
            self.pet.load(kind)
            if self.pet.error:
                self.pet.hide()
                print('pet_assets_unavailable: ' + self.pet.error, flush=True)
            elif not self.demo:
                self.pet.show()
        if self.reminder.isVisible():
            if self.reminder.entries:
                self.reminder.render()
            self.reminder.position_card()

    def set_pet(self, kind):
        self.prefs['pet_kind'] = kind if kind in ('cat', 'dog', 'none') else 'cat'
        self.configure_pet()
        self.save()

    def save_pet_position(self, x, y):
        self.prefs['pet_position'] = [x, y]
        self.save()

    def move_pet_bubble(self):
        if self.reminder.isVisible():
            self.reminder.position_card()

    def pet_clicked(self):
        pending = [s for s in self.sessions if s.unread]
        if pending:
            self.reminder.update_pending(pending, reveal=True)
        else:
            self.nav.setCurrentRow(0)
            self.reveal()

    def settings(self):
        d = QDialog(self)
        d.setWindowTitle('候响 · 外观与提醒')
        d.setMinimumWidth(445)
        v = QVBoxLayout(d)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(16)
        v.addWidget(label('按照你的节奏。', 'detailTitle'))
        theme = QComboBox()
        theme.addItems(['浅色 · 柔和蓝紫', '深色 · 中性炭灰'])
        theme.setCurrentIndex(self.prefs.get('theme') == 'dark')
        v.addWidget(theme)
        v.addWidget(label('桌面伙伴 · 拖动移动，右键切换', 'sectionLabel'))
        pet_choice = QComboBox()
        pet_choice.addItems(['小猫 · 喵～', '小狗 · 汪～', '不显示宠物'])
        pet_choice.setCurrentIndex({'cat': 0, 'dog': 1, 'none': 2}.get(self.prefs.get('pet_kind', 'cat'), 0))
        v.addWidget(pet_choice)
        checks = {}
        for key, text, default in [('notifications', '任务完成 / 待回复时弹出置顶提醒卡片', True),
                                   ('repeat', '未处理事项每 10 分钟汇总提醒一次', True),
                                   ('pet_roam', '工作时来回跑动（关闭后原地活动）', True),
                                   ('sound', '通知时播放提示音', False)]:
            w = QCheckBox(text)
            w.setChecked(self.prefs.get(key, default))
            checks[key] = w
            v.addWidget(w)
        startup = QCheckBox('登录电脑后自动在托盘运行')
        startup.setChecked(AUTOSTART.exists())
        v.addWidget(startup)
        v.addWidget(label('只跟踪正在工作的会话，不导入已完成历史。\n完成后保留提醒，点击“知道了”即移出列表。\n关闭主窗口后继续在托盘监控。', 'muted', True))
        test = button('预览完成提醒弹窗', self.reminder.show_test)
        v.addWidget(test)
        actions = QHBoxLayout()
        actions.addWidget(button('取消', d.reject))
        actions.addWidget(button('保存设置', d.accept, 'primary'))
        v.addLayout(actions)
        if d.exec_() == QDialog.Accepted:
            for key, w in checks.items():
                self.prefs[key] = w.isChecked()
            self.apply_theme('dark' if theme.currentIndex() else 'light')
            self.prefs['pet_kind'] = ['cat', 'dog', 'none'][pet_choice.currentIndex()]
            self.configure_pet()
            try:
                if startup.isChecked():
                    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
                    AUTOSTART.write_text(desktop_entry(background=True))
                elif AUTOSTART.exists():
                    AUTOSTART.unlink()
                self.save()
            except OSError as exc:
                QMessageBox.warning(self, '设置未完全保存', str(exc))
            self.render()
            if not self.prefs.get('notifications', True):
                self.reminder.hide()
        d.deleteLater()

    def closeEvent(self, event):
        if self.quit_requested or self.demo:
            self.pet.close()
            self.reminder.close()
            event.accept()
        else:
            event.ignore()
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.hide()
            else:
                self.showMinimized()

    def quit(self):
        self.quit_requested = True
        self.history.stopping = True
        self.pet.close()
        self.reminder.close()
        self.timer.stop()
        self.tray.hide()
        self.hide()
        self.scan_finished()


def desktop_entry(background=False):
    installed = ROOT == Path('/usr/share/codex-watch')
    executable = 'codex-watch' if installed else f'/usr/bin/python3 "{ROOT}/native/main.py"'
    icon_path = 'io.local.CodexWatch' if installed else str(ROOT / 'native/icon.svg')
    return ('[Desktop Entry]\nType=Application\nName=候响 · Codex Watch\n'
            'Comment=Codex 终端状态与完成提醒\n'
            f'Exec={executable}' + (' --background' if background else '') + '\n'
            f'Icon={icon_path}\nTerminal=false\nCategories=Development;\n'
            'StartupWMClass=codex-watch\nX-GNOME-Autostart-enabled=true\n')


def demo_sessions():
    now = time.time()
    return [Session('demo-1', '整理室内场景数据，准备下一轮验证', '/home/demo/Projects/scenes',
                    status='waiting', turn_id='t1', updated=now-75, pid=21843, tty='pts/6',
                    question='已经完成数据筛选。下一步你希望先验证小户型，还是完整楼层？', question_id='q1',
                    preview='场景筛选已经完成。\n\n· 保留 12 个可用的多房间场景\n· 排除了材质缺失和比例异常的样本\n· 已整理每个场景的授权与来源\n\n你可以先查看筛选结果，再确定下一步验证范围。'),
            Session('demo-2', '修复增量构建，确认无需重复编译', '/home/demo/Projects/build-tools',
                    status='completed', turn_id='t2', updated=now-300, pid=21844, tty='pts/25',
                    preview='已经修复并验证。\n\n现在只有版本内容变化时才会重写头文件。连续构建两次，第二次没有触发重新编译。'),
            Session('demo-3', '优化轨迹对齐，检查回归结果', '/home/demo/Projects/robotics-sim',
                    status='running', turn_id='t3', updated=now-10, pid=21845, tty='pts/71',
                    preview='正在对比修复前后的轨迹误差，完整验证仍在运行。'),
            Session('demo-4', '补充桌面交互和深色主题', '/home/demo/Projects/desktop-app',
                    status='running', turn_id='t4', updated=now-50, pid=21846, tty='pts/22',
                    preview='基础交互已经完成，正在核对深色模式下的文字对比度。')]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='version', version='Codex Watch ' + VERSION)
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--screenshot')
    parser.add_argument('--dark', action='store_true')
    parser.add_argument('--diagnose', action='store_true')
    args = parser.parse_args()
    if args.diagnose:
        data = dump_sessions()
        # Diagnostics omit conversation text and titles.
        for s in data['sessions']:
            for key in ('preview', 'question', 'title'):
                s.pop(key, None)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
    app = QApplication(sys.argv[:1])
    app.setApplicationName('codex-watch')
    app.setApplicationDisplayName('候响 · Codex Watch')
    app.setDesktopFileName('io.local.CodexWatch')
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    DATA.mkdir(parents=True, exist_ok=True)
    server = None
    lock = None
    if not args.demo and not args.screenshot:
        socket_name = str(DATA / 'instance.sock')
        sock = QLocalSocket()
        sock.connectToServer(socket_name)
        if sock.waitForConnected(500):
            sock.write(b'activate')
            sock.waitForBytesWritten(500)
            return
        lock = QLockFile(str(DATA / 'instance.lock'))
        if not lock.tryLock(200):
            print('候响正在启动，请稍后重试。')
            return
        QLocalServer.removeServer(socket_name)
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.UserAccessOption)
        if not server.listen(socket_name):
            raise RuntimeError(server.errorString())
    window = Window(args.demo)
    if args.dark:
        window.apply_theme('dark')
    if server:
        def activate():
            peer = server.nextPendingConnection()
            if peer:
                peer.waitForReadyRead(100)
                peer.readAll()
                window.reveal()
                peer.disconnectFromServer()
                peer.deleteLater()
        server.newConnection.connect(activate)
    if not args.background or not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()
    if args.screenshot:
        def capture():
            window.grab().save(args.screenshot)
            window.quit()
        QTimer.singleShot(650, capture)
    signal.signal(signal.SIGTERM, lambda *_: window.quit())
    signal.signal(signal.SIGINT, lambda *_: window.quit())
    pulse = QTimer()
    pulse.timeout.connect(lambda: None)
    pulse.start(500)
    code = app.exec_()
    if lock:
        lock.unlock()
    sys.exit(code)


if __name__ == '__main__':
    main()
