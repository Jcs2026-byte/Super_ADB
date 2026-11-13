# -*- coding: utf-8 -*-
"""
包信息对话框
============
异步展示指定包名的详细信息：安装路径、PID、版本号、版本名、SDK 等。
逐行获取、逐行展示，和设备信息弹窗风格一致。
"""
import re
import threading

from PySide6.QtCore import Qt, Slot, Signal, QObject
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit,
)

from 项目UI.界面样式 import get_stylesheet
from 项目UI.弹窗样式 import _create_popup_card
from 项目UI.透明外壳对话框 import 自绘外壳对话框


def _显示宽度(s):
    """计算字符显示宽度（中文=2，英文=1）。"""
    w = 0
    for c in str(s):
        cp = ord(c)
        if (0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F
                or 0xFF00 <= cp <= 0xFFEF or 0x2E80 <= cp <= 0x2EFF
                or 0x3400 <= cp <= 0x4DBF):
            w += 2
        else:
            w += 1
    return w


def _宽度填充(s, width):
    actual = _显示宽度(s)
    if actual >= width:
        return str(s)
    return str(s) + ' ' * (width - actual)


# ------------------------------------------------------------------
# 信息获取函数（按顺序执行，每条获取后立即展示）
# ------------------------------------------------------------------

def 获取包名(adb, serial, package_name):
    return package_name


def _F取缓存(缓存):
    """返回本次会话的临时缓存字典（各信息项共用，避免重复执行 shell）。"""
    return 缓存 if 缓存 is not None else {}


def _F缓存取值(缓存, 键, 生产函数):
    """带缓存的取值：首次调用才执行生产函数，之后直接复用结果。"""
    if 键 in 缓存:
        return 缓存[键]
    try:
        值 = 生产函数()
    except Exception:
        值 = None
    缓存[键] = 值
    return 值


def 获取安装路径(adb, serial, package_name, 缓存=None):
    try:
        缓存 = _F取缓存(缓存)
        结果 = _F缓存取值(缓存, '安装路径',
                         lambda: _F获取活动安装路径(adb, serial, package_name))
        路径列表 = (结果 or ([], set()))[0]
        return '\n  '.join(路径列表) if 路径列表 else '未安装'
    except Exception as e:
        return f'获取失败: {e}'


def 获取进程PID(adb, serial, package_name, 缓存=None):
    """展示该包所有正在运行的进程（含 :子进程），多进程时逐条列出。

    每个进程单独读 /proc/<pid>/maps，取它真正映射的 APK；
    双开/多用户场景下不同进程可能各自跑着不同版本的 APK，
    这时逐条标注各自 APK，不会只显示一个 PID。
    """
    try:
        缓存 = _F取缓存(缓存)
        进程列表 = _F缓存取值(缓存, '进程列表',
                            lambda: _F获取进程列表(adb, serial, package_name)) or []
        if not 进程列表:
            return '未运行'

        不同APK = sorted({进程.get('apk路径') for 进程 in 进程列表 if 进程.get('apk路径')})
        if len(不同APK) > 1:
            行列表 = []
            for 进程 in 进程列表:
                行列表.append(f'{进程["pid"]}  {进程["进程名"]}\n      → '
                              f'{进程.get("apk路径") or "APK 未知"}')
            return '\n  '.join(行列表)

        行列表 = [f'{进程["pid"]}  {进程["进程名"]}' for 进程 in 进程列表]
        行列表.append(f'（共 {len(进程列表)} 个进程'
                     + (f'，APK: {不同APK[0]}）' if 不同APK else '）'))
        return '\n  '.join(行列表)
    except Exception as e:
        return f'获取失败: {e}'


# dumpsys package 里每个包块的头： "  Package [com.foo.bar] (1a2b3c):"
_包块头_正则 = re.compile(r'^\s*Package \[([^\]]+)\]')

# 同一行里可能同时出现多个字段： versionCode=1 minSdk=21 targetSdk=29
_多字段键 = ('versionCode', 'minSdk', 'targetSdk')

