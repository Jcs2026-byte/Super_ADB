# Super_ADB Wiki

欢迎来到 **Super_ADB** 的 Wiki！这里收录了项目的完整文档：安装、使用、功能详解、常见问题与开发打包指南。

> Super_ADB 是一款跨平台的 ADB 集成调试工具，集设备连接、应用管理、文件传输、日志抓取、性能监控、网络抓包等功能于一体。

## 📚 文档导航

| 页面 | 说明 |
|------|------|
| [安装与快速开始](install) | 三平台环境要求、源码运行、安装包下载 |
| [功能详解](features) | 设备连接、文件管理、应用管理、日志、性能、抓包、投屏、工具集、快捷键、压测 |
| [常见问题](faq) | FAQ：连接失败、授权、打包、跨平台问题 |
| [开发与打包](development) | 项目结构、三平台打包、CI 说明 |
| [文件管理器](file-manager) | 文件管理功能详解 |
| [全局快捷键](hotkeys) | 截图框选标注、热键配置 |
| [JSON 对比工具](json-diff) | JSON 拖放对比、HTML 导出 |

## ✨ 核心亮点

- **自研 ADB（三平台默认）**：纯 Python 实现，TCP 直连 + USB（pyusb）双通道，不依赖官方 adb server、不占用 5037 端口，传输速度最高可达官方 2.7 倍
- **无线调试**：局域网扫描、配对码连接（adb pair）、二维码连接（mDNS）三种方式
- **完整功能集**：文件管理、APK 解析安装、logcat 日志、性能监控、tcpdump 抓包、scrcpy 投屏、Monkey 压测
- **全局快捷键**：自定义截图/录屏热键，框选+标注工具条
- **三平台一致**：Windows / macOS / Linux 结构统一的源码树

## 🔗 相关链接

- GitHub：https://github.com/Jcs2026-byte/Super_ADB
- Gitee：https://gitee.com/Jcs2026/Super_ADB
- GitHub Releases：https://github.com/Jcs2026-byte/Super_ADB/releases
