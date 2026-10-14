import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
from core import Tail, Reader, Inbox, Session, ro_db, process_sessions


def event(kind, ordinal=1, **fields):
    return {'type': 'event_msg', 'ordinal': ordinal, 'payload': {'type': kind, **fields}}


class TailTests(unittest.TestCase):
    def test_final_message_alone_does_not_mean_complete(self):
        t = Tail()
        t.consume(event('task_started', turn_id='t1'))
        t.consume({'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
                    'phase': 'final_answer', 'content': [{'text': 'done'}]}})
        self.assertEqual(t.state['status'], 'running')
        t.consume(event('task_complete', turn_id='t1', last_agent_message='done'))
        self.assertEqual(t.state['status'], 'completed')

    def test_question_persists_during_other_work_then_clears_on_answer(self):
        t = Tail()
        t.consume(event('task_started', turn_id='t1'))
        t.consume(event('item_completed', turn_id='t1', item={'type': 'AgentMessage', 'id': 'q1',
                   'questions': [{'title': 'Which?'}], 'content': [{'text': 'Which?'}]}))
        t.consume(event('item_completed', turn_id='t1', item={'type': 'CommandExecution'}))
        self.assertEqual(t.state['status'], 'waiting')
        t.consume(event('item_completed', turn_id='t1', item={'type': 'UserMessage', 'content': [{'text': 'Option A'}]}))
        self.assertEqual(t.state['status'], 'running')
        self.assertEqual(t.state['question'], '')

    def test_new_turn_resets_previous_result(self):
        t = Tail()
        t.consume(event('task_complete', turn_id='old', last_agent_message='old result'))
        t.consume(event('task_started', turn_id='new'))
        self.assertEqual(t.state['preview'], '')
        self.assertEqual(t.state['status'], 'running')

    def test_midturn_tail_detects_turn_identity(self):
        t = Tail()
        t.consume(event('item_completed', 35, turn_id='new', item={'type': 'CommandExecution'}))
        self.assertEqual(t.state['turn_id'], 'new')
        self.assertEqual(t.state['turn_ordinal'], 35)

    def test_interruption_is_not_completion(self):
        t = Tail()
        t.consume(event('task_started', turn_id='t'))
        t.consume(event('turn_aborted'))
        self.assertEqual(t.state['status'], 'interrupted')

    def test_partial_lines_and_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 's.jsonl'
            p.write_bytes((json.dumps(event('task_started', turn_id='a')) + '\n').encode())
            t = Tail()
            self.assertEqual(t.read(p)['status'], 'running')
            complete = json.dumps(event('task_complete', turn_id='a')).encode()
            with p.open('ab') as f:
                f.write(complete[:20])
            self.assertEqual(t.read(p)['status'], 'running')
            with p.open('ab') as f:
                f.write(complete[20:] + b'\n')
            self.assertEqual(t.read(p)['status'], 'completed')
            p.write_text(json.dumps(event('turn_aborted')) + '\n')
            self.assertEqual(t.read(p)['status'], 'interrupted')


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state.json'
        self.inbox = Inbox(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_baseline_no_flood_then_exactly_one_alert_per_turn(self):
        s = Session('a', status='completed', turn_id='t1', updated=time.time())
        self.assertEqual(self.inbox.reconcile([s]), [])
        self.assertFalse(s.unread)
        self.assertFalse(s.tracked)
        self.assertEqual(self.inbox.reconcile([s]), [])
        self.assertFalse(s.unread)
        s.status, s.turn_id = 'running', 't2'
        self.inbox.reconcile([s])
        s.status = 'completed'
        self.assertEqual(len(self.inbox.reconcile([s])), 1)
        self.assertEqual(self.inbox.reconcile([s]), [])
        self.assertTrue(s.unread)
        self.assertTrue(s.tracked)

    def test_acknowledgement_survives_restart(self):
        s = Session('a', status='running', turn_id='t', updated=time.time())
        self.inbox.reconcile([s])
        s.status = 'completed'
        self.inbox.reconcile([s])
        self.inbox.acknowledge(s)
        other = Inbox(self.path)
        other.reconcile([s])
        self.assertFalse(s.unread)
        self.assertFalse(s.tracked)

    def test_older_closed_history_does_not_fill_inbox(self):
        old = Session('old', status='completed', turn_id='t', updated=time.time()-90000)
        live = Session('live', status='completed', turn_id='t', updated=time.time()-90000, pid=10)
        self.inbox.reconcile([old, live])
        self.assertFalse(old.unread)
        self.assertFalse(live.unread)
        self.assertFalse(live.tracked)

    def test_running_never_unread(self):
        s = Session('a', status='running', turn_id='t', updated=time.time())
        self.inbox.reconcile([s])
        self.assertFalse(s.unread)
        self.assertTrue(s.tracked)

    def test_completion_while_monitor_closed_is_kept(self):
        s = Session('a', status='running', turn_id='t1', updated=time.time())
        self.inbox.reconcile([s])
        s.status = 'completed'
        reopened = Inbox(self.path)
        self.assertEqual(len(reopened.reconcile([s])), 1)
        self.assertTrue(s.tracked)
        self.assertTrue(s.unread)

    def test_dismissed_completion_never_returns_until_new_work(self):
        s = Session('a', status='running', turn_id='t1', updated=time.time())
        self.inbox.reconcile([s])
        s.status = 'completed'
        self.inbox.reconcile([s])
        self.inbox.acknowledge(s)
        for _ in range(3):
            self.assertEqual(self.inbox.reconcile([s]), [])
            self.assertFalse(s.tracked)
        s.turn_id, s.status = 't2', 'running'
        self.inbox.reconcile([s])
        self.assertTrue(s.tracked)

    def test_fast_turn_finished_between_polls_is_not_missed(self):
        self.inbox.reconcile([])
        s = Session('a', status='completed', turn_id='fast', started=time.time(), updated=time.time())
        self.assertEqual(len(self.inbox.reconcile([s])), 1)
        self.assertTrue(s.tracked)

    def test_old_history_inbox_migrates_without_old_reminders(self):
        self.path.write_text(json.dumps({'sessions': {'a': {'observed': 't:completed:'}}, 'preferences': {'theme': 'dark'}}))
        migrated = Inbox(self.path)
        s = Session('a', status='completed', turn_id='t', updated=time.time(), pid=12)
        self.assertEqual(migrated.reconcile([s]), [])
        self.assertFalse(s.tracked)
        self.assertEqual(migrated.data['preferences']['theme'], 'dark')

    def test_observed_but_undelivered_completion_retries_after_restart(self):
        s = Session('a', status='running', turn_id='t1', updated=time.time())
        self.inbox.reconcile([s])
        s.status = 'completed'
        self.inbox.reconcile([s])
        reopened = Inbox(self.path)
        reopened.reconcile([s])
        self.assertEqual(reopened.pending_alerts([s]), [s])
        reopened.mark_presented([s])
        again = Inbox(self.path)
        again.reconcile([s])
        self.assertEqual(again.pending_alerts([s]), [])


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.rollout = self.home / 'session.jsonl'
        self.rollout.write_text(json.dumps(event('task_started', turn_id='t1')) + '\n')
        c = sqlite3.connect(self.home / 'state_5.sqlite')
        c.execute('CREATE TABLE threads (id,title,cwd,source,updated_at,rollout_path,archived)')
        for thread, source in [('a', 'cli'), ('b', 'vscode'), ('c', '{"subagent":{}}')]:
            c.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,0)', (thread, 'test', str(self.home), source, time.time(), str(self.rollout)))
        c.commit()
        c.close()
        self.conn = sqlite3.connect(self.home / 'thread_history_1.sqlite')
        self.conn.execute('CREATE TABLE thread_turns (thread_id,turn_id,rollout_ordinal,status,started_at,completed_at)')
        self.conn.execute('CREATE TABLE thread_items (thread_id,turn_id,rollout_ordinal,item_type,item_json)')
        self.conn.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?)', ('a', 't1', 1, 'inProgress', time.time(), None))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def scan(self):
        with patch('core.process_sessions', return_value=({}, [])):
            return sorted(Reader(self.home).scan()[0], key=lambda s: s.id)

    def test_read_only_and_exclude_internal_agents(self):
        sessions = self.scan()
        self.assertEqual({s.id for s in sessions}, {'a', 'b'})
        c = ro_db(self.home / 'state_5.sqlite')
        with self.assertRaises(sqlite3.OperationalError):
            c.execute('DELETE FROM threads')
        c.close()

    def test_history_index_includes_old_and_archived_without_reading_logs(self):
        c = sqlite3.connect(self.home / 'state_5.sqlite')
        c.execute('UPDATE threads SET archived=1,updated_at=1 WHERE id=?', ('a',))
        c.commit()
        c.close()
        with patch.object(Tail, 'read', side_effect=AssertionError('Index must not read transcripts')):
            sessions = Reader(self.home).history_index()
        self.assertEqual({s.id for s in sessions}, {'a', 'b'})
        self.assertTrue(next(s for s in sessions if s.id == 'a').archived)
        self.assertTrue(all(not s.tracked and not s.unread for s in sessions))

    def test_history_selected_details_stay_out_of_inbox(self):
        self.rollout.write_text(json.dumps(event('task_complete', turn_id='t1', last_agent_message='selected reply'))+'\n')
        reader = Reader(self.home)
        selected = reader.history_detail('a')
        self.assertEqual(selected.preview, 'selected reply')
        self.assertEqual(selected.status, 'completed')
        self.assertFalse(selected.tracked)
        self.assertFalse(selected.unread)
        self.assertEqual(reader.tails, {})
        self.assertEqual([s.id for s in reader.history_index('b')], ['b'])

    def test_history_deleted_log_keeps_metadata_and_explains_missing_preview(self):
        self.rollout.unlink()
        selected = Reader(self.home).history_detail('b')
        self.assertEqual(selected.id, 'b')
        self.assertIn('日志不可读', selected.note)
        self.assertEqual(selected.preview, '')

    def test_missing_home_is_explicit_error(self):
        with self.assertRaisesRegex(RuntimeError, '没有找到'):
            Reader(self.home / 'missing').scan()

    def test_current_window_name_preferred_over_first_prompt(self):
        c = sqlite3.connect(self.home / 'state_5.sqlite')
        c.execute('ALTER TABLE threads ADD COLUMN name')
        c.execute("UPDATE threads SET name='示例项目 · 当前会话名称' WHERE id='b'")
        c.commit()
        c.close()
        sessions = self.scan()
        self.assertEqual(sessions[1].title, '示例项目 · 当前会话名称')
        self.assertEqual(sessions[0].title, 'test')

    def test_history_completion_overrides_missing_log_end(self):
        self.conn.execute("UPDATE thread_turns SET status='completed'")
        self.conn.commit()
        self.assertEqual(self.scan()[0].status, 'completed')

    def test_projection_lag_does_not_revert_newer_log(self):
        self.rollout.write_text(json.dumps(event('task_started', 20, turn_id='t2')) + '\n')
        self.conn.execute("UPDATE thread_turns SET status='completed'")
        self.conn.commit()
        s = self.scan()[0]
        self.assertEqual((s.status, s.turn_id), ('running', 't2'))

    def test_newer_projection_replaces_stale_log(self):
        self.conn.execute("UPDATE thread_turns SET turn_id='t2',rollout_ordinal=20,status='completed'")
        self.conn.commit()
        s = self.scan()[0]
        self.assertEqual((s.status, s.turn_id), ('completed', 't2'))

    def test_completed_log_not_reverted_by_running_projection(self):
        with self.rollout.open('a') as f:
            f.write(json.dumps(event('task_complete', 10, turn_id='t1')) + '\n')
        self.assertEqual(self.scan()[0].status, 'completed')

    def test_stale_running_is_unknown_not_done(self):
        self.conn.close()
        (self.home / 'thread_history_1.sqlite').unlink()
        self.conn = sqlite3.connect(':memory:')
        old = time.time()-1800
        os.utime(self.rollout, (old, old))
        c = sqlite3.connect(self.home / 'state_5.sqlite')
        c.execute('UPDATE threads SET updated_at=?', (old,))
        c.commit()
        c.close()
        self.assertTrue(all(s.status == 'unknown' for s in self.scan()))

    def test_history_question_and_response(self):
        question = {'type': 'agentMessage', 'id': 'q1', 'text': 'Which?', 'questions': [{'title': 'Which?'}]}
        self.conn.execute('INSERT INTO thread_items VALUES (?,?,?,?,?)', ('a', 't1', 2, 'agentMessage', json.dumps(question)))
        self.conn.commit()
        self.assertEqual(self.scan()[0].status, 'waiting')
        answer = {'type': 'userMessage', 'content': [{'text': 'Option A'}]}
        self.conn.execute('INSERT INTO thread_items VALUES (?,?,?,?,?)', ('a', 't1', 3, 'userMessage', json.dumps(answer)))
        self.conn.commit()
        self.assertEqual(self.scan()[0].status, 'running')

    def test_approval_event_survives_projection(self):
        with self.rollout.open('a') as f:
            f.write(json.dumps(event('exec_approval_request', 3, call_id='approval1')) + '\n')
        self.assertEqual(self.scan()[0].status, 'waiting')


