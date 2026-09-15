# -*- coding: utf-8 -*-
"""
ADB 命令集合弹窗
================
点击主界面「便捷工具 → ADB命令集合」按钮弹出的独立窗口：
- 内置常用 ADB 命令库（按类别组织），每条含 命令 / 详细解释 / 实例
- 顶部类别下拉框：按 7 大分类聚焦浏览，不用一屏看全部
- 搜索框：按 类别 / 命令 / 解释 / 实例 实时过滤（不区分大小写），可与类别筛选叠加
- 点击条目下方显示详情，「复制命令」一键复制到剪贴板；双击条目直接复制
- 弹窗样式与其他弹窗一致（弹窗样式.py：主题色高亮边框卡片 + 外发光）

命令库集中在模块级 ``ADB命令集``（类别, 命令, 说明, 实例），方便后续扩充。
"""

import sys

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QTextEdit, QGroupBox,
)

from 项目UI import png_rc  # noqa: F401
from 项目UI.界面样式 import get_stylesheet, get_current_theme_id, THEMES
from 项目UI.弹窗样式 import add_green_glow, highlight_card_style, _create_popup_card


# ----------------------------------------------------------------------
# ADB 命令库：(类别, 命令, 说明, 实例)
# ----------------------------------------------------------------------
ADB命令集 = [
    # ── 设备连接与状态 ──
    ("设备连接与状态", "adb devices",
     "列出当前连接的所有设备（USB + 无线），含序列号和状态。状态 offline 表示未授权，unauthorized 表示需在设备上允许调试。",
     "adb devices"),
    ("设备连接与状态", "adb connect <设备IP:端口>",
     "通过无线方式连接指定设备。需先开启设备的「无线调试」或先用 USB 执行 adb tcpip 5555。",
     "adb connect 192.168.1.100:5555"),
    ("设备连接与状态", "adb disconnect <设备IP:端口>",
     "断开指定设备的无线连接；不接参数则断开全部无线设备。",
     "adb disconnect 192.168.1.100:5555"),
    ("设备连接与状态", "adb kill-server",
     "停止 adb 服务。设备离线、端口占用、adb 异常时先执行此命令再 adb start-server 重启服务。",
     "adb kill-server"),
    ("设备连接与状态", "adb start-server",
     "启动 adb 服务（默认端口 5037），一般会自动启动，异常时手动执行。",
     "adb start-server"),
    ("设备连接与状态", "adb get-state",
     "查看指定设备的状态：device（正常）/ offline（离线）/ unauthorized（未授权）。",
     "adb get-state"),
    ("设备连接与状态", "adb wait-for-device",
     "阻塞等待设备上线后再执行后续命令，常用于开机脚本（等待 boot 完成）。",
     "adb wait-for-device"),
    ("设备连接与状态", "adb reboot",
     "重启设备。加 -recovery 进恢复模式，-bootloader 进引导加载器。",
     "adb reboot"),
    ("设备连接与状态", "adb pair <设备IP:端口> <配对码>",
     "无线调试配对（Android 11+）：先在设备「开发者选项 → 无线调试 → 使用配对码配对设备」获取 IP:端口 和 6 位配对码，配对成功后即可 adb connect。",
     "adb pair 192.168.1.100:37000 123456"),
    ("设备连接与状态", "adb reconnect",
     "强制重连设备。设备状态显示 offline 时先执行它（必要时配合 adb kill-server）。",
     "adb reconnect"),
    ("设备连接与状态", "adb forward <本地端口> <设备端口>",
     "端口转发：把设备上的端口映射到电脑，访问电脑地址即访问设备服务（如抓包代理、设备内部 Web 服务）。",
     "adb forward tcp:8080 tcp:8080"),
    ("设备连接与状态", "adb reverse <设备端口> <本地端口>",
     "反向端口转发：让设备通过 127.0.0.1 访问电脑上的服务（调试本地接口、配合抓包工具常用）。",
     "adb reverse tcp:8080 tcp:8080"),
    ("设备连接与状态", "adb usb",
     "重启 adbd 并切回 USB 监听（从无线调试切回 USB 连接时使用）。",
     "adb usb"),
    ("设备连接与状态", "adb devices -l",
     "列出设备详细信息（型号、传输方式 USB/WLAN 等），比 adb devices 信息更全。",
     "adb devices -l"),
    ("设备连接与状态", "adb help",
     "查看 ADB 全部客户端命令的帮助说明。",
     "adb help"),
    ("设备连接与状态", "adb version",
     "查看当前 adb 工具版本号，确认环境版本。",
     "adb version"),
    ("设备连接与状态", "adb -s <序列号> <命令>",
     "多设备连接时指定设备执行命令（序列号用 adb devices 查看），避免操作错设备。",
     "adb -s 192.168.1.100:5555 shell pm list packages"),
    ("设备连接与状态", "adb get-serialno",
     "查看当前设备序列号（与 getprop ro.serialno 相同）。",
     "adb get-serialno"),
    ("设备连接与状态", "adb get-devpath",
     "查看设备连接路径（USB 端口位置），多设备接线排障时使用。",
     "adb get-devpath"),
    ("设备连接与状态", "adb mdns services",
     "扫描局域网内通过 mDNS 广播的无线调试设备（Android 11+）。",
     "adb mdns services"),
    ("设备连接与状态", "adb reconnect offline",
     "强制重连处于离线状态的设备（配合 kill-server 处理离线问题）。",
     "adb reconnect offline"),
    # ── 应用管理 ──
    ("应用管理", "adb install <apk路径>",
     "安装 APK 到设备。常用参数：-r 覆盖安装（保留数据）、-d 允许降级安装、-t 允许安装测试包。",
     "adb install -r app.apk"),
    ("应用管理", "adb uninstall <包名>",
     "卸载应用。加 -k 卸载但保留数据目录。",
     "adb uninstall com.example.app"),
    ("应用管理", "adb shell pm list packages",
     "列出所有应用包名。参数：-3 仅第三方、-s 仅系统、-d 仅已禁用、-e 仅已启用、-f 含路径。",
     "adb shell pm list packages -3"),
    ("应用管理", "adb shell pm disable <包名>",
     "冻结（禁用）应用：图标消失、无法启动、后台进程被停，数据保留。常用于禁掉不可卸载的预装应用。",
     "adb shell pm disable com.example.app"),
    ("应用管理", "adb shell pm enable <包名>",
     "解冻（启用）之前被禁用的应用，是 pm disable 的逆操作。",
     "adb shell pm enable com.example.app"),
    ("应用管理", "adb shell pm clear <包名>",
     "清除应用全部数据（缓存、数据库、设置），相当于恢复出厂，应用本体保留。",
     "adb shell pm clear com.example.app"),
    ("应用管理", "adb shell am start -n <包名/Activity>",
     "启动指定应用的指定界面。Activity 可用 resolve-activity 查询或直接写主界面类名。",
     "adb shell am start -n com.example.app/.MainActivity"),
    ("应用管理", "adb shell am force-stop <包名>",
     "强制停止应用进程（相当于「结束运行」），不影响应用数据。",
     "adb shell am force-stop com.example.app"),
    ("应用管理", "adb shell am start -W -n <包名/Activity>",
     "启动应用并输出启动耗时（TotalTime / WaitTime），用于冷启动性能测量。",
     "adb shell am start -W -n com.example.app/.MainActivity"),
    ("应用管理", "adb shell pm path <包名>",
     "查看应用的安装路径（APK 在设备上的位置）。",
     "adb shell pm path com.example.app"),
    ("应用管理", "adb shell pm dump <包名>",
     "输出应用详细信息：版本、权限、四大组件、安装来源等，信息量大可用 | grep 过滤。",
     "adb shell pm dump com.example.app | grep version"),
    ("应用管理", "adb shell cmd package resolve-activity --brief <包名>",
     "查询应用的入口 Activity（launcher 启动的界面），返回 包名/Activity 格式。",
     "adb shell cmd package resolve-activity --brief com.example.app"),
    ("应用管理", "adb shell monkey -p <包名> <次数>",
     "对指定应用随机执行 N 次点击/滑动等事件做压力测试，-v 可加详细程度。",
     "adb shell monkey -p com.example.app 500"),
    ("应用管理", "adb shell dumpsys package <包名>",
     "查看包在系统内的状态信息（disabled/enabled、data 目录等），判断是否被冻结。",
     "adb shell dumpsys package com.example.app"),
    ("应用管理", "adb install-multiple <多个apk>",
     "批量安装/安装拆分 APK（App Bundle 解包出的 base.apk + split 分包必须一起装）。",
     "adb install-multiple base.apk split_config.xhdpi.apk"),
    ("应用管理", "adb shell pm grant <包名> <权限>",
     "直接授予运行时权限（不再弹权限框），需先安装应用。",
     "adb shell pm grant com.example.app android.permission.CAMERA"),
    ("应用管理", "adb shell pm revoke <包名> <权限>",
     "撤销已授予的运行时权限。",
     "adb shell pm revoke com.example.app android.permission.CAMERA"),
    ("应用管理", "adb shell pm install-existing <包名>",
     "恢复已卸载的系统应用（出厂自带应用被卸掉后重新装回，数据丢失）。",
     "adb shell pm install-existing com.example.systemapp"),
    ("应用管理", "adb shell am broadcast -a <Action> [-p 包名]",
     "发送广播。可模拟开机完成、网络变化等系统事件，或触发应用的广播接收器。",
     "adb shell am broadcast -a android.intent.action.BOOT_COMPLETED -p com.example.app"),
    ("应用管理", "adb shell am start -a <Action> -d <URI>",
     "隐式意图启动：用系统默认应用处理链接/操作（打开网页、拨号、地图等）。",
     "adb shell am start -a android.intent.action.VIEW -d https://www.baidu.com"),
    ("应用管理", "adb shell am start -n <包名/Activity> --es <键> <值>",
     "带参数启动应用：--es 字符串 / --ei 整数 / --ez 布尔，用于深链或测试参数。",
     "adb shell am start -n com.example.app/.MainActivity --es extra_key hello"),
    ("应用管理", "adb shell appops set <包名> <权限操作> <模式>",
     "应用权限操作（无需 root 的权限管理）：allow 允许 / ignore 静默拒绝 / deny 拒绝并返回失败。",
     "adb shell appops set com.example.app CAMERA ignore"),
    ("应用管理", "adb shell am kill-all",
     "杀掉当前所有后台进程（前台应用不受影响），用于清后台/测试冷启动。",
     "adb shell am kill-all"),
    ("应用管理", "adb shell pm list users",
     "列出设备全部用户（0 为主用户，多开/访客/工作资料均可见）。",
     "adb shell pm list users"),
    ("应用管理", "adb install --user 0 <apk>",
     "指定用户安装（多用户设备只装给主用户 0，避免装到其他用户）。",
     "adb install --user 0 app.apk"),
    ("应用管理", "adb shell pm list permissions",
     "列出系统全部权限定义，加 -g 只看危险权限，查询权限名用。",
     "adb shell pm list permissions -g"),
    ("应用管理", "adb shell pm list features",
     "列出设备支持的硬件与系统特性（NFC/指纹/多窗口等）。",
     "adb shell pm list features"),
    ("应用管理", "adb shell pm create-user <用户名>",
     "创建新用户（多用户模式），返回用户 ID，访客/多开场景使用。",
     "adb shell pm create-user 访客"),
    ("应用管理", "adb shell pm remove-user <用户ID>",
     "删除指定用户及其全部数据，谨慎使用。",
     "adb shell pm remove-user 10"),
    ("应用管理", "adb shell am startservice -n <包名/服务>",
     "启动应用的后台服务（Service）。",
     "adb shell am startservice -n com.example.app/.MyService"),
    ("应用管理", "adb shell am dumpheap <包名> <设备路径>",
     "导出应用堆内存快照（hprof 文件），配合 MAT/Android Studio 分析内存泄漏。",
     "adb shell am dumpheap com.example.app /sdcard/app.hprof"),
    ("应用管理", "adb shell am profile start <文件> <包名>",
     "开始对应用做 CPU 采样（方法耗时分析）。",
     "adb shell am profile start /sdcard/app.trace com.example.app"),
    ("应用管理", "adb shell am profile stop <文件>",
     "停止 CPU 采样并保存结果文件。",
     "adb shell am profile stop /sdcard/app.trace"),
    ("应用管理", "adb shell pm trim-caches <大小>",
     "清理各应用缓存，使缓存总量降到指定大小以下（省存储空间）。",
     "adb shell pm trim-caches 200M"),
    ("应用管理", "adb shell cmd package uninstall --user 0 <包名>",
     "指定用户卸载应用（多用户设备只卸主用户的）。",
     "adb shell cmd package uninstall --user 0 com.example.app"),
    # ── 文件传输 ──
    ("文件传输", "adb push <本地路径> <设备路径>",
     "把电脑上的文件/目录推送到设备。路径含空格或中文时建议加引号。",
     "adb push C:\\test.apk /sdcard/"),
    ("文件传输", "adb pull <设备路径> <本地路径>",
     "把设备上的文件/目录拉取到电脑。不写本地路径则保存到当前目录。",
     "adb pull /sdcard/test.txt C:\\"),
    ("文件传输", "adb shell ls",
     "查看设备目录内容。-l 显示详情、-a 含隐藏文件、-h 人性化大小。",
     "adb shell ls -l /sdcard"),
    ("文件传输", "adb shell rm",
     "删除设备上的文件/目录。-rf 递归强制删除（目录必加 -r）。",
     "adb shell rm -rf /sdcard/test"),
    ("文件传输", "adb shell mkdir",
     "创建设备目录。-p 可递归创建多级目录。",
     "adb shell mkdir -p /sdcard/test/sub"),
    ("文件传输", "adb shell chmod",
     "修改设备文件权限（rwx 八进制 644/755/777 等），部分目录需 root。",
     "adb shell chmod 777 /data/local/tmp/test.sh"),
    ("文件传输", "adb shell cp",
     "复制设备上的文件/目录（-r 复制目录）。",
     "adb shell cp /sdcard/a.txt /sdcard/b.txt"),
    ("文件传输", "adb shell mv",
     "移动/重命名设备上的文件或目录。",
     "adb shell mv /sdcard/a.txt /sdcard/test/"),
    ("文件传输", "adb sync <本地目录> <设备目录>",
     "增量同步本地目录到设备（只传变化的文件，比 push 全量高效）。",
     "adb sync C:\\sync_dir /sdcard/"),
    ("文件传输", "adb shell cat <文件>",
     "查看设备文件内容（也可读取 proc 等系统虚拟文件）。",
     "adb shell cat /proc/cpuinfo"),
    ("文件传输", "adb shell touch <文件>",
     "创建空文件或更新时间戳。",
     "adb shell touch /sdcard/new.txt"),
    ("文件传输", "adb shell find <目录> -name <模式>",
     "按名称查找文件（-iname 忽略大小写，-type d 只找目录）。",
     "adb shell find /sdcard -name '*.apk'"),
    # ── 日志与调试 ──
    ("日志与调试", "adb logcat",
     "实时滚动查看设备日志。-s 按标签过滤（如 ActivityManager:I）、-v time 带时间戳。Ctrl+C 退出。",
     "adb logcat -s ActivityManager:I"),
    ("日志与调试", "adb logcat -c",
     "清空 logcat 日志缓冲区，之后日志从零开始，方便定位问题起点。",
     "adb logcat -c"),
    ("日志与调试", "adb logcat -d",
     "导出当前缓冲区全部日志后立即退出（不阻塞），常配合重定向保存到文件。",
     "adb logcat -d > log.txt"),
    ("日志与调试", "adb shell dumpsys",
     "输出所有系统服务状态摘要；接服务名（battery/window/activity/meminfo 等）查看单项详情。",
     "adb shell dumpsys battery"),
    ("日志与调试", "adb shell dumpsys meminfo <包名>",
     "查看指定应用的内存占用明细（Java 堆 / Native / 图形等）。",
     "adb shell dumpsys meminfo com.example.app"),
    ("日志与调试", "adb shell dumpsys window | grep mCurrentFocus",
     "查看当前处于前台的窗口/界面，返回 包名/Activity，常用于获取当前应用包名。",
     "adb shell dumpsys window | grep mCurrentFocus"),
    ("日志与调试", "adb shell dumpsys activity top",
     "查看栈顶 Activity 的详细信息（Intent、进程、状态等）。",
     "adb shell dumpsys activity top"),
    ("日志与调试", "adb bugreport",
     "导出设备完整诊断报告（系统信息 + 日志 + 崩溃栈等），耗时较长，可用于提交问题。",
     "adb bugreport"),
    ("日志与调试", "adb shell dumpsys gfxinfo <包名>",
     "帧渲染统计：输出平均帧耗时、掉帧（Janky）次数等，用于评估应用流畅度。",
     "adb shell dumpsys gfxinfo com.example.app"),
    ("日志与调试", "adb shell dumpsys batterystats",
     "耗电统计：各应用/组件的电量使用明细，排查异常耗电。",
     "adb shell dumpsys batterystats"),
    ("日志与调试", "adb shell getevent",
     "监听触摸/按键/传感器原始事件，-lt 带时间与类型标签，调试自动点击坐标时常用。",
     "adb shell getevent -lt"),
    ("日志与调试", "adb shell dumpsys activity activities",
     "查看 Activity 任务栈详情（栈内所有 Activity、是否可见等）。",
     "adb shell dumpsys activity activities"),
    ("日志与调试", "adb shell dumpsys alarm",
     "查看闹钟（AlarmManager）统计：各应用设置的闹钟与唤醒次数，排查异常唤醒耗电。",
     "adb shell dumpsys alarm"),
    ("日志与调试", "adb shell dumpsys power",
     "电源与唤醒锁（WakeLock）统计，排查息屏后异常耗电。",
     "adb shell dumpsys power"),
    ("日志与调试", "adb shell dumpsys connectivity",
     "网络连接状态（当前网络类型、连接详情）。",
     "adb shell dumpsys connectivity"),
    ("日志与调试", "adb shell dumpsys input",
     "输入系统信息（触摸屏/按键设备与配置）。",
     "adb shell dumpsys input"),
    ("日志与调试", "adb shell dumpsys diskstats",
     "磁盘读写统计与存储状态。",
     "adb shell dumpsys diskstats"),
    ("日志与调试", "adb shell dumpsys window displays",
     "显示器参数（分辨率/密度/刷新率等）。",
     "adb shell dumpsys window displays"),
    ("日志与调试", "adb jdwp",
     "列出当前可调试的进程 PID（JVM 调试通道）。",
     "adb jdwp"),
    ("日志与调试", "adb shell cmd usagestats",
     "应用使用统计（各应用使用时长、次数、前台时间）。",
     "adb shell cmd usagestats --summary 7d"),
    # ── 系统设置与信息 ──
    ("系统设置与信息", "adb shell getprop",
     "读取系统属性。接属性名读取单项，如 ro.build.version.release 系统版本、ro.product.model 机型。",
     "adb shell getprop ro.build.version.release"),
    ("系统设置与信息", "adb shell settings get/set",
     "读取/修改系统设置（global/system/secure 三类）。如设置代理：settings put global http_proxy IP:端口。",
     "adb shell settings put global http_proxy 192.168.1.1:8888"),
    ("系统设置与信息", "adb shell wm size",
     "查看屏幕分辨率；接 宽x高 可修改（部分设备重启失效），接 reset 恢复默认。",
     "adb shell wm size 1080x1920"),
    ("系统设置与信息", "adb shell wm density",
     "查看屏幕密度（dpi）；接数值可修改，接 reset 恢复默认。",
     "adb shell wm density 440"),
    ("系统设置与信息", "adb shell input keyevent <键码>",
     "模拟按键。常用：3=Home、4=返回、26=电源、82=菜单、187=最近任务。",
     "adb shell input keyevent 3"),
    ("系统设置与信息", "adb shell input text <文本>",
     "模拟输入文本到当前焦点输入框（仅支持 ASCII，中文可用 adb keyboard 类工具）。",
     "adb shell input text hello"),
    ("系统设置与信息", "adb shell input swipe <x1> <y1> <x2> <y2> [时长ms]",
     "模拟屏幕滑动/长按，常用于自动滑动、手势测试。",
     "adb shell input swipe 500 1500 500 300 500"),
    ("系统设置与信息", "adb shell screencap <路径>",
     "设备截屏保存到指定路径，再 adb pull 拉回电脑。",
     "adb shell screencap /sdcard/screen.png"),
    ("系统设置与信息", "adb shell screenrecord <路径>",
     "设备录屏（MP4，默认 1080p），Ctrl+C 停止录制。",
     "adb shell screenrecord /sdcard/video.mp4"),
    ("系统设置与信息", "adb shell date",
     "查看设备系统时间（也可用于对比 PC 与设备时间差）。",
     "adb shell date"),
    ("系统设置与信息", "adb root",
     "以 root 权限重启 adbd 守护进程（需设备已 root），之后 shell 即拥有 root 权限。",
     "adb root"),
    ("系统设置与信息", "adb shell input tap <x> <y>",
     "模拟点击屏幕指定坐标（配合 wm size 或 dumpsys window 获取坐标）。",
     "adb shell input tap 500 800"),
    ("系统设置与信息", "adb shell svc wifi enable / disable",
     "开启/关闭设备 WiFi。",
     "adb shell svc wifi disable"),
    ("系统设置与信息", "adb shell svc data enable / disable",
     "开启/关闭移动数据（蜂窝数据）。",
     "adb shell svc data disable"),
    ("系统设置与信息", "adb shell settings list",
     "列出全部系统设置项（global/system/secure 三类，可接类名只看一类）。",
     "adb shell settings list global"),
    ("系统设置与信息", "adb shell cmd uimode night yes / no",
     "切换深色模式（yes 开 / no 关），部分设备需重启生效。",
     "adb shell cmd uimode night yes"),
    ("系统设置与信息", "adb exec-out screencap -p > <本地文件>",
     "截屏直接输出到电脑（不经设备存储），建议在 CMD 下使用。",
     "adb exec-out screencap -p > screen.png"),
    ("系统设置与信息", "adb shell getprop ro.serialno",
     "查看设备序列号（SN），常用于设备识别与登记。",
     "adb shell getprop ro.serialno"),
    ("系统设置与信息", "adb shell settings put global window_animation_scale 0",
     "关闭系统动画（窗口/过渡/缩放动画），开发调试提速。配合 transition_animation_scale、animator_duration_scale 一并置 0 效果完整。",
     "adb shell settings put global window_animation_scale 0"),
    ("系统设置与信息", "adb shell getprop ro.build.version.sdk",
     "查看设备 Android API 等级（33=Android 13，34=Android 14），判断系统版本兼容性。",
     "adb shell getprop ro.build.version.sdk"),
    ("系统设置与信息", "adb shell getprop ro.product.model",
     "查看设备型号名称。",
     "adb shell getprop ro.product.model"),
    ("系统设置与信息", "adb shell input rollback",
     "撤销上一次 input 输入（input text 输错内容时回退），部分设备不支持。",
     "adb shell input rollback"),
    ("系统设置与信息", "adb shell wm overscan <左,上,右,下>",
     "调整屏幕显示边界（像素值），隐藏刘海/圆角黑边；全部 0 恢复默认。",
     "adb shell wm overscan 0,0,0,0"),
    ("系统设置与信息", "adb shell wm dismiss-keyguard",
     "解除锁屏（配合唤醒/解锁自动化）。",
     "adb shell wm dismiss-keyguard"),
    ("系统设置与信息", "adb shell setprop <属性> <值>",
     "设置系统属性（临时生效，部分属性需 root）。",
     "adb shell setprop debug.hwui.profile true"),
    ("系统设置与信息", "adb shell cmd battery set level <数值>",
     "模拟电池电量（0-100），调试低电量弹窗与省电逻辑。",
     "adb shell cmd battery set level 5"),
    ("系统设置与信息", "adb shell cmd battery set status charging",
     "模拟充电状态；battery reset 恢复真实电量。",
     "adb shell cmd battery set status charging"),
    ("系统设置与信息", "adb shell cmd locksettings set-pattern <图案>",
     "设置锁屏图案（4-9 位数字编码，0000 表示无图案）。",
     "adb shell cmd locksettings set-pattern 0000"),
    ("系统设置与信息", "adb shell cmd notification post <标签> <标题> <内容>",
     "发送一条测试通知到通知栏。",
     "adb shell cmd notification post test 标题 内容"),
    ("系统设置与信息", "adb shell cmd statusbar expand-notifications",
     "展开通知栏（收起用 collapse-notifications）。",
     "adb shell cmd statusbar expand-notifications"),
    ("系统设置与信息", "adb shell content query --uri <URI>",
     "直接查询 ContentProvider 数据（系统设置/联系人等）。",
     "adb shell content query --uri content://settings/secure"),
    # ── 网络相关 ──
    ("网络相关", "adb shell ip addr",
     "查看设备各网卡的 IP 地址（wlan0=WiFi、eth0=有线、rmnet0=蜂窝）。",
     "adb shell ip addr show wlan0"),
    ("网络相关", "adb shell ping <地址>",
     "测试设备到目标地址的连通性，-c 指定次数、-s 指定包大小。",
     "adb shell ping -c 4 8.8.8.8"),
    ("网络相关", "adb shell netstat",
     "查看设备网络连接状态（TCP/UDP 端口监听等），-t 只看 TCP。",
     "adb shell netstat -t"),
    ("网络相关", "adb tcpip 5555",
     "重启 adbd 并监听 5555 端口，开启无线调试（需先 USB 连接）。之后可 adb connect IP:5555。",
     "adb tcpip 5555"),
    ("网络相关", "adb shell settings get global http_proxy",
     "查看当前 HTTP 代理设置；输出 :0 表示未设置代理。",
     "adb shell settings get global http_proxy"),
    ("网络相关", "adb shell settings put global http_proxy :0",
     "清除设备 HTTP 代理（恢复直连）。",
     "adb shell settings put global http_proxy :0"),
    ("网络相关", "adb shell svc bluetooth enable / disable",
     "开启/关闭蓝牙。",
     "adb shell svc bluetooth disable"),
    ("网络相关", "adb shell svc power stayon true / false",
     "充电时屏幕常亮/关闭，测试常亮场景。",
     "adb shell svc power stayon true"),
    ("网络相关", "adb shell traceroute <地址>",
     "网络路由追踪，排查链路节点问题。",
     "adb shell traceroute 8.8.8.8"),
    ("网络相关", "adb shell cmd wifi connect-network <SSID> open",
     "命令行连接开放 WiFi（新版系统，密码方式用引号带密码）。",
     "adb shell cmd wifi connect-network TestWiFi open"),
    ("网络相关", "adb shell cmd connectivity airplane-mode enable / disable",
     "开启/关闭飞行模式（新版系统）。",
     "adb shell cmd connectivity airplane-mode enable"),
    # ── 性能与压测 ──
    ("性能与压测", "adb shell top",
     "实时查看设备 CPU 占用率 TOP 列表（类似电脑任务管理器），-n 1 只取一次。",
     "adb shell top -n 1"),
    ("性能与压测", "adb shell dumpsys cpuinfo",
     "查看各进程 CPU 占用快照。",
     "adb shell dumpsys cpuinfo"),
    ("性能与压测", "adb shell uptime",
     "查看设备开机时长与系统负载（load average）。",
     "adb shell uptime"),
    ("性能与压测", "adb shell ps -A",
     "列出设备所有进程（PID / 用户 / 内存 / 命令），定位进程与 PID。",
     "adb shell ps -A"),
    ("性能与压测", "adb shell free -m",
     "查看内存总量 / 已用 / 可用（-m 以 MB 显示）。",
     "adb shell free -m"),
    ("性能与压测", "adb shell df -h",
     "查看各分区磁盘占用（-h 人性化大小），排查存储空间不足。",
     "adb shell df -h"),
    ("性能与压测", "adb shell vmstat",
     "查看系统性能快照（进程/内存/IO/CPU 统计），可带间隔与次数持续刷新。",
     "adb shell vmstat 1 3"),
    ("性能与压测", "adb shell cmd jobscheduler run -f <包名>",
     "手动触发应用的 JobScheduler 后台任务（测试任务时机与执行）。",
     "adb shell cmd jobscheduler run -f com.example.app"),
    ("性能与压测", "adb shell cmd deviceidle force-idle",
     "强制设备进入 Doze 深度省电（测试待机耗电与后台冻结）。",
     "adb shell cmd deviceidle force-idle"),
    ("性能与压测", "adb shell cmd deviceidle unforce",
     "退出强制 Doze 模式。",
     "adb shell cmd deviceidle unforce"),
    # ── 高级与系统维护 ──
    ("高级与系统维护", "adb shell su -c '<命令>'",
     "以 root 权限执行单条 shell 命令（需设备已 root，Magisk/SuperSU 等）。",
     "adb shell su -c 'ls /data/data'"),
    ("高级与系统维护", "adb shell cmd package compile -m speed -f <包名>",
     "强制全量编译优化应用（dex2oat），提升首次启动速度，速度模式：verify / speed / speed-profile。",
     "adb shell cmd package compile -m speed -f com.example.app"),
    ("高级与系统维护", "adb shell am instrument -w <测试包>/<Runner>",
     "运行应用的自动化测试（AndroidJUnitRunner 等），输出测试结果。",
     "adb shell am instrument -w com.example.app.test/androidx.test.runner.AndroidJUnitRunner"),
    ("高级与系统维护", "adb sideload <OTA包>",
     "在 Recovery 模式下侧载 OTA 升级包（先 adb reboot recovery 再进 Apply update from ADB）。",
     "adb sideload ota.zip"),
    ("高级与系统维护", "adb backup -apk <包名>",
     "备份应用数据到电脑（Android 8+ 多数设备已移除该命令，旧设备可用）。",
     "adb backup -apk com.example.app"),
    ("高级与系统维护", "adb remount",
     "以可写方式重新挂载 /system 等分区（需 root 且已解锁），修改系统文件前使用。",
     "adb remount"),
    ("高级与系统维护", "adb disable-verity",
     "关闭 dm-verity 校验（修改 /system 前先执行，重启后生效）。",
     "adb disable-verity"),
    ("高级与系统维护", "adb enable-verity",
     "重新开启 dm-verity 校验。",
     "adb enable-verity"),
    ("高级与系统维护", "adb unroot",
     "退出 adbd 的 root 模式（需设备已 root）。",
     "adb unroot"),
    ("高级与系统维护", "adb restore <备份文件>",
     "从电脑恢复应用备份（与 adb backup 对应）。",
     "adb restore backup.ab"),
    ("高级与系统维护", "adb exec-out <命令>",
     "执行命令并把原始二进制输出直接重定向（截屏到电脑、导出文件常用）。",
     "adb exec-out screencap -p > screen.png"),
    ("高级与系统维护", "adb emu <命令>",
     "向模拟器发送控制命令：kill 关闭模拟器、avd name 查询名称等。",
     "adb emu kill"),
    ("高级与系统维护", "adb keygen <文件名>",
     "生成 ADB 认证密钥对（无线调试安全连接）。",
     "adb keygen adbkey"),
]


