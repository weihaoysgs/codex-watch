#!/usr/bin/python3
"""Install only this app's launcher; no sudo, no Codex configuration edits."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'native'))
from main import desktop_entry

dest = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'applications/io.local.CodexWatch.desktop'
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(desktop_entry())
dest.chmod(0o755)
print('已安装应用菜单入口：' + str(dest))
print('搜索“候响”或“Codex Watch”即可打开。登录自启动默认关闭，可在应用设置中开启。')
