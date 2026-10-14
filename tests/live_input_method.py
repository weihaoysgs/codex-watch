"""Real X11 key -> Fcitx/IBus pinyin -> Qt commit integration check.

Run only in an isolated display/session (see packaging/Dockerfile.ime).
Unlike QInputMethodEvent unit tests, this exercises the platform IM plugin.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

if os.environ.get('CODEX_WATCH_IME_TEST') != '1':
    raise SystemExit('Use the isolated IME test container; never type into the user desktop.')
sys.path.insert(0, os.environ.get('CODEX_WATCH_TEST_NATIVE',
                               str(Path(__file__).resolve().parents[1] / 'native')))
from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
import main


def key(name):
    subprocess.run(['xdotool', 'key', '--clearmodifiers', name], check=True, timeout=5)
    QTest.qWait(120)


def check_pinyin(window, refresh, label, syllables='nihao', expected='你好'):
    window.search.clear()
    window.search.setFocus()
    QTest.qWait(150)
    for letter in syllables:
        key(letter)
        refresh()
        QTest.qWait(80)
        assert window.search.text() == '', (label, 'premature commit', window.search.text())
    key('space')
    QTest.qWait(150)
    assert window.search.text() == expected, (label, window.search.text())
    assert window.search.hasFocus(), label
    print('PASS', label, repr(window.search.text()), flush=True)


app = QApplication([])
app.setQuitOnLastWindowClosed(False)
print('Qt', QT_VERSION_STR, 'PyQt', PYQT_VERSION_STR, flush=True)
with tempfile.TemporaryDirectory() as temp:
    main.DATA = Path(temp)
    window = main.Window(demo=True)
    window.timer.stop()  # All refreshes below use synthetic sessions explicitly.
    window.show()
    QTest.qWait(300)
    subprocess.run(['xdotool', 'windowfocus', '--sync', str(int(window.winId()))],
                   check=True, timeout=5)
    window.search.setFocus()
    QTest.qWait(200)
    if os.environ.get('QT_IM_MODULE') == 'ibus':
        # Without a desktop keyboard manager this command can return 1 even
        # after selecting the engine. Verify the resulting engine explicitly.
        subprocess.run(['ibus', 'engine', 'libpinyin'], timeout=5)
        QTest.qWait(300)
        engine = subprocess.check_output(['ibus', 'engine'], text=True, timeout=5).strip()
        assert engine == 'libpinyin', ('IBus engine not ready', engine)
    else:
        subprocess.run(['fcitx-remote', '-s', 'pinyin'], check=True, timeout=5)
        subprocess.run(['fcitx-remote', '-o'], check=True, timeout=5)
    QTest.qWait(300)
    try:
        check_pinyin(window, window.render, 'active queue: refresh between every key')
        window.search.clear()
        window.receive([], [])
        check_pinyin(window, window.render, 'empty queue: refresh between every key')
        window.nav.setCurrentRow(3)
        check_pinyin(window, lambda: window.history.receive_index(main.demo_sessions()),
                     'history: asynchronous directory refresh')
        window.search.clear()
        panel = window.history
        session = main.Session('detail-ime', title='你好，中文任务', preview='异步回复')
        panel.receive_index([session])
        panel.selected = 'detail-ime'
        panel.generation = 100
        check_pinyin(window, lambda: panel.receive_detail(session, 100),
                     'history: asynchronous detail refresh')
        assert panel.body.toPlainText() == '异步回复', 'deferred detail not applied'
        window.nav.setCurrentRow(0)
        window.search.clear()
        window.search.setFocus()
        key('n')
        key('Escape')
        QTest.qWait(150)
        assert not window.search.input_busy(), 'cancel left search stuck'
        check_pinyin(window, window.render, 'new composition after cancellation')
        window.search.clear()
        window.demo = False
        session = main.Session('live-ime', status='running', turn_id='t', updated=main.time.time())
        window.receive([session], [])

        def complete_task():
            session.status = 'completed'
            window.receive([session], [])
            assert session.unread and window.reminder.isVisible(), 'completion reminder delayed'

        check_pinyin(window, complete_task, 'completion reminder during composition')
        window.demo = True
    finally:
        window.demo = True
        window.close()
        app.processEvents()