# 单值字段 → 内部字段名
_单值字段 = {
    'codePath': '代码路径',
    'versionName': '版本名',
    'dataDir': '数据目录',
    'uid': 'UID',
    'userId': 'UID',
}


def _F获取活动安装路径(adb, serial, package_name):
    """用 pm path 取当前真正生效的 APK 路径，返回 (路径列表, 所在目录集合)。

    /data 下安装过的应用，pm path 只会返回 /data/app/... 这一份，
    正好可以用来判断 dumpsys 里哪个包块是"当前在用的"。
    """
    路径列表 = []
    目录集合 = set()
    try:
        raw = adb.执行shell(serial, f'pm path {package_name}', timeout=5)
    except Exception:
        return 路径列表, 目录集合
    for 行 in (raw or '').splitlines():
        路径 = 行.strip()
        if 路径.startswith('package:'):
            路径 = 路径[len('package:'):].strip()
        if not 路径 or 路径 == 'null':
            continue
        路径列表.append(路径)
        目录 = 路径.rsplit('/', 1)[0] if '/' in 路径 else 路径
        目录集合.add(目录.rstrip('/'))
    return 路径列表, 目录集合


def _F解析进程行(行, package_name):
    """从 ps 输出行解析 (pid, 进程名)，只保留本包相关进程（含 :子进程）。

    兼容两种列布局：
      toybox `ps -A -o PID,NAME` → "6889 com.x"
      老式 `ps`                  → "u0_a15 6889 1234 119404 ... S com.x"
    """
    片段 = (行 or '').split()
    if not 片段:
        return None
    命中名称 = ''
    for 片段项 in 片段:
        if package_name in 片段项:
            命中名称 = 片段项
            break
    if not 命中名称:
        return None
    pid = next((片段项 for 片段项 in 片段 if 片段项.isdigit()), '')
    if not pid:
        return None
    return pid, 命中名称


def _F取进程APK路径(adb, serial, pid, package_name=''):
    """读 /proc/<pid>/maps，取该进程真正映射的"本应用" APK 路径。

    注意不能简单取第一个 .apk：每个进程都会映射 /system/framework/framework-res.apk
    这类框架资源包，首个匹配往往不是应用自己。判定顺序：
      1) 路径里带包名（/data/app/<包名>-1/base.apk，split 分包同目录）
      2) /data/app 下的 apk
      3) 排除框架资源后的第一个 apk（纯 /system 预装应用兜底）
    """
    if not pid:
        return ''
    try:
        raw = adb.执行shell(
            serial,
            f"cat /proc/{pid}/maps 2>/dev/null | grep -o '/[^ ]*\\.apk'",
            timeout=5)
    except Exception:
        return ''

    路径列表 = []
    for 行 in (raw or '').splitlines():
        匹配 = re.search(r'(/[^ \t]*\.apk)', 行)
        if 匹配:
            路径 = 匹配.group(1)
            if 路径 not in 路径列表:
                路径列表.append(路径)

    if package_name:
        for 路径 in 路径列表:
            if package_name in 路径:
                return 路径
    for 路径 in 路径列表:
        if 路径.startswith('/data/app'):
            return 路径
    for 路径 in 路径列表:
        if not 路径.startswith('/system/framework'):
            return 路径
    return ''