class ADB命令集合对话框(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ADB 命令集合")
        self.setWindowIcon(QIcon(":/Super_ADB.png"))
        self.setMinimumSize(680, 520)
        self._theme_id = get_current_theme_id(self)
        self.setStyleSheet(get_stylesheet(self._theme_id))
        # 与其他弹窗同款：主题色高亮边框卡片 + 外发光
        self.card, _ = _create_popup_card(self, self._theme_id)
        self._build_ui()

    def apply_theme(self, theme_id):
        """运行时切换主题：更新全局 QSS + 外发光。"""
        if theme_id not in THEMES or theme_id == self._theme_id:
            return
        self._theme_id = theme_id
        self.setStyleSheet(get_stylesheet(theme_id))
        self.card.setStyleSheet(highlight_card_style(theme_id))
        add_green_glow(self.card, accent=QColor(THEMES[theme_id]['accent']))
        self.update()

    def _build_ui(self):
        root = QVBoxLayout(self.card)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # ── 搜索 + 类别筛选行 ──
        search_row = QHBoxLayout()
        lbl = QLabel("搜索")
        lbl.setFixedWidth(44)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "输入关键字过滤（匹配 类别 / 命令 / 解释 / 实例）…")
        self.search_edit.textChanged.connect(self._过滤列表)
        self.count_label = QLabel()
        self.count_label.setFixedWidth(64)
        search_row.addWidget(lbl)
        search_row.addWidget(self.search_edit, 1)
        # 类别下拉：按类别聚焦浏览，避免一屏长列表阅读负担
        self.cat_combo = QComboBox()
        self.cat_combo.setFixedWidth(150)
        self.cat_combo.addItem("全部", None)
        for _cat in [c[0] for c in ADB命令集]:
            if self.cat_combo.findData(_cat) == -1:
                self.cat_combo.addItem(_cat, _cat)
        self.cat_combo.currentIndexChanged.connect(self._过滤列表)
        search_row.addWidget(QLabel("类别"))
        search_row.addWidget(self.cat_combo)
        search_row.addWidget(self.count_label)
        root.addLayout(search_row)

        # ── 命令列表 ──
        self.cmd_list = QListWidget()
        self.cmd_list.currentItemChanged.connect(self._显示详情)
        self.cmd_list.itemDoubleClicked.connect(lambda _item: self._复制当前命令())
        root.addWidget(self.cmd_list, 1)

        # ── 详情 + 复制 ──
        detail_group = QGroupBox("详情（双击条目可直接复制命令）")
        dv = QVBoxLayout(detail_group)
        dv.setSpacing(6)
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setMaximumHeight(170)
        dv.addWidget(self.detail_view)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.copy_btn = QPushButton("复制命令")
        self.copy_btn.setFixedWidth(110)
        self.copy_btn.clicked.connect(self._复制当前命令)
        btn_row.addWidget(self.copy_btn)
        dv.addLayout(btn_row)
        root.addWidget(detail_group)

        # ── 填充数据：每条显示「命令 + 一句话简述」，悬停看完整说明 ──
        for i, (_cat, cmd, desc, _ex) in enumerate(ADB命令集):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, i)
            item.setText(f'{cmd}\n{self._简述(desc)}')
            item.setToolTip(f'{cmd}\n{desc}')
            item.setSizeHint(QSize(0, 46))
            self.cmd_list.addItem(item)
        self._过滤列表()

    @staticmethod
    def _简述(desc: str, limit: int = 36) -> str:
        """把长说明压成列表里的一行简述：取第一句（按。；，切分）并截断。"""
        pos = [p for p in (desc.find(s) for s in '。；，') if p > 0]
        if pos:
            desc = desc[:min(pos)]
        return desc if len(desc) <= limit else desc[:limit] + '…'

    # -- 交互逻辑 -----------------------------------------------------
    def _过滤列表(self):
        kw = self.search_edit.text().strip().lower()
        cat_sel = self.cat_combo.currentData()
        visible = 0
        for i in range(self.cmd_list.count()):
            item = self.cmd_list.item(i)
            idx = item.data(Qt.UserRole)
            cat, cmd, desc, ex = ADB命令集[idx]
            hay = f'{cat} {cmd} {desc} {ex}'.lower()
            hit = (kw in hay if kw else True) and (cat == cat_sel if cat_sel else True)
            item.setHidden(not hit)
            if hit:
                visible += 1
        self.count_label.setText(f'{visible} 条')
        # 过滤后自动选中第一条可见项
        if visible:
            for i in range(self.cmd_list.count()):
                item = self.cmd_list.item(i)
                if not item.isHidden():
                    self.cmd_list.setCurrentItem(item)
                    break
        else:
            self.detail_view.setPlainText("（无匹配命令）")

    def _显示详情(self, current, _previous=None):
        if current is None:
            return
        idx = current.data(Qt.UserRole)
        cat, cmd, desc, ex = ADB命令集[idx]
        self.detail_view.setPlainText(
            f'【类别】{cat}\n'
            f'命令: {cmd}\n'
            f'说明: {desc}\n'
            f'实例: {ex}')

    def _复制当前命令(self):
        item = self.cmd_list.currentItem()
        if item is None:
            return
        idx = item.data(Qt.UserRole)
        cmd = ADB命令集[idx][1]
        QApplication.clipboard().setText(cmd)
        self.copy_btn.setText("已复制 ✓")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("复制命令"))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dlg = ADB命令集合对话框()
    dlg.show()
    sys.exit(app.exec())
