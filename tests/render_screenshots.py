"""Publish-safe screenshots: synthetic sessions and a temporary app data directory."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
from PyQt5.QtWidgets import QApplication
import main


def run():
    with tempfile.TemporaryDirectory() as temp:
        main.DATA = Path(temp)
        app = QApplication([])
        app.setStyle('Fusion')
        window = main.Window(demo=True)
        window.show()
        out = main.ROOT / 'doc'
        out.mkdir(exist_ok=True)
        for theme in ('light', 'dark'):
            window.apply_theme(theme)
            app.processEvents()
            window.grab().save(str(out / (theme + '.png')))
        window.apply_theme('light')
        window.history.demo.append(main.Session(
            'demo-archive', title='整理项目说明，补充部署步骤', cwd='/home/demo/Projects/desktop-app',
            status='completed', archived=True, updated=1700000000,
            preview='项目说明已整理完成。\n\n· 补充了安装与运行步骤\n· 添加了配置项说明\n· 核对了截图和文档链接\n\n这是用于展示会话目录的演示记录。'))
        window.nav.setCurrentRow(3)
        window.history.tree.expandAll()
        for i in range(window.history.tree.topLevelItemCount()):
            group = window.history.tree.topLevelItem(i)
            for j in range(group.childCount()):
                if group.child(j).data(0, main.Qt.UserRole) == 'demo-archive':
                    window.history.tree.setCurrentItem(group.child(j))
        app.processEvents()
        window.grab().save(str(out / 'history.png'))
        window.close()


if __name__ == '__main__':
    run()
