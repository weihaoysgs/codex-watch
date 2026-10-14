"""Read-only Codex adapters and durable notification state. No Qt dependency."""
from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import time
from datetime import datetime
from dataclasses import dataclass, field, asdict
from pathlib import Path
from urllib.parse import quote

UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
LABELS = {'running': '进行中', 'waiting': '待回复', 'completed': '已完成',
          'interrupted': '已中断', 'failed': '出错了', 'unknown': '待确认', 'idle': '尚未开始'}
ATTENTION = {'waiting', 'completed', 'interrupted', 'failed', 'unknown'}


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        os.chmod(tmp, 0o600)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def ro_db(path):
    conn = sqlite3.connect('file:' + quote(str(path)) + '?mode=ro', uri=True, timeout=.3)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn


def newest_db(home, stem):
    paths = list(home.glob(stem + '_*.sqlite'))
    return max(paths, key=lambda p: int(p.stem.rsplit('_', 1)[1])) if paths else None


def content_text(item):
    if isinstance(item.get('text'), str):
        return item['text']
    return '\n'.join(x.get('text', '') for x in item.get('content', []) if isinstance(x, dict))


@dataclass
class Session:
    id: str
    title: str = ''
    cwd: str = ''
    source: str = 'cli'
    status: str = 'unknown'
    turn_id: str = ''
    updated: float = 0
    started: float = 0
    preview: str = ''
    question: str = ''
    question_id: str = ''
    pid: int = 0
    tty: str = ''
    note: str = ''
    rollout: str = ''
    unread: bool = False
    tracked: bool = False
    archived: bool = False

    @property
    def token(self):
        return f'{self.turn_id}:{self.status}:{self.question_id if self.status == "waiting" else ""}'

    @property
    def project(self):
        return Path(self.cwd).name or self.cwd or '未指定项目'

    @property
    def resume_command(self):
        return f'cd -- {shlex.quote(self.cwd or str(Path.home()))} && codex resume {shlex.quote(self.id)}'


class Tail:
    """Incremental bounded JSONL reader; partial records are retried, never consumed."""
    def __init__(self):
        self.offset = 0
        self.identity = None
        self.state = {}

    def read(self, path):
        path = Path(path)
        st = path.stat()
        identity = (st.st_dev, st.st_ino)
        if self.identity != identity or st.st_size < self.offset:
            self.state = {}
            self.offset = max(0, st.st_size - 1024 * 1024)
            self.identity = identity
            discard_first = self.offset > 0
        else:
            discard_first = False
        with path.open('rb') as f:
            f.seek(self.offset)
            if discard_first:
                f.readline()
                self.offset = f.tell()
            # Read at most 4 MiB per poll; catch up on following polls.
            stop = f.tell() + 4 * 1024 * 1024
            while f.tell() < stop:
                line = f.readline(4 * 1024 * 1024)
                if not line or not line.endswith(b'\n'):
                    break
                self.offset = f.tell()
                try:
                    self.consume(json.loads(line))
                except (ValueError, TypeError, AttributeError):
                    continue
        return self.state

    def consume(self, record):
        p = record.get('payload', {})
        kind = p.get('type')
        s = self.state
        if record.get('type') == 'event_msg':
            if kind in ('task_started', 'turn_started'):
                s.update(status='running', turn_id=p.get('turn_id', ''), question='', question_id='', preview='',
                         turn_ordinal=record.get('ordinal', -1))
            elif kind in ('task_complete', 'turn_complete'):
                s.update(status='completed', turn_id=p.get('turn_id', s.get('turn_id', '')),
                         preview=p.get('last_agent_message') or s.get('preview', ''), question='', question_id='')
            elif kind in ('turn_aborted', 'task_interrupted'):
                s.update(status='interrupted', question='', question_id='')
            elif kind in ('exec_approval_request', 'apply_patch_approval_request'):
                s.update(status='waiting', question='此终端正在请求操作审批，请回到原终端确认。',
                         question_id=p.get('call_id', 'approval'))
            elif kind in ('exec_command_begin', 'patch_apply_begin') and s.get('question_id') == p.get('call_id'):
                s.update(status='running', question='', question_id='')
            elif kind == 'user_message':
                # A user message alone does not establish a running turn.
                self.answer(p.get('message', ''))
            elif kind == 'agent_message':
                s['preview'] = p.get('message', '')
            elif kind == 'item_completed':
                if p.get('turn_id') and p['turn_id'] != s.get('turn_id'):
                    s.update(status='running', turn_id=p['turn_id'], question='', question_id='', preview='',
                             turn_ordinal=record.get('ordinal', -1))
                self.item(p.get('item', {}))
        elif record.get('type') == 'response_item':
            if kind == 'message' and p.get('role') == 'assistant':
                s['preview'] = content_text(p)
            elif kind == 'message' and p.get('role') == 'user':
                self.answer(content_text(p))

    def answer(self, text):
        s = self.state
        if s.get('question_id') and (s['question_id'] in text or '<send_user_message_question_reply>' not in text):
            s.update(question='', question_id='')
            if s.get('status') == 'waiting':
                s['status'] = 'running'

    def item(self, item):
        kind = item.get('type', '').lower()
        if kind == 'usermessage':
            self.answer(content_text(item))
        elif kind == 'agentmessage':
            text = content_text(item)
            if text:
                self.state['preview'] = text
            if item.get('questions'):
                self.state.update(question=text or '\n'.join(q.get('title', '') for q in item['questions']),
                                  question_id=item.get('id', ''), status='waiting')


