# 开发与反馈指南

## 报告问题

请在 [Issues](https://github.com/weihaoysgs/codex-watch/issues) 中提供：

- 候响版本与 Codex 版本。
- Ubuntu 版本、桌面环境，以及 X11 / Wayland。
- 安装方式：源码或 `.deb`。
- 最小复现步骤、预期结果和实际结果。
- 必要的脱敏日志或截图。

`./run.sh --diagnose` 会省略标题和回复正文，但仍包含项目路径与会话 ID。提交前请删除私人信息；不要提交 `~/.codex`、`auth.json`、真实会话数据库或候响状态目录。

## 本地开发

运行依赖为系统 Python 3.8+、PyQt5 5.14+、libqt5svg5。使用 `/usr/bin/python3` 以匹配 Ubuntu 安装的 PyQt5，不要求通过 pip 安装替代版本。

```bash
sudo apt install python3 python3-pyqt5 libqt5svg5
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s tests -v
./run.sh --demo
```

修改会话识别时，请用临时 SQLite / JSONL 夹具复现，不把真实会话当作测试文件。保持只读访问、完成去重、确认后移除和下一轮重新加入的语义。

修改界面或动画时，请检查浅色 / 深色、最小窗口尺寸、任务运行 / 完成 / 无任务状态。截图必须来自演示或隔离测试数据。

`tests/live_reminder.py` 可在 X11 桌面进行置顶提醒联调，需要 `xwininfo` 和 `xprop`。它创建隔离的模拟会话，但会显示真实测试窗口。

### 真实中文输入回归

Qt 离屏测试无法证明输入法插件可用。`tests/live_input_method.py` 通过真实 X11 按键输入拼音，并断言组词期间没有提前上屏、选词后得到中文。覆盖列表逐键刷新、空队列、目录与详情异步返回、取消后重新组词。

仅在隔离容器中运行，不要连接用户桌面的 DISPLAY 或 D-Bus：

```bash
docker build -f packaging/Dockerfile.ime --build-arg BASE_IMAGE=ubuntu:20.04 -t codex-watch-ime-20 .
docker run --rm --network none codex-watch-ime-20
docker run --rm --network none -e QT_IM_MODULE=ibus codex-watch-ime-20

# Ubuntu 22.04 使用相同脚本，替换基础系统
docker build -f packaging/Dockerfile.ime --build-arg BASE_IMAGE=ubuntu:22.04 -t codex-watch-ime-22 .
docker run --rm --network none codex-watch-ime-22
docker run --rm --network none -e QT_IM_MODULE=ibus codex-watch-ime-22
```

不要用直接注入 Unicode 或 Qt commit 事件代替这项检查：旧版能通过模拟输入，但真实输入法会被列表重绘打断。涉及 Qt 项目视图重建或异步详情更新的修改，应保留这一回归。

## 提交改动

- 在说明中写清改动原因、行为变化与实际执行的验证。
- 保持 Python 3.8 和 Ubuntu 20.04 的 Qt 兼容性。
- 不提交 `dist/`、缓存、令牌、用户配置或真实桌面截图。
- 新增素材须注明来源与许可，不混淆原创部分和第三方部分。
- 重大功能建议先开 Issue 讨论。

项目暂未确定项目级许可证；第三方素材的许可见对应说明。
