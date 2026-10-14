"""Read-only directory browser, intentionally separate from the live Inbox."""
from dataclasses import replace
from datetime import datetime

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QTreeWidget, QTreeWidgetItem, QSplitter,
                            QVBoxLayout, QLabel, QTextBrowser, QFrame)
from core import Reader, LABELS


class HistoryWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, home, sid, parent):
        super().__init__(parent)
        self.home, self.sid = home, sid

    def run(self):
        try:
            reader = Reader(self.home)
            self.result.emit(reader.history_index() if self.sid is None else reader.history_detail(self.sid))
        except Exception as exc:
            self.failed.emit(str(exc))


def plain_label(text='', name='muted'):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


class HistoryPanel(QWidget):
    summaryChanged = pyqtSignal(str)
    workersChanged = pyqtSignal()

    def __init__(self, home, demo_sessions=None):
        super().__init__()
        self.home = home
        self.demo = demo_sessions
        self.sessions = []
        self.selected = None
        self.query = ''
        self.loaded = False
        self.index_worker = None
        self.workers = []
        self.generation = 0
        self.stopping = False
        self.input_busy = lambda: False
        self.pending_updates = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.message = plain_label('按项目目录浏览当前用户的本地会话，包含已归档记录。', 'tiny')
        layout.addWidget(self.message)
        splitter = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setObjectName('historyTree')
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.currentItemChanged.connect(self.select_item)
        splitter.addWidget(self.tree)
        detail = QFrame()
        detail.setObjectName('detail')
        right = QVBoxLayout(detail)
        right.setContentsMargins(20, 18, 20, 18)
        self.title = plain_label('选择一个会话', 'detailTitle')
        self.meta = plain_label()
        self.meta.setWordWrap(True)
        self.body = QTextBrowser()
        self.body.setOpenLinks(False)
        self.body.setOpenExternalLinks(False)
        self.body.setPlaceholderText('选择会话后，按需读取最近回复。不会启动或恢复 Codex。')
        self.note = plain_label('这里仅供查看，不会触发提醒或改变确认记录。', 'tiny')
        for widget in (self.title, self.meta, self.body, self.note):
            right.addWidget(widget, 1 if widget is self.body else 0)
        splitter.addWidget(detail)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([430, 440])
        layout.addWidget(splitter, 1)

    def busy(self):
        return any(worker.isRunning() for worker in self.workers)

    def start_worker(self, sid, result, failed):
        worker = HistoryWorker(self.home, sid, self)
        self.workers.append(worker)
        worker.result.connect(result)
        worker.failed.connect(failed)
        worker.finished.connect(lambda: self.finished(worker))
        worker.start()
        return worker

    def finished(self, worker):
        self.workers.remove(worker)
        if self.index_worker is worker:
            self.index_worker = None
        worker.deleteLater()
        self.workersChanged.emit()

    def refresh(self):
        if self.stopping or self.index_worker:
            return
        if self.demo is not None:
            self.receive_index([replace(s, tracked=False, unread=False) for s in self.demo])
            return
        self.message.setText('正在读取会话目录…')
        self.index_worker = self.start_worker(None, self.receive_index, self.index_error)

    def index_error(self, text):
        self.message.setText('目录读取失败：' + text)
        self.summaryChanged.emit('会话目录暂不可用')

    def receive_index(self, sessions):
        if self.input_busy():
            self.pending_updates['index'] = (self.receive_index, (sessions,))
            return
        self.pending_updates.pop('index', None)
        self.sessions = sessions
        self.loaded = True
        self.message.setText('包含已完成、已归档会话；仅点选时读取最近回复，不加入提醒队列。')
        self.render_tree()
        # Refresh the selected record too, without discarding directory expansion.
        if self.selected:
            self.select_item(self.tree.currentItem(), None)

    def filter(self, query):
        query = query.strip().lower()
        if query != self.query:
            self.query = query
            self.render_tree()

    def render_tree(self):
        expanded = {self.tree.topLevelItem(i).data(0, Qt.UserRole+1)
                    for i in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(i).isExpanded()}
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = {}
        selected_item = None
        visible = [s for s in self.sessions if not self.query or
                   self.query in ' '.join((s.title, s.cwd, s.id)).lower()]
        for s in visible:
            cwd = s.cwd or '未指定目录'
            if cwd not in groups:
                folder = QTreeWidgetItem(self.tree, [cwd])
                folder.setData(0, Qt.UserRole+1, cwd)
                folder.setToolTip(0, cwd)
                groups[cwd] = folder
            item = QTreeWidgetItem(groups[cwd], [('已归档 · ' if s.archived else '') + s.title])
            item.setData(0, Qt.UserRole, s.id)
            item.setToolTip(0, s.title + '\n' + s.id)
            if s.id == self.selected:
                selected_item = item
        for cwd, folder in groups.items():
            folder.setText(0, f'{cwd}  ({folder.childCount()})')
            folder.setExpanded(bool(self.query) or cwd in expanded)
        if selected_item:
            self.tree.setCurrentItem(selected_item)
        self.tree.blockSignals(False)
        if self.selected and not selected_item:
            self.selected = None
            self.generation += 1
            self.clear_detail()
        self.summaryChanged.emit(f'{len(groups)} 个目录 · {len(visible)} 个会话')

    def clear_detail(self):
        self.title.setText('选择一个会话')
        self.meta.clear()
        self.body.clear()
        self.note.setText('这里仅供查看，不会触发提醒或改变确认记录。')

    def select_item(self, item, old):
        self.generation += 1
        request = self.generation
        sid = item.data(0, Qt.UserRole) if item else None
        self.selected = sid
        self.clear_detail()
        if not sid or self.stopping:
            return
        session = next((s for s in self.sessions if s.id == sid), None)
        if not session:
            return
        self.show_session(session, loading=True)
        if self.demo is not None:
            self.show_session(session)
        else:
            self.start_worker(sid, lambda s: self.receive_detail(s, request),
                              lambda error: self.detail_error(error, request))

    def receive_detail(self, session, request):
        if request != self.generation or session.id != self.selected or self.stopping:
            return
        if self.input_busy():
            self.pending_updates['detail'] = (self.receive_detail, (session, request))
            return
        self.pending_updates.pop('detail', None)
        self.show_session(session)

    def detail_error(self, error, request):
        if request != self.generation or self.stopping:
            return
        if self.input_busy():
            self.pending_updates['detail'] = (self.detail_error, (error, request))
            return
        self.pending_updates.pop('detail', None)
        self.body.setPlainText('无法读取会话详情：' + error)

    def flush_pending(self):
        if self.input_busy() or self.stopping:
            return
        pending, self.pending_updates = self.pending_updates, {}
        for callback, args in pending.values():
            callback(*args)

    def show_session(self, session, loading=False):
        self.title.setText(session.title)
        try:
            updated = datetime.fromtimestamp(session.updated).strftime('%Y-%m-%d %H:%M')
        except (ValueError, OSError, OverflowError):
            updated = '未知时间'
        status = '读取中' if loading else LABELS.get(session.status, '未知')
        self.meta.setText(f'目录：{session.cwd or "未指定"}\n会话：{session.id}\n'
                          f'更新：{updated} · 记录状态：{status}' + (' · 已归档' if session.archived else ''))
        text = '正在读取所选会话…' if loading else (
            ('【需要回复】\n' + session.question + '\n\n' if session.question else '') +
            (session.preview[:50000] or '没有可显示的最近回复。'))
        self.body.setPlainText(text)
        self.note.setText('仅查看本地最近记录，不加入提醒队列。' if loading else session.note or
                          '仅查看本地最近记录，不代表会话当前仍在运行。')