def process_sessions(proc=Path('/proc')):
    """Exact fd→thread association for both standalone CLI and shared app-server."""
    result = {}
    unmapped = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / 'comm').read_text().strip() != 'codex':
                continue
            tty = os.readlink(entry / 'fd/0')
            is_terminal = tty.startswith('/dev/pts/')
            ids = set()
            for fd in (entry / 'fd').iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                if '/sessions/' in target or '/thread-writer-locks/' in target:
                    match = re.search(UUID, Path(target).name)
                    if match:
                        ids.add(match.group())
            # is_terminal already proves the prefix; slicing also works on Python 3.8.
            value = {'pid': int(entry.name), 'tty': tty[len('/dev/'):] if is_terminal else ''}
            for thread in ids:
                if thread not in result or is_terminal:
                    result[thread] = value
            if not ids and is_terminal:
                unmapped.append(value)
        except (OSError, ValueError):
            continue
    return result, unmapped


class Reader:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        self.tails = {}

    def history_index(self, sid=None):
        """Metadata only: all ages and archived user sessions, no monitor enrollment."""
        path = newest_db(self.home, 'state')
        if not path:
            raise RuntimeError('没有找到 Codex 会话索引，请先使用 Codex 并检查 CODEX_HOME。')
        conn = ro_db(path)
        try:
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(threads)')}
            name = "COALESCE(NULLIF(name,''),title)" if 'name' in columns else 'title'
            archived = 'archived' if 'archived' in columns else '0'
            query = (f'SELECT id,{name} AS title,cwd,source,updated_at,rollout_path,{archived} AS archived '
                     "FROM threads WHERE source IN ('cli','vscode')")
            args = ()
            if sid is not None:
                query += ' AND id=?'
                args = (sid,)
            rows = conn.execute(query + ' ORDER BY updated_at DESC,id', args).fetchall()
            return [Session(id=r['id'], title=(r['title'] or '未命名会话').replace('\n', ' ')[:220],
                            cwd=r['cwd'] or '', source=r['source'], updated=r['updated_at'] or 0,
                            rollout=r['rollout_path'] or '', archived=bool(r['archived']),
                            note='历史会话，仅查看，不加入提醒队列。') for r in rows]
        finally:
            conn.close()

    def history_detail(self, sid):
        """Load only the selected session. Fresh tail never mutates the live reader."""
        rows = self.history_index(sid)
        if not rows:
            raise RuntimeError('这条会话已不在本地索引中，请刷新列表。')
        session = rows[0]
        tail = Tail()
        notes = []
        try:
            state = tail.read(session.rollout)
            for key in ('status', 'turn_id', 'preview', 'question', 'question_id'):
                if key in state:
                    setattr(session, key, state[key])
        except OSError:
            notes.append('会话日志不可读或已被删除。')
        history_path = newest_db(self.home, 'thread_history')
        if history_path:
            conn = ro_db(history_path)
            try:
                self.project_history(conn, session, tail.state.get('turn_ordinal', -1))
            except sqlite3.Error:
                notes.append('轮次索引暂不可用，显示日志中可读取的信息。')
            finally:
                conn.close()
        session.note = ' '.join(notes + ['仅显示本地记录的最近状态与回复，不代表该会话当前仍在运行。'])
        session.tracked = session.unread = False
        return session

    def scan(self):
        path = newest_db(self.home, 'state')
        if not path:
            raise RuntimeError(f'没有找到 Codex 会话索引：{self.home}。请先运行一次 Codex CLI。')
        processes, unmapped = process_sessions()
        conn = ro_db(path)
        try:
            # All user threads, no guardian/subagent noise; old open terminals must remain visible.
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(threads)')}
            display_name = "COALESCE(NULLIF(name,''),title)" if 'name' in columns else 'title'
            rows = conn.execute(f"SELECT id,{display_name} AS title,cwd,source,updated_at,rollout_path FROM threads "
                                "WHERE archived=0 AND source IN ('cli','vscode') ORDER BY updated_at DESC").fetchall()
        finally:
            conn.close()
        history_path = newest_db(self.home, 'thread_history')
        history = ro_db(history_path) if history_path else None
        sessions = []
        warnings = []
        try:
            for row in rows:
                s = Session(id=row['id'], title=row['title'].replace('\n', ' ')[:220], cwd=row['cwd'],
                            source=row['source'], updated=row['updated_at'], rollout=row['rollout_path'])
                if s.id in processes:
                    s.pid, s.tty = processes[s.id]['pid'], processes[s.id]['tty']
                # Retain open sessions even when their metadata is older than 30 days.
                if not s.pid and time.time() - s.updated > 30 * 86400:
                    continue
                tail = self.tails.setdefault(s.id, Tail())
                try:
                    state = tail.read(s.rollout)
                    for key in ('status', 'turn_id', 'preview', 'question', 'question_id'):
                        if key in state:
                            setattr(s, key, state[key])
                    s.updated = max(s.updated, Path(s.rollout).stat().st_mtime)
                except OSError:
                    s.note = '会话日志不可读；显示已有索引记录'
                if history:
                    self.project_history(history, s, tail.state.get('turn_ordinal', -1))
                if s.status == 'running' and not s.pid and time.time() - s.updated > 900:
                    s.status = 'unknown'
                    s.note = '未关联到终端，且超过 15 分钟没有新事件；不能确定是否仍在运行'
                elif s.status == 'waiting':
                    s.note = '有问题需要你回复；任务可能仍在后台继续'
                elif s.status == 'running' and time.time() - s.updated > 300:
                    s.note = '暂时没有新事件；长任务不等于已完成'
                if not s.title:
                    s.title = s.project + ' · ' + s.id[:8]
                sessions.append(s)
        finally:
            if history:
                history.close()
        known_ids = {s.id for s in sessions}
        unresolved = unmapped + [v for k, v in processes.items() if k not in known_ids]
        # Dedupe by pid: a process may retain several historical thread handles.
        unresolved = list({v['pid']: v for v in unresolved if not any(s.pid == v['pid'] for s in sessions)}.values())
        # An idle frontend may have no thread handles at all when using the shared daemon.
        # Do not turn every idle terminal into an unexplained warning in an active-only monitor.
        return sessions, warnings

    @staticmethod
    def project_history(conn, s, tail_ordinal=-1):
        turn = conn.execute('SELECT * FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal DESC LIMIT 1', (s.id,)).fetchone()
        if not turn:
            return
        # The log can be ahead of the SQLite projection. Do not overwrite a newer turn.
        if s.turn_id and s.turn_id != turn['turn_id']:
            if tail_ordinal > turn['rollout_ordinal']:
                return
            s.status, s.preview, s.question, s.question_id = 'unknown', '', '', ''
        s.turn_id = turn['turn_id']
        s.started = turn['started_at'] or 0
        db_status = {'inProgress': 'running', 'completed': 'completed', 'failed': 'failed', 'interrupted': 'interrupted'}.get(turn['status'], 'unknown')
        # Terminal rollout events take precedence over a projection that has not caught up.
        if s.status not in ('completed', 'interrupted', 'waiting') or db_status != 'running':
            s.status = db_status
        if s.status == 'failed' and 'error_json' in turn.keys() and turn['error_json']:
            try:
                error = json.loads(turn['error_json'])
                s.note = str(error.get('message', error) if isinstance(error, dict) else error)[:1500]
            except (ValueError, TypeError):
                s.note = str(turn['error_json'])[:1500]
        items = conn.execute("SELECT item_json FROM thread_items WHERE thread_id=? AND turn_id=? "
                             "AND item_type IN ('agentMessage','userMessage') ORDER BY rollout_ordinal DESC LIMIT 80",
                             (s.id, s.turn_id)).fetchall()
        question = ''
        question_id = ''
        preview = ''
        for row in reversed(items):
            try:
                item = json.loads(row['item_json'])
                if item.get('type') == 'userMessage':
                    text = content_text(item)
                    if question_id and (question_id in text or '<send_user_message_question_reply>' not in text):
                        question = question_id = ''
                elif item.get('type') == 'agentMessage':
                    preview = content_text(item) or preview
                    if item.get('questions'):
                        question, question_id = preview, item.get('id', '')
            except (ValueError, TypeError):
                continue
        if not s.preview:
            s.preview = preview
        if s.status == 'running' and question:
            s.status, s.question, s.question_id = 'waiting', question, question_id


