import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
import main
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt5.QtGui import QMouseEvent


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_data = main.DATA
        main.DATA = Path(self.tmp.name)
        self.w = main.Window(demo=True)
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        main.DATA = self.original_data
        self.tmp.cleanup()

    def test_selection_does_not_ack_and_explicit_ack_works(self):
        self.assertTrue(self.w.current().unread)
        self.w.show_detail()
        self.assertTrue(self.w.current().unread)
        old = self.w.current()
        self.w.acknowledge()
        self.assertFalse(old.unread)
        self.assertNotIn(old.id, [s.id for s in self.w.visible_sessions()])
        self.w.receive(self.w.sessions, [])
        self.assertNotIn(old.id, [s.id for s in self.w.visible_sessions()])

    def test_titlebar_drag_on_older_qt_without_system_move(self):
        chrome = self.w.findChild(main.Chrome)
        self.w.move(80, 80)
        origin = self.w.pos()
        start = origin + QPoint(60, 20)
        with patch.object(self.w, 'windowHandle', return_value=object()):
            chrome.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(60, 20), QPointF(start),
                                              Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        moved = start + QPoint(40, 35)
        chrome.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(100, 55), QPointF(moved),
                                         Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(self.w.pos(), origin + QPoint(40, 35))
        chrome.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(100, 55), QPointF(moved),
                                            Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.assertIsNone(chrome.drag_offset)

    def test_history_groups_full_paths_and_never_enrolls_or_acknowledges(self):
        before = self.w.inbox.path.read_bytes()
        self.w.nav.setCurrentRow(3)
        self.w.history.receive_index([
            main.Session('h1', title='历史一', cwd='/a/same', preview='第一条回复', archived=True),
            main.Session('h2', title='历史二', cwd='/b/same', preview='第二条回复')])
        self.assertEqual(self.w.history.tree.topLevelItemCount(), 2)
        self.assertFalse(self.w.ack_all.isVisible())
        self.w.history.tree.setCurrentItem(self.w.history.tree.topLevelItem(0).child(0))
        self.assertEqual(self.w.history.body.toPlainText(), '第一条回复')
        self.assertIn('已归档', self.w.history.meta.text())
        self.w.acknowledge_all()
        self.w.acknowledge()
        self.assertEqual(self.w.inbox.path.read_bytes(), before)
        self.assertNotIn('h1', self.w.inbox.data['sessions'])
        self.w.search.setText('/b/same')
        self.assertEqual(self.w.history.tree.topLevelItemCount(), 1)
        self.assertEqual(self.w.history.body.toPlainText(), '')
        self.w.search.clear()
        self.w.nav.setCurrentRow(0)
        self.assertTrue(self.w.ack_all.isVisible())
        self.assertEqual(self.w.pages.currentIndex(), 0)

    def test_history_late_reply_cannot_replace_new_selection(self):
        self.w.nav.setCurrentRow(3)
        self.w.history.selected = 'new'
        self.w.history.generation = 8
        self.w.history.body.setPlainText('当前内容')
        old = main.Session('old', preview='过时结果')
        self.w.history.receive_detail(old, 7)
        self.assertEqual(self.w.history.body.toPlainText(), '当前内容')

    def test_search_and_empty_state_clear_stale_detail(self):
        self.w.search.setText('robotics-sim')
        self.assertEqual(self.w.list.count(), 1)
        self.w.search.setText('nonexistent xyz')
        self.assertEqual(self.w.list.count(), 0)
        self.assertFalse(self.w.copy.isEnabled())
        self.assertEqual(self.w.preview.toPlainText(), '')

    def test_filters_and_copy_resume(self):
        self.w.nav.setCurrentRow(2)
        self.assertEqual(self.w.list.count(), 2)
        self.w.copy_resume()
        self.assertIn('codex resume', self.app.clipboard().text())

    def test_question_visible_and_dark_minimum_layout_readable(self):
        self.assertIn('【需要你回复】', self.w.preview.toPlainText())
        self.w.apply_theme('dark')
        self.w.resize(1060, 760)
        self.app.processEvents()
        self.assertGreaterEqual(self.w.preview.height(), 100)
        self.assertGreaterEqual(self.w.detail_meta.height(), 38)
        self.assertTrue(self.w.ack.isVisible())
        self.assertLessEqual(self.w.ack.geometry().bottom(), self.w.ack.parent().height())

    def test_live_transition_reaches_notification_once(self):
        # Exercise actual receive -> durable inbox -> Qt notification handoff.
        self.w.demo = False
        s = main.Session('new-live', title='test task', status='running', turn_id='live-1', updated=main.time.time())
        with patch.object(self.w.tray, 'showMessage') as send:
            self.w.receive([s], [])
            send.assert_not_called()
            s.status = 'completed'
            self.w.receive([s], [])
            send.assert_called_once()
            self.w.receive([s], [])
            send.assert_called_once()
            self.assertTrue(self.w.current().unread)
            self.assertTrue(self.w.reminder.isVisible())
        self.w.demo = True

    def test_vscode_labeled_active_window_visible_without_history(self):
        running = main.Session('target', title='示例项目 · 当前会话名称', source='vscode',
                               status='running', turn_id='t', updated=main.time.time())
        old = main.Session('old-completed', status='completed', turn_id='old', updated=main.time.time(), pid=20)
        self.w.receive([running, old], [])
        self.assertEqual(self.w.list.count(), 1)
        self.assertEqual(self.w.current().title, running.title)
        self.assertFalse(old.tracked)

    def test_all_acknowledged_queue_is_empty(self):
        done = main.Session('done', status='running', turn_id='t', updated=main.time.time())
        self.w.receive([done], [])
        done.status = 'completed'
        self.w.receive([done], [])
        self.w.acknowledge_all()
        self.assertEqual(self.w.list.count(), 0)
        self.w.receive([done], [])
        self.assertEqual(self.w.list.count(), 0)

    def live_completion(self):
        self.w.demo = False
        s = main.Session('popup-task', title='弹窗验证任务', status='running', turn_id='p1', updated=main.time.time())
        self.w.receive([s], [])
        s.status = 'completed'
        self.w.receive([s], [])
        self.app.processEvents()
        return s

    def test_hidden_main_window_still_shows_popup_and_button_removes_task(self):
        self.w.hide()
        s = self.live_completion()
        self.assertFalse(self.w.isVisible())
        self.assertTrue(self.w.reminder.isVisible())
        self.assertIn('弹窗验证任务', self.w.reminder.title.text())
        QTest.mouseClick(self.w.reminder.ack_button, Qt.LeftButton)
        self.assertFalse(s.unread)
        self.assertFalse(self.w.reminder.isVisible())
        self.w.receive([s], [])
        self.assertFalse(self.w.reminder.isVisible())
        self.w.demo = True

    def test_pause_does_not_consume_delivery(self):
        self.w.pause_until = main.time.time() + 1800
        s = self.live_completion()
        self.assertFalse(self.w.reminder.isVisible())
        self.assertEqual(self.w.inbox.pending_alerts([s]), [s])
        self.w.toggle_pause()
        self.assertTrue(self.w.reminder.isVisible())
        self.assertEqual(self.w.inbox.pending_alerts([s]), [])
        self.w.demo = True

    def test_later_hides_card_without_acknowledging(self):
        s = self.live_completion()
        self.w.reminder.hide()
        self.w.receive([s], [])
        self.assertFalse(self.w.reminder.isVisible())
        self.assertTrue(s.unread)
        self.w.demo = True

    def test_stale_popup_cannot_acknowledge_new_turn(self):
        s = self.live_completion()
        old_token = s.token
        s.turn_id, s.status = 'p2', 'running'
        self.w.receive([s], [])
        s.status = 'completed'
        self.w.receive([s], [])
        self.w.acknowledge_reminder(s.id, old_token)
        self.assertTrue(s.unread)
        self.assertTrue(self.w.reminder.isVisible())
        self.w.demo = True

    def test_pet_bubble_and_ack_with_multiple_running_jobs(self):
        self.w.demo = False
        self.w.configure_pet()
        a = main.Session('a', status='running', turn_id='a1', updated=main.time.time())
        b = main.Session('b', status='running', turn_id='b1', updated=main.time.time())
        with patch.object(QApplication, 'beep') as beep:
            self.w.receive([a, b], [])
            self.assertEqual(self.w.pet.running, 2)
            a.status = 'completed'
            self.w.receive([a, b], [])
            self.assertEqual(self.w.pet.running, 1)
            self.assertEqual(self.w.pet.pending, 1)
            self.assertIn('喵～工作完成啦', self.w.reminder.status.text())
            self.assertTrue(self.w.pet.bubble_visible)
            self.assertTrue(self.w.reminder.isVisible())
            beep.assert_not_called()
            self.w.set_pet('dog')
            self.assertIn('汪～', self.w.reminder.status.text())
            self.w.pet.move(100, 420)
            self.assertFalse(self.w.reminder.geometry().intersects(self.w.pet.geometry()))
            QTest.mouseClick(self.w.reminder.ack_button, Qt.LeftButton)
            self.assertFalse(a.tracked)
            self.assertTrue(b.tracked)
            self.assertEqual(self.w.pet.running, 1)
            self.assertEqual(self.w.pet.pending, 0)
            self.assertFalse(self.w.pet.bubble_visible)
        self.w.demo = True

    def test_pet_hidden_still_delivers_popup(self):
        self.w.set_pet('none')
        s = self.live_completion()
        self.assertFalse(self.w.pet.isVisible())
        self.assertFalse(self.w.pet.timer.isActive())
        self.assertTrue(self.w.reminder.isVisible())
        self.assertNotIn('喵', self.w.reminder.status.text())
        self.w.acknowledge_reminder(s.id, s.token)
        self.w.demo = True


if __name__ == '__main__':
    unittest.main()
