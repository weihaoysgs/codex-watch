"""A real, non-modal top-level reminder, independent of GNOME notification banners."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from core import LABELS


class ReminderCard(QWidget):
    acknowledged = pyqtSignal(str, str)
    requested = pyqtSignal(str)

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('候响 · 工作提醒')
        self.setFixedWidth(420)
        self.entries = []
        self.test_mode = False
        self.companion = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName('reminderShell')
        outer.addWidget(shell)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName('reminderStatus')
        header.addWidget(self.status, 1)
        later = QPushButton('稍后')
        later.setObjectName('textButton')
        later.setToolTip('先收起弹窗，事项仍留在等你确认中')
        later.clicked.connect(self.hide)
        header.addWidget(later)
        layout.addLayout(header)
        self.title = QLabel()
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        self.title.setObjectName('detailTitle')
        layout.addWidget(self.title)
        self.context = QLabel()
        self.context.setTextFormat(Qt.PlainText)
        self.context.setWordWrap(True)
        self.context.setObjectName('muted')
        layout.addWidget(self.context)
        self.hint = QLabel('这条提醒会保留，直到你点“知道了”。')
        self.hint.setObjectName('tiny')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        row = QHBoxLayout()
        self.view_button = QPushButton('查看这项工作')
        self.view_button.clicked.connect(self.view)
        row.addWidget(self.view_button)
        self.ack_button = QPushButton('知道了')
        self.ack_button.setObjectName('primary')
        self.ack_button.clicked.connect(self.acknowledge)
        row.addWidget(self.ack_button)
        layout.addLayout(row)
        for b in (later, self.view_button, self.ack_button):
            b.setCursor(Qt.PointingHandCursor)

    def update_pending(self, sessions, reveal=False):
        if self.test_mode and not reveal:
            return
        self.test_mode = False
        # Immutable identity snapshot prevents an old card from acknowledging a newer turn.
        self.entries = [(s.id, s.token, s.title, s.project, s.status) for s in sessions if s.unread]
        if not self.entries:
            self.hide()
            return
        self.render()
        if reveal:
            self.present()

    def render(self):
        _, _, title, project, status = self.entries[0]
        if self.companion and self.companion.isVisible():
            sound = '喵～' if self.companion.kind == 'cat' else '汪～'
            phrase = {'completed': '工作完成啦！', 'waiting': '有个问题等你回答。',
                      'failed': '这项工作需要你看看。', 'interrupted': '这项工作停下来了。',
                      'unknown': '帮我确认一下进展吧。'}.get(status, '有新进展啦！')
            self.status.setText(sound + phrase)
        else:
            self.status.setText('候响  ·  ' + LABELS[status])
        self.title.setText(title[:160] + ('…' if len(title) > 160 else ''))
        self.context.setText(project + (f'  ·  还有 {len(self.entries)-1} 项等你确认' if len(self.entries) > 1 else ''))
        self.view_button.setEnabled(True)
        self.hint.setText('这条提醒会保留，直到你点“知道了”。')
        self.adjustSize()
        if self.isVisible():
            self.position_card()

    def present(self):
        self.adjustSize()
        self.position_card()
        self.show()
        self.raise_()
        if self.companion:
            self.companion.bubble_visible = True
        # Deliberately no activateWindow(): keep keyboard focus in the user's current task.

    def position_card(self):
        if self.companion and self.companion.isVisible():
            pet = self.companion
            screen = QApplication.screenAt(pet.geometry().center()) or QApplication.primaryScreen()
            area = screen.availableGeometry()
            x = pet.x() + pet.width()//2 - self.width()//2
            y = pet.y() - self.height() - 8
            if y < area.top():
                y = pet.y() + pet.height() + 8
            self.move(max(area.left()+8, min(x, area.right()-self.width()-8)),
                      max(area.top()+8, min(y, area.bottom()-self.height()-8)))
            return
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(max(area.left(), area.right() - self.width() - 24), area.top() + 26)

    def hideEvent(self, event):
        if self.companion:
            self.companion.bubble_visible = False
        super().hideEvent(event)

    def show_test(self):
        self.test_mode = True
        self.entries = []
        self.status.setText('候响  ·  提醒测试')
        self.title.setText(('喵～' if self.companion.kind == 'cat' else '汪～') + '工作完成啦，来看看吧。'
                           if self.companion and self.companion.isVisible() else '工作完成后，我会这样提醒你。')
        self.context.setText('这是候响自己的弹窗，不依赖系统通知横幅。')
        self.hint.setText('这是一条测试提醒，不会改变任何真实任务。')
        self.view_button.setEnabled(False)
        self.present()

    def acknowledge(self):
        if self.test_mode:
            self.test_mode = False
            self.hide()
        elif self.entries:
            sid, token = self.entries[0][:2]
            self.acknowledged.emit(sid, token)

    def view(self):
        if self.entries:
            self.requested.emit(self.entries[0][0])
