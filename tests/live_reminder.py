"""Real-desktop smoke: isolated Codex fixture -> visible popup -> button -> removed.

Run with /usr/bin/python3 tests/live_reminder.py in a desktop session.
Does not read/write real Codex state or acknowledge any real task.
"""
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
import main
from core import Reader, Inbox
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication


def run():
    with tempfile.TemporaryDirectory(prefix='codex-watch-reminder-test-') as temp:
        root = Path(temp)
        main.DATA = root / 'app'
        codex = root / 'codex'
        codex.mkdir()
        rollout = codex / 'test.jsonl'

        def event(kind, ordinal):
            return json.dumps({'type': 'event_msg', 'ordinal': ordinal,
                               'payload': {'type': kind, 'turn_id': 'smoke-turn'}}) + '\n'

        rollout.write_text(event('task_started', 1))
        conn = sqlite3.connect(codex / 'state_5.sqlite')
        conn.execute('CREATE TABLE threads (id,title,name,cwd,source,updated_at,rollout_path,archived)')
        conn.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,0)',
                     ('smoke-thread', 'test', '弹窗联调测试（非真实任务）', str(root), 'vscode', time.time(), str(rollout)))
        conn.commit()
        conn.close()
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        window = main.Window(demo=True)
        window.apply_theme('dark')
        window.inbox = Inbox(root / 'delivery.json')
        window.reader = Reader(codex)
        window.demo = False
        window.configure_pet()
        window.hide()
        window.receive(*window.reader.scan())
        app.processEvents()
        pet_before = window.pet.grab().toImage()
        assert window.pet.isVisible()
        assert window.pet.running == 1
        assert window.current().status == 'running'
        assert not window.reminder.isVisible()

        def checked(callback):
            def wrapper():
                try:
                    callback()
                except Exception:
                    traceback.print_exc()
                    window.reminder.close()
                    app.exit(1)
            return wrapper

        @checked
        def finish_task():
            assert window.pet.grab().toImage() != pet_before, 'Working pet did not animate'
            print('PASS: real desktop pet is visible and its working animation advances', flush=True)
            with rollout.open('a') as f:
                f.write(event('task_complete', 2))
            window.receive(*window.reader.scan())
            assert not window.isVisible()
            assert window.reminder.isVisible()
            QTimer.singleShot(500, verify_popup)

        @checked
        def verify_popup():
            wid = hex(int(window.reminder.winId()))
            info = subprocess.check_output(['xwininfo', '-id', wid], text=True)
            assert 'Map State: IsViewable' in info, info
            props = subprocess.check_output(['xprop', '-id', wid, '_NET_WM_STATE'], text=True)
            assert '_NET_WM_STATE_ABOVE' in props, props
            pet_info = subprocess.check_output(['xwininfo', '-id', hex(int(window.pet.winId()))], text=True)
            assert 'Map State: IsViewable' in pet_info
            assert '喵～工作完成啦' in window.reminder.status.text()
            assert not window.reminder.geometry().intersects(window.pet.geometry())
            window.reminder.grab().save(str(main.ROOT / 'doc/reminder-verified.png'))
            window.pet.grab().save(str(main.ROOT / 'doc/pet-verified.png'))
            print('PASS: hidden main window; real completion event; native popup is viewable and above', flush=True)
            QTest.mouseClick(window.reminder.ack_button, Qt.LeftButton)
            assert not window.reminder.isVisible()
            assert not window.visible_sessions()
            window.receive(*window.reader.scan())
            assert not window.reminder.isVisible()
            assert not window.visible_sessions()
            print('PASS: clicking 知道了 removes the task and subsequent scan does not re-alert', flush=True)
            window.demo = True
            window.close()
            app.exit(0)

        QTimer.singleShot(300, finish_task)
        QTimer.singleShot(15000, lambda: app.exit(2))
        return app.exec_()


if __name__ == '__main__':
    sys.exit(run())
