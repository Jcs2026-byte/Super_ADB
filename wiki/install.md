# 安装与快速开始

## 环境要求

- **Python 3.12+**（代码使用了 3.12 的 f-string 反斜杠语法）
- PySide6 等依赖见根目录 `requirements.txt`
- 对应平台的 ADB 工具（默认使用项目自研 ADB，无需单独安装官方 adb）

## 源码运行

```bash
# 克隆仓库（以 GitHub 为例）
git clone https://github.com/Jcs2026-byte/Super_ADB.git
cd Super_ADB

# 安装依赖
pip install -r requirements.txt

# 运行（以 Windows 为例）
cd Super_ADB_Win
python 项目启动入口/Super_ADB_主入口.py
```

macOS / Linux 同理，进入 `Super_ADB_MAC` / `Super_ADB_Linux` 目录运行各自的 `项目启动入口/Super_ADB_主入口.py`。

## 下载安装包

三平台安装包由 CI（打标签后）自动构建发布：

- **GitHub Releases**（主选，CI 自动打包）：https://github.com/Jcs2026-byte/Super_ADB/releases
- **Gitee 发行版**（GitHub 跨网不一定能同步过来）：https://gitee.com/Jcs2026/super_adb/releases
- **夸克网盘**：https://pan.quark.cn/s/2b7b11ebe1e5?pwd=fAXN#/list/share

| 平台 | 产物 |
|------|------|
| Linux x86_64 | `Super_ADB-linux-x86_64.tar.gz` |
| Windows x64 | `Super_ADB-windows-x64.zip` |
| macOS arm64 | `Super_ADB-macos-arm64.zip` |

## ADB 连接模式

工具默认使用**自研 ADB**（纯 Python socket 直连设备，不依赖官方 adb server）。

需要切换时，通过环境配置选择：

| 模式 | 说明 |
|------|------|
| 自研 ADB（默认） | 纯 Python 协议栈，TCP 直连 + USB，无需安装 adb |
| Socket 直连 | 优先自研协议客户端（socket），失败回退 subprocess |
| 系统 ADB | 调用官方 adb 二进制（优先 PATH，其次内置 platform-tools） |

> 连接模式保存在各平台 `配置/Super_ADB配置.json` 中；未配置或全新安装时默认自研 ADB。
