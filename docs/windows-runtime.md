# Windows 桌面运行与验证

StreamCap 使用 Python 3.12+、Flet、SQLite 和 FFmpeg。Python 依赖由 pip 按
`requirements.txt` 安装，测试位于 `tests`，打包入口为 `scripts/build.py`。

## 启动与进程归属

`main.py` 先执行 `multiprocessing.freeze_support()`，再进入 `launcher.py`。
Windows 启动器在导入会读写配置的 `app` 包之前，取得当前用户 SID 对应的命名互斥锁，
并创建不继承句柄的 Job Object。Job Object 创建或关联失败时启动失败，不降级为无保护录制。

同一 Windows 用户的源码版、桌面 EXE 和 Web 后台共用一个锁。重复启动桌面版会通知已有
窗口恢复显示；已有 Web 后台时显示其访问地址。多个浏览器会话仍共享同一个后台。

正常退出先禁止新录制，给已启动的 FFmpeg 发送 `q`，并行等待退出，超时后强制终止。
停止录制进程和收尾任务的等待预算为 15 秒；配置保存、窗口销毁另行完成。
转码、脚本也通过同一个进程管理器启动，退出期间不追加转换任务。
中断转换时保留原始文件，即使 FFmpeg 接收 `q` 后返回成功状态也不删除原文件。

Windows 后台异常退出时，内核关闭 Job Object 句柄并终止其子进程树；Flet 窗口进程异常
退出时，后台执行同一清理流程。最小化到托盘和关闭 Web 标签页不会停止后台。
此内核级保证仅针对 Windows。其他系统保留正常退出清理，不承诺强杀后的子进程行为。

旧版本未纳入 Job Object 的 FFmpeg 不会被批量终止。启动检查只列出同用户、输出位于配置
录制目录的候选任务；确认前暂停录制。对用户选中的任务，重新核对 PID、创建时间和映像
路径后才结束，保留已有文件。界面不显示流地址或完整命令行。

## 包结构与数据

Windows 包位于 `dist/StreamCap`，目录如下。构建只包含三个默认 JSON，不包含本地账户、
Cookies 或录制数据库；用户配置、数据库和日志在运行时生成。保留 JSON 配置格式和现有
SQLite 文件名，不使用示例 INI 配置，也不自动迁移数据库。

```text
StreamCap/
├── StreamCap.exe
├── version.txt
├── config/                 # 默认配置及运行时生成的用户配置
├── logs/                   # 写日志时创建，app.log、error.log、play_url.log
├── data/                   # 使用相关功能时创建
│   ├── database/           # recordings.db，运行时生成
│   └── recordings/         # 新安装默认录制目录
├── resources/              # 图标、图片、语言文件及其他静态资源
│   ├── icons/
│   ├── images/
│   └── locales/
├── runtime/
│   ├── ffmpeg/
│   ├── node/
│   └── flet/               # 已解压的桌面客户端，无需首次联网下载
└── _internal/              # Python DLL 和 PyInstaller 收集的 Python 依赖
```

打包不预建日志、数据目录或没有功能使用的占位目录。
新安装把配置、数据和日志放在 EXE 旁，因此需解压到当前用户可写目录。
若检测到 `%APPDATA%/StreamCap` 已有用户配置或数据库，继续使用原位置；EXE 旁已有便携数据
时优先使用便携数据。保留已配置的录制路径和已有 `downloads` 目录。旧包把资源放在
`_internal` 或根目录的布局仍可读取。启动异常日志仍位于
`%LOCALAPPDATA%/StreamCap/runtime/startup-error.log`。

## 构建与检查

在 Windows、已安装项目及开发依赖的 Python 环境中运行：

```powershell
python -m unittest discover -v
python -m ruff check .
python -m ruff format --check .
python scripts/download_ffmpeg.py --platform windows
python scripts/download_nodejs.py --platform windows --windows-arch x64
python scripts/build.py --platform windows
python scripts/smoke_desktop.py dist/StreamCap
```

桌面检查复制真实安装包到含中文和空格的临时目录，使用隔离用户环境、移除开发机
工具路径、设置不可用的 HTTP 代理，然后启动 EXE。检查主页已加载、窗口可见、重复启动
不多开，新配置、数据库和日志位于便携目录，不创建外部 Flet 缓存，以及正常退出、前端强退、
后台强退后的子进程退出。独立的 FFmpeg 必须继续运行，
正常退出生成的媒体文件必须能解码。检查通过才允许 CI 上传 Windows 包和发布 beta。

隐藏参数 `--smoke-test` 仅供构建验证：禁用真实直播录制、安装检查、更新和定时关机，
只创建临时合成音频任务。不要用它启动日常录制。
