# -*- coding: utf-8 -*-
"""
包信息对话框
============
异步展示指定包名的详细信息：安装路径、PID、版本号、版本名、SDK 等。
逐行获取、逐行展示，和设备信息弹窗风格一致。
"""
import threading

from PySide6.QtCore import Qt, Slot, Signal, QObject
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QLabel,
)

from 项目UI.界面样式 import get_stylesheet
from 项目UI.弹窗样式 import _create_popup_card


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


def 获取安装路径(adb, serial, package_name):
    try:
        raw = adb.执行shell(serial, f'pm path {package_name}', timeout=5)
        lines = [l.strip().replace('package:', '') for l in (raw or '').splitlines() if l.strip()]
        return '\n  '.join(lines) if lines else '未安装'
    except Exception as e:
        return f'获取失败: {e}'


def 获取PID(adb, serial, package_name):
    try:
        raw = adb.执行shell(serial, f'pidof {package_name}', timeout=3)
        pid = raw.strip()
        return pid if pid else '未运行'
    except Exception as e:
        return f'获取失败: {e}'


def 获取版本信息(adb, serial, package_name):
    """从 dumpsys package 提取版本号、版本名、SDK 等信息。"""
    try:
        raw = adb.执行shell(serial, f'dumpsys package {package_name}', timeout=10)
        info = {}
        for line in (raw or '').splitlines():
            line = line.strip()
            if 'versionCode=' in line:
                parts = line.split('versionCode=')
                if len(parts) >= 2:
                    info['versionCode'] = parts[1].split()[0]
            elif 'versionName=' in line:
                parts = line.split('versionName=')
                if len(parts) >= 2:
                    info['versionName'] = parts[1].split()[0]
            elif 'targetSdk=' in line:
                parts = line.split('targetSdk=')
                if len(parts) >= 2:
                    info['targetSdk'] = parts[1].split()[0]
            elif 'minSdk=' in line:
                parts = line.split('minSdk=')
                if len(parts) >= 2:
                    info['minSdk'] = parts[1].split()[0]
            elif 'dataDir=' in line:
                parts = line.split('dataDir=')
                if len(parts) >= 2:
                    info['dataDir'] = parts[1].split()[0]
            elif 'uid=' in line and not info.get('uid'):
                parts = line.split('uid=')
                if len(parts) >= 2:
                    info['uid'] = parts[1].split()[0]

        lines = []
        if 'versionName' in info:
            lines.append(f"版本名: {info['versionName']}")
        if 'versionCode' in info:
            lines.append(f"版本号: {info['versionCode']}")
        if 'minSdk' in info:
            lines.append(f"最低 SDK: {info['minSdk']}")
        if 'targetSdk' in info:
            lines.append(f"目标 SDK: {info['targetSdk']}")
        if 'uid' in info:
            lines.append(f"UID: {info['uid']}")
        if 'dataDir' in info:
            lines.append(f"数据目录: {info['dataDir']}")
        return '\n  '.join(lines) if lines else '未获取到版本信息'
    except Exception as e:
        return f'获取失败: {e}'


def 获取应用大小(adb, serial, package_name):
    """获取 APK 占用大小（用 du 统计安装路径）。"""
    try:
        raw = adb.执行shell(serial, f'pm path {package_name}', timeout=3)
        paths = [l.strip().replace('package:', '') for l in (raw or '').splitlines() if l.strip().startswith('package:')]
        if not paths:
            return '未知（未安装）'
        total = 0
        for p in paths:
            try:
                du = adb.执行shell(serial, f'du -s {p} 2>/dev/null | awk "{{print $1}}"', timeout=5)
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
    ('进程 PID', 获取PID),
    ('版本信息', 获取版本信息),
    ('应用大小', 获取应用大小),
]


class _结果信号(QObject):
    """后台线程用信号把结果发回主线程。"""
    单条完成 = Signal(str, str)  # (名称, 值)
    全部完成 = Signal()


class 包信息对话框(QDialog):
    """包信息弹窗：异步获取并展示指定包的详细信息。"""

    def __init__(self, adb, serial, package_name, theme_id, parent=None):
        super().__init__(parent)
        self.adb = adb
        self.serial = serial
        self.package_name = package_name
        self._theme_id = theme_id
        self._cancelled = threading.Event()
        self._信号 = _结果信号()
        self._信号.单条完成.connect(self._追加一行)
        self._信号.全部完成.connect(self._完成)

        self.setWindowTitle(f'包信息 — {package_name}')
        self.setMinimumSize(600, 420)
        self.setStyleSheet(get_stylesheet(theme_id))

        # 内层亮边卡片
        self.card, _ = _create_popup_card(self, theme_id)

        self._build_ui()
        self._启动获取()

    def _build_ui(self):
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        title = QLabel(f'包名: {self.package_name}')
        lay.addWidget(title)

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
            for 名称, fn in _INFO_ITEMS:
                if self._cancelled.is_set():
                    return
                try:
                    值 = fn(self.adb, self.serial, self.package_name)
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
