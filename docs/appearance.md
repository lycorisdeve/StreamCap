# 外观与录制页

在「设置 → 外观设置」选择浅色、深色或跟随系统，以及六套预设主题色。新安装默认使用梦幻紫 `#7555F6` 和浅色模式；已有配置中的颜色名和明暗模式继续兼容。

自定义颜色支持 HSV 面板、滑条和三位／六位 HEX。选择后仅在当前窗口预览；点击「应用」保存到现有 `config/user_settings.json`，并同步其他 Web 会话。「取消修改」或离开设置页会恢复最近已保存的外观。其他会话在预览时收到新配置，会保留自己的草稿，取消时使用最新保存值。「恢复默认外观」需要点击应用才会保存。

侧栏日夜按钮使用同一个主题管理器：没有草稿时立即保存，有草稿时只修改当前预览。跟随系统时，每个 Web 客户端按各自的系统明暗显示。

品牌色由 `app/ui/themes/theme_tokens.py` 派生。主色保持输入值，文字、交互色及焦点色根据对比度调整；导航、按钮、输入框、弹窗和卡片交互状态共享主题。录制、直播、检查、未开播、错误、停止监控的语义色以及卡片 2 像素状态边框不受主题色影响。

录制页提供常驻搜索框，支持 `Ctrl+F` 聚焦。搜索与状态、平台筛选同时生效；清空搜索保留其他筛选条件。网格根据实际可用宽度调整列数，卡片以约 280 像素为最小宽度、120 像素为基准高度，间距统一为 12 像素。主题切换和窗口缩放不会重新创建录制卡片或触发直播检查。

## 本地验证

项目使用 Python 3.12+、Flet、StreamGet 和 FFmpeg；依赖由 `requirements.txt` / `pyproject.toml` 管理。源码在 `app/`，入口为 `main.py`，测试在 `tests/`，构建输出在 `build/` 与 `dist/`。

```powershell
.venv/Scripts/python.exe main.py --web --host 127.0.0.1 --port 6006
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe scripts/build.py --platform windows
```

主题测试覆盖颜色校验、预设及随机色的浅深对比度、旧配置兼容、预览隔离、取消、保存失败、乱序消息、并发保存，以及旧会话保存其他设置时不回滚已提交的主题。界面测试使用 Web 模式；Windows 打包启动及进程退出行为由现有构建工作流检查。