class Inbox:
    """Watch a live turn, keep its completion until acknowledged, never import history."""
    def __init__(self, path):
        self.path = Path(path)
        self.data = read_json(path, {})
        if not isinstance(self.data, dict):
            self.data = {}
        self.data.setdefault('sessions', {})
        self.data.setdefault('preferences', {})
        # v1 was a history inbox. Do not migrate old completion badges into the live queue.
        if self.data.get('monitor_version') != 2:
            self.data['sessions'] = {}
            self.data['monitor_version'] = 2
        self.started = False
        self.monitor_started = time.time()

    def reconcile(self, sessions):
        alerts = []
        changed = not self.started
        for s in sessions:
            records = self.data['sessions']
            record = records.setdefault(s.id, {})
            previous = dict(record)
            active = s.status in ('running', 'waiting')
            finished_between_polls = (self.started and record.get('observed') != s.token
                                      and s.status in ATTENTION and s.started >= int(self.monitor_started))
            if (active or finished_between_polls) and s.turn_id:
                record['watched_turn'] = s.turn_id
            watched = bool(s.turn_id and record.get('watched_turn') == s.turn_id)
            s.unread = watched and s.status in ATTENTION and record.get('seen') != s.token
            s.tracked = s.status == 'running' or s.unread
            if record.get('observed') != s.token:
                # A tracked turn that finished while the monitor was closed is still pending.
                # Historical completions that were never observed running never enter the queue.
                if s.unread:
                    alerts.append(s)
                record['observed'] = s.token
            if record != previous:
                changed = True
        self.started = True
        if changed:
            self.save()
        return alerts

    def acknowledge(self, session):
        self.data['sessions'].setdefault(session.id, {})['seen'] = session.token
        session.unread = False
        session.tracked = session.status == 'running'
        self.save()

    def pending_alerts(self, sessions):
        """Observation is not delivery: paused/failed notifications remain eligible."""
        return [s for s in sessions if s.unread and
                self.data['sessions'].get(s.id, {}).get('presented') != s.token]

    def mark_presented(self, sessions):
        for s in sessions:
            self.data['sessions'].setdefault(s.id, {})['presented'] = s.token
        self.save()

    def save(self):
        atomic_json(self.path, self.data)


def dump_sessions(home=None):
    sessions, warnings = Reader(home).scan()
    return {'sessions': [asdict(s) for s in sessions], 'warnings': warnings}