def _F获取进程列表(adb, serial, package_name):
    """列出该包所有运行中的进程及其实际映射的 APK。

    Returns: [{'pid': '6889', '进程名': 'com.x', 'apk路径': '/data/app/.../base.apk'}, ...]
    """
    进程列表 = []
    行列表 = []
    try:
        行列表 = (adb.执行shell(serial, 'ps -A -o PID,NAME', timeout=5) or '').splitlines()
    except Exception:
        行列表 = []
    if not any(package_name in 行 for 行 in 行列表):
        # 老设备不认 -o 参数，或进程名被 ps 截断，退回到不带格式的 ps
        try:
            行列表 = (adb.执行shell(serial, 'ps -A', timeout=5) or '').splitlines()
        except Exception:
            行列表 = []

    已收PID = set()
    for 行 in 行列表:
        解析 = _F解析进程行(行, package_name)
        if not 解析:
            continue
        pid, 名称 = 解析
        if pid in 已收PID:
            continue
        已收PID.add(pid)
        进程列表.append({'pid': pid, '进程名': 名称, 'apk路径': ''})

    if not 进程列表:
        # ps 里完全找不到（进程名被截断/受限），用 pidof 兜底，只拿 PID
        try:
            原始 = adb.执行shell(serial, f'pidof {package_name}', timeout=3)
        except Exception:
            原始 = ''
        for pid in (原始 or '').split():
            if pid.isdigit() and pid not in 已收PID:
                已收PID.add(pid)
                进程列表.append({'pid': pid, '进程名': package_name, 'apk路径': ''})

    for 进程 in 进程列表:
        进程['apk路径'] = _F取进程APK路径(adb, serial, 进程['pid'], package_name)
    return 进程列表


def _F解析包块(dump文本):
    """按 "Package [包名]" 把 dumpsys package 输出分块，返回块字典列表。

    每块收集：包名、是否位于 Hidden system packages 段、代码路径、
    版本号、版本名、最低/目标 SDK、UID、数据目录。
    系统预装应用被 /data 更新覆盖时，dumpsys 末尾会多出一段
    Hidden system packages，里面是旧系统版本，必须区分开。
    """
    块列表 = []
    当前 = None
    在隐藏段 = False
    for 原始行 in (dump文本 or '').splitlines():
        行 = 原始行.strip()
        if not 行:
            continue
        if 行.startswith('Hidden system packages') or 行.startswith('Disabled system packages'):
            在隐藏段 = True
            continue
        if 行.startswith('Packages:') or 行.startswith('Dexopt state'):
            在隐藏段 = False
            continue
        匹配 = _包块头_正则.match(原始行)
        if 匹配:
            当前 = {'包名': 匹配.group(1), '隐藏段': 在隐藏段, '代码路径': '',
                    '版本号': '', '版本名': '', '最低SDK': '', '目标SDK': '',
                    'UID': '', '数据目录': ''}
            块列表.append(当前)
            continue
        if 当前 is None:
            continue

        首字段 = 行.split()[0]
        首键, 分隔符, 首值 = 首字段.partition('=')
        if not 分隔符:
            continue

        if 首键 in _多字段键:
            键值 = {}
            for 片段 in 行.split():
                键, _, 值 = 片段.partition('=')
                if 值 and 键 not in 键值:
                    键值[键] = 值
            for 字段 in _多字段键:
                内部名 = {'versionCode': '版本号', 'minSdk': '最低SDK', 'targetSdk': '目标SDK'}[字段]
                if 字段 in 键值 and not 当前[内部名]:
                    当前[内部名] = 键值[字段]
            continue

        内部名 = _单值字段.get(首键)
        if not 内部名:
            continue
        if not 首值 or 首值.lower() == 'null':
            continue
        if not 当前[内部名]:
            当前[内部名] = 首值

    return 块列表


def _F路径与代码路径一致(apk路径, 代码路径):
    """判断某个 APK 路径是否属于 dumpsys 的 codePath（两种路径风格都要适配）。

    新版：apk=/data/app/com.x-1/base.apk        codePath=/data/app/com.x-1
    老版：apk=/data/app/com.x-1.apk             codePath=/data/app/com.x-1.apk
    注意老版不能再"去掉文件名取目录"，否则得到笼统的 /data/app，匹配不到任何块。
    """
    apk路径 = (apk路径 or '').strip()
    代码路径 = (代码路径 or '').strip().rstrip('/')
    if not apk路径 or not 代码路径:
        return False
    if apk路径 == 代码路径 or apk路径.startswith(代码路径 + '/'):
        return True
    if apk路径.lower().endswith('.apk'):
        return apk路径[:-len('.apk')] == 代码路径
    return False


