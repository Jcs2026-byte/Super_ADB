# Super_ADB

> 一款跨平台的 ADB 集成调试工具，集设备连接、应用管理、文件传输、日志抓取、性能监控、网络抓包等功能于一体。

![Super_ADB](Super_ADB_Win/资源/Super_ADB.png)
**最新版本：`v2026.09.10`**（GitHub / Gitee 均已同步）

## ✨ 功能特性

### 🔌 设备连接
- **自研 ADB（三平台默认）**：纯 Python 实现的 ADB 协议栈（`工具/android调试工具/自研adb/`），
  TCP 直连 + USB（pyusb）双通道，不依赖官方 adb server、不占用 5037 端口，
  传输速度最高可达官方 2.7 倍
- **系统 ADB / Socket 直连**：可一键切换回官方 adb（优先 PATH，其次内置 platform-tools）
- **无线调试**：局域网扫描、配对码连接（adb pair）、二维码连接（mDNS）三种方式

### 📁 文件管理
- 设备文件树浏览器，支持上传/下载/删除/重命名
- 拖拽上传、递归搜索、文本预览
- 权限修改（右键授权 777），只读分区自动检测并附解锁引导

### 📦 应用管理
- APK 拖拽安装、批量安装、实时进度显示
- APK 元信息解析（包名/版本/权限/四大组件）
- 解包查看资源，安装失败自动诊断原因

### 📋 日志抓取
- 多标签 logcat 查看器，实时流式输出
- 关键字过滤（支持正则）、日志级别筛选、星标标记
- 多设备同时监控，日志导出保存

### 📊 性能监控
- 设备级：CPU 多核分核/内存/温度/FPS/网络速率
- 应用级：12 项图表指标、内存泄漏自动检测、ANR/OOM 检测、hprof 自动抓取
- HTML 报告导出，数据实时刷新

### 🌐 网络抓包
- tcpdump 自动检测架构并推送二进制（arm64/arm）
- BPF 过滤器、实时包数统计、pcap 自动拉取
- PCAP 解析器：HTTP/HTTPS/TCP/UDP 协议分析、流重组

### 📺 scrcpy 投屏
- 低延迟投屏，键鼠反向控制
- 分辨率/码率/帧率/编码器/渲染驱动自定义
- 文件拖拽传输、屏幕录制

### 🛠️ 便捷工具集
- ADB 终端（命令历史/Tab 补全/多设备切换）
- JSON 工具（格式化/差异对比/YAML 互转/Schema 校验）
- URL 编解码（UTF-8 百分号编码 / 解码）
- 哈希校验（8 种算法，支持 Windows 右键菜单）
- 时间戳转换、修改系统时间、设备信息、证书安装、环境配置

### 🐒 Monkey 压测
- 命令模板自定义、暂停/继续/停止控制
- 实时事件饼图统计、崩溃报告自动拉取、事件回放

## 🖥️ 支持平台

| 平台 | 目录 | 状态 |
|------|------|------|
| Windows | `Super_ADB_Win/` | ✅ 完整支持 |
| macOS | `Super_ADB_MAC/` | ✅ 完整支持 |
| Linux | `Super_ADB_Linux/` | ✅ 完整支持 |

## 🚀 快速开始

### 环境要求
- Python 3.12+（代码使用了 3.12 的 f-string 反斜杠语法）
- PySide6 等依赖见 [requirements.txt](requirements.txt)

### 源码运行

```bash
# 克隆仓库
git clone https://github.com/Jcs2026-byte/Super_ADB.git
cd Super_ADB

# 安装依赖
pip install -r requirements.txt

# 运行（以 Windows 为例）
cd Super_ADB_Win
python 项目启动入口/Super_ADB_主入口.py
```

### 下载安装包

三平台安装包由 CI（打标签后）自动构建发布，提供两个下载渠道：

- **GitHub Releases**（主选，CI 自动打包）：https://github.com/Jcs2026-byte/Super_ADB/releases
- **Gitee 发行版**（GitHub 跨网不一定能同步过来）：https://gitee.com/Jcs2026/super_adb/releases
- 夸克网盘：https://pan.quark.cn/s/2b7b11ebe1e5?pwd=fAXN#/list/share

| 平台 | 产物 |
|------|------|
| Linux x86_64 | `Super_ADB-linux-x86_64.tar.gz` |
| Windows x64 | `Super_ADB-windows-x64.zip` |
| macOS arm64 | `Super_ADB-macos-arm64.zip` |

## 📁 项目结构

```
Super_ADB/
├── Super_ADB_Win/          # Windows 平台源码
├── Super_ADB_MAC/          # macOS 平台源码
├── Super_ADB_Linux/        # Linux 平台源码
├── ui/                     # 通用 UI 资源（.ui 设计文件 / 图标 / 编译脚本）
└── .github/                # CI 工作流与打包脚本

三平台目录结构一致，以 Super_ADB_Win 为例：
├── 工具/
│   ├── android调试工具/     # ADB工具、自研adb/（协议栈）、收藏下拉框、性能监控、APK/AXML/DEX 解析
│   ├── 便捷工具/           # JSON读写、WiFi工具、WiFi密码破解、PCAP解析
│   └── 配置/               # Super_ADB配置.json（ADB 模式等运行时配置）
├── 对话框/                 # 各功能对话框（ADB终端、URL编解码、TCPDump、时间戳、设备信息…）
├── 页面/                   # 主界面页面组件
├── 项目UI/                 # 主界面生成代码
├── 项目启动入口/            # 程序入口（Super_ADB_主入口.py）
├── 外部扩展/
│   ├── adb/                # 官方 platform-tools（系统 ADB 模式备用）
│   ├── scrcpy/             # 投屏二进制（各平台发行包，含自带 adb）
│   └── tcpdump/            # 抓包二进制
├── 打包/                   # PyInstaller spec / 构建脚本（build_linux.sh、requirements_*.txt）
├── 脚本/                   # 辅助脚本
├── 诊断/                   # 诊断工具（仅 Windows）
├── 资源/                   # 图标、公众号图等
└── 配置/                   # 顶层运行时配置（仅 Windows）
```

## 📖 文档

- [更新日志](CHANGELOG.md) — 各版本变更记录
- [打包说明](Super_ADB_Linux/打包/README.md) — 三平台打包方法（PyInstaller / build_linux.sh）
- [贡献指南](CONTRIBUTING.md)

## 🔗 开源地址

- **GitHub**：https://github.com/Jcs2026-byte/Super_ADB.git
- **Gitee**：https://gitee.com/Jcs2026/Super_ADB.git

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！请先阅读 [贡献指南](CONTRIBUTING.md)。

## 📜 许可证

本项目基于 [MIT License](LICENSE) 开源。

## 📢 联系方式

扫码关注公众号 **Super_ADB**，获取最新版本更新、使用教程和技术分享。

![公众号](Super_ADB_Win/资源/公众号.jpg)
