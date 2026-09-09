# -*- coding: utf-8 -*-
"""
工具 / Ios调试模块
==================
pymobiledevice3（GPL-3.0，纯 Python CLI）桥接层。
只负责「跑命令拿 JSON / 文本」，不做 UI、不做业务语义换算。

    ⚠ 许可说明：pymobiledevice3 为 GPL-3.0。本模块以「独立进程 + 命令行」方式调用它
    （arm's length，不 import、不链接其代码），因此不使本工程成为其衍生作品。
    请勿改为 in-process import pymobiledevice3；也不要把它随本工程一起分发，
    由使用者自行 pip 安装。

命令清单（pymobiledevice3 11.x 实际子命令，--udid 为子命令级选项）：
    usbmux list                  设备列表（JSON 数组，short_info 形态）
    version                      版本号（纯文本）
    lockdown info                设备信息（JSON 对象）
    apps list                    应用列表（JSON 对象 {bundleId: {…}}）
    apps install <包>            安装
    apps uninstall <bundleId>    卸载
    developer dvt launch <bid>   启动应用
    developer dvt pkill <bid> --bundle   停止应用（kill 只接受 PID！）
    developer screenshot <路径>  截图（失败回退 developer dvt screenshot）
    crash ls                     崩溃列表（逐行纯文本，非 JSON）
    crash pull <目录> [--match 正则]      拉取崩溃报告
    syslog live                  系统日志（流式）
    developer dvt sysmon system  系统监控（一次性「键: 值」纯文本）
    diagnostics battery single   电池（JSON）
    processes ps                 进程（JSON 对象 {pid: {ProcessName}}）
    amfi developer-mode-status / enable-developer-mode   开发者模式
    mounter auto-mount / list    开发者镜像挂载 / 已挂载列表
    remote tunneld --daemonize   隧道常驻服务（可选；iOS 17+ 默认按需自动建隧道）

命名约定（本模块全部为新建代码）：
    类名    前缀 c   → cIos设备操作
    方法名  前缀 f   → f获取设备列表
    变量名  前缀 b   → b设备列表

模拟模式（无真机联调）：
    设置环境变量 SUPER_ADB_IOS_MOCK=1 后，桥接自动改跑本目录的 pymd3模拟器.py
    （STUB，输出形态逐条对齐真实 pymobiledevice3），取消该变量即回到真实后端。
"""