def _F选择活动包块(块列表, 进程APK列表=(), 安装路径列表=()):
    """挑出当前真正生效的那一块。

    优先级：进程实际映射的 APK → pm path 返回的 APK → 代码路径在 /data 下
            → 数据目录在 /data 下 → 首个非隐藏块。
    """
    可用块 = [块 for 块 in 块列表 if not 块.get('隐藏段')] or 块列表

    def _按APK匹配(APK列表):
        for 块 in 可用块:
            for apk in APK列表 or ():
                if _F路径与代码路径一致(apk, 块.get('代码路径')):
                    return 块
        return None

    for APK列表 in (进程APK列表, 安装路径列表):
        命中块 = _按APK匹配(APK列表 or ())
        if 命中块:
            return 命中块

    # 程序走到这里说明路径都没对上，按 /data 前缀兜底
    for 块 in 可用块:
        if (块.get('代码路径') or '').startswith('/data'):
            return 块
    for 块 in 可用块:
        if (块.get('数据目录') or '').startswith('/data'):
            return 块
    return 可用块[0] if 可用块 else None


def 获取版本信息(adb, serial, package_name, 缓存=None):
    """从 dumpsys package 提取版本号、版本名、SDK 等信息。

    优先用"进程实际映射的 APK"（/proc/<pid>/maps）锚定包块，其次 pm path，
    最后才退到 /data 前缀。系统预装应用的旧版本位于 dump 末尾的
    Hidden system packages 段（codePath=/system/...、dataDir=null），
    不会被选中。
    """
    try:
        缓存 = _F取缓存(缓存)
        安装路径结果 = _F缓存取值(缓存, '安装路径',
                               lambda: _F获取活动安装路径(adb, serial, package_name))
        路径列表, _pm目录集合 = 安装路径结果 or ([], set())
        进程列表 = _F缓存取值(缓存, '进程列表',
                            lambda: _F获取进程列表(adb, serial, package_name)) or []
        进程APK列表 = [进程.get('apk路径') for 进程 in 进程列表 if 进程.get('apk路径')]
        进程APK列表 = [apk for apk in 进程APK列表
                    if package_name in apk or apk.startswith('/data')]

        raw = _F缓存取值(缓存, '包信息dump',
                         lambda: adb.执行shell(serial, f'dumpsys package {package_name}', timeout=10))
        块列表 = _F解析包块(raw or '')
        块 = _F选择活动包块(块列表, 进程APK列表, 路径列表)
        if not 块:
            return '未获取到版本信息'

        lines = []
        if 块['版本名']:
            lines.append(f"版本名: {块['版本名']}")
        if 块['版本号']:
            lines.append(f"版本号: {块['版本号']}")
        if 块['最低SDK']:
            lines.append(f"最低 SDK: {块['最低SDK']}")
        if 块['目标SDK']:
            lines.append(f"目标 SDK: {块['目标SDK']}")
        if 块['UID']:
            lines.append(f"UID: {块['UID']}")
        数据目录 = 块['数据目录'] or (路径列表[0] if 路径列表 else '')
        if 数据目录:
            lines.append(f"数据目录: {数据目录}")
        if 块['代码路径']:
            lines.append(f"版本路径: {块['代码路径']}")

        # 多进程各自跑着不同 APK 时（双开/多用户），把其余版本也列出来
        其他APK = sorted(apk for apk in set(进程APK列表)
                      if not _F路径与代码路径一致(apk, 块['代码路径']))
        if 其他APK:
            lines.append('其他运行中 APK:')
            for apk in 其他APK:
                其他块 = next((候选 for 候选 in 块列表
                               if _F路径与代码路径一致(apk, 候选['代码路径'])), None)
                版本 = (f"{其他块['版本名']}（{其他块['版本号']}）"
                        if 其他块 and 其他块['版本名'] else '版本未知')
                lines.append(f"  {apk} → {版本}")

        return '\n  '.join(lines) if lines else '未获取到版本信息'
    except Exception as e:
        return f'获取失败: {e}'


