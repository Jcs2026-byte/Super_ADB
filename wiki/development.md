# 开发与打包

## 项目结构

```
Super_ADB/
├── Super_ADB_Win/          # Windows 平台源码
├── Super_ADB_MAC/          # macOS 平台源码
├── Super_ADB_Linux/        # Linux 平台源码
├── ui/                     # 通用 UI 资源（.ui 设计文件 / 图标 / 编译脚本）
├── wiki/                   # 本 Wiki 页面源文件
└── .github/                # CI 工作流与打包脚本
```

三个平台目录结构一致，以 `Super_ADB_Win` 为例：

```
├── 工具/
│   ├── android调试工具/     # ADB工具、自研adb/（协议栈）、收藏下拉框、性能监控、APK/AXML/DEX 解析
│   ├── 便捷工具/           # JSON读写、WiFi工具、WiFi密码破解、PCAP解析
│   └── 配置/               # Super_ADB配置.json（ADB 模式等运行时配置）
├── 对话框/                 # 各功能对话框（ADB终端、URL编解码、TCPDump、时间戳、设备信息…）
├── 页面/                   # 主界面页面组件
├── 项目UI/                 # 主界面生成代码（Ui_MainWindow、png_rc 资源）
├── 项目启动入口/            # 程序入口（Super_ADB_主入口.py）
├── 外部扩展/
│   ├── adb/                # 官方 platform-tools（系统 ADB 模式备用）
│   ├── scrcpy/             # 投屏二进制（各平台发行包，含自带 adb）
│   └── tcpdump/            # 抓包二进制
├── 打包/                   # PyInstaller spec / 构建脚本
├── 脚本/                   # 辅助脚本
├── 诊断/                   # 诊断工具（仅 Windows）
├── 资源/                   # 图标、公众号图等
└── 配置/                   # 顶层运行时配置（仅 Windows）
```

## 代码规范

- **命名规范**：类名 `C` + 中文类名（如 `CURL编解码对话框`），方法名 `F` + 中文方法名（如 `F编码`），私有成员 `_C`/`_F` 前缀
- **目录分类**：代码按文件目录类别存放，模块通过 `工具.android调试工具.xxx` 等包路径引用
- **UI 生成**：`ui/` 下的 `.ui` / `.qrc` 由 `ui/compile_ui.py` 编译到 `项目UI/` 下的 `.py`

## 三平台打包

依赖清单与脚本均在各平台 `打包/` 目录：

| 平台 | 依赖清单 | 打包命令 |
|------|----------|----------|
| Windows | 根目录 `requirements.txt` | `pyinstaller --noconfirm --clean --distpath 打包/dist --workpath 打包/build 打包/Super_ADB.spec` |
| Linux | `打包/requirements_linux.txt`（含 cryptography、pyusb） | `bash 打包/build_linux.sh --clean` |
| macOS | 根目录 `requirements.txt` | `bash 打包/build_mac_zip.sh` |

> 注意：spec 文件使用 PyInstaller 的 `SPEC` 变量推导相对路径（CI 兼容），**不要**改回硬编码本机绝对路径，否则 GitHub Actions 上会构建失败。

详细说明见 `Super_ADB_Linux/打包/README.md`。

## CI

`.github/workflows/` 下有 3 个工作流：

| 文件 | 触发 | 内容 |
|------|------|------|
| `ci.yml` | push / PR | Ruff lint、三平台 byte-compile、文件名卫生检查、三平台构建 |
| `build.yml` | 被 CI/Release 复用 | 三平台 PyInstaller 打包 + 冒烟测试 |
| `release.yml` | 打 tag | 打包并发布 GitHub Release |

> `ci.yml` 的"文件名卫生检查"要求仓库骨架路径（三平台目录与 docs/ 之外）使用 ASCII 命名，新增根目录文件时注意避开中文路径。

## 提交与发版

1. 修改代码 → 本地验证（语法编译 / 模块导入）
2. 提交并推送：`git push gitee master`、`git push github master`
3. 打 tag 发版：`git tag -a vYYYY.MM.DD -m "..."` → `git push gitee refs/tags/xxx`、`git push github refs/tags/xxx`
4. 等待 GitHub Release 自动构建发布