class ProcessTests(unittest.TestCase):
    def test_shared_app_server_without_tty_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / '888'
            (p / 'fd').mkdir(parents=True)
            (p / 'comm').write_text('codex\n')
            (p / 'fd/0').symlink_to('/dev/null')
            uid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
            (p / 'fd/10').symlink_to('/home/test/.codex/thread-writer-locks/' + uid + '.lock')
            found, unbound = process_sessions(root)
            self.assertEqual(found[uid], {'pid': 888, 'tty': ''})
            self.assertEqual(unbound, [])

    def test_exact_fd_mapping_no_cwd_guess(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / '123'
            (p / 'fd').mkdir(parents=True)
            (p / 'comm').write_text('codex\n')
            (p / 'fd/0').symlink_to('/dev/pts/7')
            uid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
            (p / 'fd/10').symlink_to('/home/test/.codex/thread-writer-locks/' + uid + '.lock')
            found, unbound = process_sessions(root)
            self.assertEqual(found[uid], {'pid': 123, 'tty': 'pts/7'})
            self.assertEqual(unbound, [])

    def test_resume_command_quotes_shell_metacharacters(self):
        import shlex
        s = Session('abc', cwd="/tmp/space ' $(touch BAD)")
        parts = shlex.split(s.resume_command)
        self.assertEqual(parts[2], s.cwd)


if __name__ == '__main__':
    unittest.main()