def 获取应用大小(adb, serial, package_name, 缓存=None):
    """获取 APK 占用大小（用 du 统计安装路径）。"""
    try:
        缓存 = _F取缓存(缓存)
        安装路径结果 = _F缓存取值(缓存, '安装路径',
                               lambda: _F获取活动安装路径(adb, serial, package_name))
        路径列表 = (安装路径结果 or ([], set()))[0]
        if not 路径列表:
            return '未知（未安装）'
        total = 0
        for 路径 in 路径列表:
            try:
                du = adb.执行shell(serial, f'du -s {路径} 2>/dev/null | awk "{{print $1}}"', timeout=5)
                size_kb = du.strip().split()[0] if du.strip() else '0'
                total += int(size_kb)
            except Exception:
                pass
        if total > 1024 * 1024:
            return f'{total / 1024 / 1024:.1f} MB'
        elif total > 1024:
            return f'{total / 1024:.1f} MB'
        else:
            return f'{total} KB'
    except Exception as e:
        return f'获取失败: {e}'


# 信息项列表：(显示名称, 获取函数)
_INFO_ITEMS = [
    ('安装路径', 获取安装路径),
    ('进程 PID', 获取进程PID),
    ('版本信息', 获取版本信息),
    ('应用大小', 获取应用大小),
]


class _结果信号(QObject):
    """后台线程用信号把结果发回主线程。"""
    单条完成 = Signal(str, str)  # (名称, 值)
    全部完成 = Signal()


class 包信息对话框(自绘外壳对话框):
    """包信息弹窗：异步获取并展示指定包的详细信息。"""

    def __init__(self, adb, serial, package_name, theme_id, parent=None):
        super().__init__(parent, 标题=f'包信息 — {package_name}', 最小尺寸=(600, 420))
        self.adb = adb
        self.serial = serial
        self.package_name = package_name
        self._theme_id = theme_id
        self._cancelled = threading.Event()
        self._信号 = _结果信号()
        self._信号.单条完成.connect(self._追加一行)
        self._信号.全部完成.connect(self._完成)

        self.setStyleSheet(get_stylesheet(theme_id))

        # 内层亮边卡片
        self.card, _ = _create_popup_card(self, theme_id)

        self._build_ui()
        self._启动获取()

    def _build_ui(self):
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        # 包名只在窗口标题栏显示一次，卡片内不再重复
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setPlainText('正在获取包信息…\n')
        lay.addWidget(self.text_edit, 1)

    def apply_theme(self, theme_id):
        if theme_id == self._theme_id:
            return
        self._theme_id = theme_id
        self.setStyleSheet(get_stylesheet(theme_id))
        self.update()

    def _启动获取(self):
        def _work():
            缓存 = {}  # 本次弹窗内的共享缓存：pm path / 进程列表 / dumpsys 各只执行一次
            for 名称, fn in _INFO_ITEMS:
                if self._cancelled.is_set():
                    return
                try:
                    值 = fn(self.adb, self.serial, self.package_name, 缓存)
                except Exception as e:
                    值 = f'获取失败: {e}'
                if self._cancelled.is_set():
                    return
                self._信号.单条完成.emit(名称, str(值))
            if not self._cancelled.is_set():
                self._信号.全部完成.emit()

        threading.Thread(target=_work, daemon=True).start()

    @Slot(str, str)
    def _追加一行(self, 名称, 值):
        try:
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
            行 = f'\n【{名称}】\n  {值}\n'
            self.text_edit.insertPlainText(行)
        except Exception:
            pass

    @Slot()
    def _完成(self):
        try:
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
            self.text_edit.insertPlainText('\n── 信息获取完成 ──\n')
        except Exception:
            pass

    def closeEvent(self, event):
        self._cancelled.set()
        super().closeEvent(event)
