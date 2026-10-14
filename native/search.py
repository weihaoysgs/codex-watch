"""Keep Qt view resets out of the input method's composition/commit callback."""
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import QLineEdit


class SearchEdit(QLineEdit):
    inputSettled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.composing = False
        self.handling_input = False
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.timeout.connect(self.notify_settled)

    def input_busy(self):
        return self.composing or self.handling_input

    def inputMethodEvent(self, event):
        self.settle_timer.stop()
        self.composing = bool(event.preeditString())
        self.handling_input = True
        try:
            # textChanged fires inside here. Rebuilding a Qt item view at that
            # point can reset the platform input context before commit finishes.
            super().inputMethodEvent(event)
        finally:
            self.handling_input = False
        if not self.composing:
            self.settle_timer.start(0)

    def focusOutEvent(self, event):
        self.handling_input = True
        try:
            super().focusOutEvent(event)
        finally:
            self.handling_input = False
            self.composing = False
        self.settle_timer.start(0)

    def notify_settled(self):
        if not self.input_busy():
            self.inputSettled.emit()
