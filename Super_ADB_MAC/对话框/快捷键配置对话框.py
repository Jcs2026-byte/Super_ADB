# -*- coding: utf-8 -*-
"""
快捷键配置对话框
================
配置截屏/录屏全局热键，触发后框选屏幕区域截图或录屏。
"""
import os
import sys
import json
import time
import datetime

from PySide6.QtCore import Qt, QRect, QPoint, QTimer, Signal, QObject, QUrl
from PySide6.QtGui import QGuiApplication, QPainter, QPen, QColor, QKeySequence, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QFormLayout, QMessageBox, QApplication, QWidget,
)

from 项目UI.对话框基类 import 对话框基类
from 项目UI.界面样式 import get_stylesheet, get_current_theme_id

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '配置', 'Super_ADB配置.json')
DEFAULT_CONFIG = {
    'hotkey_screenshot': '',
    'hotkey_recording': '',
}


def _load_hotkey_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **(cfg.get('hotkeys', {}))}
    except Exception:
        return dict(DEFAULT_CONFIG)


def _save_hotkey_config(hotkeys):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        cfg = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        cfg['hotkeys'] = hotkeys
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f'[热键] 保存配置失败: {e}')
        return False


# ── 截图预览窗口全局引用（防止GC回收）──
_F全局预览列表 = []


# ── 框选截图覆盖层 ──
class _C框选覆盖层(QWidget):
    """全屏覆盖层，鼠标拖拽框选区域，释放后截图。"""

    def __init__(self, on_captured=None, parent=None):
        super().__init__(None)
        self._F回调 = on_captured
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # 覆盖所有屏幕
        screen_geo = QGuiApplication.primaryScreen().virtualGeometry()
        for s in QGuiApplication.screens():
            sg = s.geometry()
            screen_geo = screen_geo.united(sg)
        self.setGeometry(screen_geo)
        # 关键：设置 mask 防止 Windows 把透明区域的鼠标事件穿透到下面
        self.setMask(self.rect())
        self._F起点 = None
        self._F终点 = None

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def mousePressEvent(self, event):
        print(f'[覆盖层] mousePressEvent: {event.position().toPoint()}')
        if event.button() == Qt.MouseButton.LeftButton:
            self._F起点 = event.position().toPoint()
            self._F终点 = None
            self.update()

    def mouseMoveEvent(self, event):
        if self._F起点:
            self._F终点 = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        print(f'[覆盖层] mouseReleaseEvent: start={self._F起点} end={self._F终点}')
        if event.button() == Qt.MouseButton.LeftButton and self._F起点 and self._F终点:
            x1 = min(self._F起点.x(), self._F终点.x())
            y1 = min(self._F起点.y(), self._F终点.y())
            x2 = max(self._F起点.x(), self._F终点.x())
            y2 = max(self._F起点.y(), self._F终点.y())
            self.close()
            if self._F回调:
                self._F回调(QRect(x1, y1, x2 - x1, y2 - y1))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        if not self._F起点 or not self._F终点:
            return
        rect = QRect(
            min(self._F起点.x(), self._F终点.x()),
            min(self._F起点.y(), self._F终点.y()),
            abs(self._F终点.x() - self._F起点.x()),
            abs(self._F终点.y() - self._F起点.y()),
        )
        painter.setClipRect(rect, Qt.ClipOperation.ReplaceClip)
        painter.fillRect(rect, Qt.transparent)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(0, 200, 255), 2))
        painter.drawRect(rect)


# ── 快捷键录制输入框 ──
class _HotkeyEdit(QLineEdit):
    """点击后进入录制模式，按键盘组合键自动记录。"""

    def __init__(self, hotkey='', parent=None):
        super().__init__(parent)
        self._recording = False
        self.setText(hotkey)
        self.setReadOnly(True)
        self.setPlaceholderText('点击后按组合键…')
        self.setStyleSheet("QLineEdit { padding: 6px; }")

    def mousePressEvent(self, event):
        self._recording = True
        self.setText('请按组合键…')
        self.setStyleSheet("QLineEdit { padding: 6px; background: #1a3a5c; border: 1px solid #00c8ff; }")
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if not self._recording:
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._recording = False
            self.setText(self._saved_text)
            self.setStyleSheet("QLineEdit { padding: 6px; }")
            return
        if key == Qt.Key.Key_Backspace:
            self.setText('')
            self._recording = False
            self.setStyleSheet("QLineEdit { padding: 6px; }")
            return
        # 解析修饰键
        mods = []
        m = event.modifiers()
        if m & Qt.KeyboardModifier.ControlModifier:
            mods.append('ctrl')
        if m & Qt.KeyboardModifier.AltModifier:
            mods.append('alt')
        if m & Qt.KeyboardModifier.ShiftModifier:
            mods.append('shift')
        if m & Qt.KeyboardModifier.MetaModifier:
            mods.append('win')
        # 主键
        k = key
        if k in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta):
            return  # 只按了修饰键，等主键
        key_name = QKeySequence(k).toString().lower()
        combo = '+'.join(mods + [key_name])
        self.setText(combo)
        self._recording = False
        self.setStyleSheet("QLineEdit { padding: 6px; }")

    def focusOutEvent(self, event):
        if self._recording:
            self._recording = False
            self.setText(getattr(self, '_saved_text', ''))
            self.setStyleSheet("QLineEdit { padding: 6px; }")
        super().focusOutEvent(event)

    def showEvent(self, event):
        self._saved_text = self.text()
        super().showEvent(event)


# ── 系统自带功能检测 ──
def _检测截图工具():
    """检测系统自带截图工具是否可用。
    纯版本/文件系统判断，毫秒级，不启动子进程。
    返回: {'可用': bool, '热键': str, '说明': str, '相对路径': str, '绝对路径': str}"""
    结果 = {'可用': False, '热键': '', '说明': '', '相对路径': '', '绝对路径': ''}
    if _sys.platform.startswith('win'):
        结果['热键'] = 'Win+Shift+S'
        可用 = False
        # 1) 系统版本 >= Win10 1809 (build 17763) 即支持截图工具 Win+Shift+S
        try:
            import platform as _platform
            ver = _platform.version()
            parts = [int(x) for x in ver.split('.')]
            build = parts[2] if len(parts) > 2 else 0
            可用 = build >= 17763
        except Exception:
            可用 = False
        # 2) 保险：截图工具应用目录存在
        if not 可用:
            try:
                可用 = os.path.isdir(r'C:\Windows\SystemApps\Microsoft.Windows.ScreenSketch_cw5n1h2txyewy')
            except Exception:
                可用 = False
        if 可用:
            结果['可用'] = True
            结果['说明'] = '截图默认保存到剪贴板'
            pics = os.path.join(os.path.expanduser('~'), 'Pictures', 'Screenshots')
            if os.path.isdir(pics):
                结果['相对路径'] = 'Pictures\\Screenshots'
                结果['绝对路径'] = pics
    elif _sys.platform == 'darwin':
        # macOS 全系支持
        结果 = {'可用': True, '热键': '⌘⇧4', '说明': '区域截图，保存到桌面',
                '相对路径': 'Desktop', '绝对路径': os.path.join(os.path.expanduser('~'), 'Desktop')}
    else:
        # Linux: 检测常见截图工具
        import shutil
        for tool in ('gnome-screenshot', 'spectacle', 'flameshot', 'grim', 'scrot'):
            if shutil.which(tool):
                结果 = {'可用': True, '热键': 'PrintScreen', '说明': '使用 ' + tool,
                        '相对路径': 'Pictures', '绝对路径': os.path.join(os.path.expanduser('~'), 'Pictures')}
                break
    return 结果


def _检测录屏工具():
    """检测系统自带录屏功能是否可用（Windows: Game Bar Win+Alt+R）。
    纯注册表读取，毫秒级，不启动子进程。"""
    结果 = {'可用': False, '热键': '', '说明': '', '相对路径': '', '绝对路径': ''}
    if _sys.platform.startswith('win'):
        结果['热键'] = 'Win+Alt+R'
        可用 = False
        try:
            import winreg
            # Game Bar (XboxGamingOverlay) 已安装：HKLM Appx 应用注册表
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r'SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Applications') as k:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    if 'microsoft.xboxgamingoverlay' in name.lower():
                        可用 = True
                        break
                    i += 1
        except OSError:
            可用 = False
        if not 可用:
            # 回退：HKCU GameBar 键存在
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\GameBar'):
                    pass
                可用 = True
            except OSError:
                可用 = False
        if 可用:
            # Game DVR 被显式关闭时录屏不可用
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'System\GameConfigStore') as k:
                    val, _ = winreg.QueryValueEx(k, 'GameDVR_Enabled')
                if val == 0:
                    可用 = False
            except OSError:
                pass
        if 可用:
            结果['可用'] = True
            vids = os.path.join(os.path.expanduser('~'), 'Videos', 'Captures')
            结果['相对路径'] = 'Videos\\Captures'
            结果['绝对路径'] = vids
            结果['说明'] = '录屏默认保存位置（相对当前用户目录）'
            if not os.path.isdir(vids):
                结果['说明'] = '尚未录制过，首次录屏后自动创建该目录'
    elif _sys.platform == 'darwin':
        # macOS 录屏 Cmd+Shift+5
        结果 = {'可用': True, '热键': '⌘⇧5', '说明': '录屏保存到桌面',
                '相对路径': 'Desktop', '绝对路径': os.path.join(os.path.expanduser('~'), 'Desktop')}
    else:
        import shutil
        for tool in ('obs', 'wf-recorder', 'kooha'):
            if shutil.which(tool):
                结果 = {'可用': True, '热键': '见应用设置', '说明': '使用 ' + tool,
                        '相对路径': 'Videos', '绝对路径': os.path.join(os.path.expanduser('~'), 'Videos')}
                break
    return 结果


# ── 快捷键配置对话框（本软件截图 + 系统自带功能检测）──
class 快捷键配置对话框(对话框基类):
    """本软件截图（框选+标注）配置 + 系统自带截图/录屏功能检测展示。"""

    def __init__(self, parent=None):
        super().__init__(parent, 标题='快捷键配置', 最小尺寸=(620, 540), 发光=False)
        self._cfg = _load_hotkey_config()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        tip = QLabel('本软件截图可自行配置快捷键；系统自带截图/录屏功能无需设置（每台电脑可能不同）。')
        tip.setStyleSheet('color: #888;')
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # ── 本软件截图（框选 + 标注）──
        grp_shot = QGroupBox('截屏（框选区域截图）')
        gl_shot = QFormLayout(grp_shot)
        self.edit_shot = _HotkeyEdit(self._cfg.get('hotkey_screenshot', ''))
        gl_shot.addRow('快捷键:', self.edit_shot)
        btn_test_shot = QPushButton('测试截屏')
        btn_test_shot.clicked.connect(self._test_screenshot)
        gl_shot.addRow('', btn_test_shot)
        lbl_save = QLabel('保存位置: 桌面/Super_ADB/截图')
        lbl_save.setStyleSheet('color: #888;')
        gl_shot.addRow('', lbl_save)
        lay.addWidget(grp_shot)

        # ── 系统截图工具（检测展示）──
        grp_sys = QGroupBox('系统截图工具')
        gl_sys = QFormLayout(grp_sys)
        self._F系统截屏键 = QLabel('检测中…')
        self._F系统截屏键.setTextFormat(Qt.TextFormat.RichText)
        gl_sys.addRow('快捷键:', self._F系统截屏键)
        self._F系统截屏路径 = QLabel('')
        self._F系统截屏路径.setTextFormat(Qt.TextFormat.RichText)
        self._F系统截屏路径.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._F系统截屏路径.linkActivated.connect(self._F打开目录)
        gl_sys.addRow('保存位置:', self._F系统截屏路径)
        lay.addWidget(grp_sys)

        # ── 系统录屏（Game Bar，检测展示）──
        grp_rec = QGroupBox('录屏（系统 Game Bar）')
        gl_rec = QFormLayout(grp_rec)
        self._F录屏键 = QLabel('检测中…')
        self._F录屏键.setTextFormat(Qt.TextFormat.RichText)
        gl_rec.addRow('快捷键:', self._F录屏键)
        self._F录屏路径 = QLabel('')
        self._F录屏路径.setTextFormat(Qt.TextFormat.RichText)
        self._F录屏路径.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._F录屏路径.linkActivated.connect(self._F打开目录)
        gl_rec.addRow('保存位置:', self._F录屏路径)
        lay.addWidget(grp_rec)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_save = QPushButton('保存')
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton('取消')
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        # 界面先显示，检测结果异步填充，避免弹窗打开卡顿
        QTimer.singleShot(0, self._F刷新系统检测)

    def _F刷新系统检测(self):
        """运行系统功能检测并更新界面展示。"""
        self._F设置模块(self._F系统截屏键, self._F系统截屏路径, _检测截图工具())
        self._F设置模块(self._F录屏键, self._F录屏路径, _检测录屏工具())

    def _F设置模块(self, key_lbl, path_lbl, info):
        if info['可用']:
            key_lbl.setText(f"{info['热键']}　<span style='color:#1de9b6;'>✓ 可用</span>")
        else:
            key_lbl.setText(f"{info['热键']}　<span style='color:#ff6b6b;'>✗ 未检测到</span>")
        if not info['可用']:
            path_lbl.setText("<span style='color:#888;'>该功能在此电脑上不可用</span>")
        elif info['绝对路径']:
            href = QUrl.fromLocalFile(info['绝对路径']).toString()
            path_lbl.setText(
                f"<a href='{href}' style='color:#4fc3f7; text-decoration:underline;'>{info['相对路径']}</a>"
                f"　<span style='color:#888;'>{info['说明']}</span>")
        else:
            path_lbl.setText(f"<span style='color:#888;'>{info['说明']}</span>")

    def _F打开目录(self, link):
        """点击保存位置链接，用系统资源管理器打开该目录。"""
        QDesktopServices.openUrl(QUrl(link))

    # ── 本软件截图功能（框选 + 标注）──
    def _test_screenshot(self):
        self.hide()
        self._start_select_screenshot()

    def _start_select_screenshot(self):
        # 先关闭旧覆盖层和旧预览
        try:
            if hasattr(self, '_当前覆盖层') and self._当前覆盖层:
                self._当前覆盖层.close()
        except Exception:
            pass
        for p in list(_F全局预览列表):
            try:
                p.close()
            except Exception:
                pass
        _F全局预览列表.clear()
        self._当前覆盖层 = _C框选覆盖层(on_captured=self._do_screenshot, parent=None)
        self._当前覆盖层.show()
        self._当前覆盖层.raise_()
        self._当前覆盖层.activateWindow()

    def _do_screenshot(self, rect):
        """框选完成，弹出预览工具条（类似QQ截图）"""
        screen = QGuiApplication.primaryScreen()
        geo = screen.virtualGeometry()
        pixmap = screen.grabWindow(0, rect.x() + geo.x(), rect.y() + geo.y(),
                                    rect.width(), rect.height())
        preview = _C截图工具条(pixmap, rect, parent=None)
        _F全局预览列表.append(preview)
        preview.destroyed.connect(lambda: _F全局预览列表.remove(preview) if preview in _F全局预览列表 else None)

    def _save(self):
        # 只保存本软件截屏热键；录屏使用系统 Game Bar，不再注册
        hotkeys = {
            'hotkey_screenshot': self.edit_shot.text().strip(),
            'hotkey_recording': '',
        }
        # 允许为空表示不使用；检查热键是否被占用（仅 Windows）
        if _sys.platform == 'win32':
            import ctypes
            user32 = ctypes.windll.user32
            for hid in list(_registered_ids):
                try:
                    user32.UnregisterHotKey(None, hid)
                except Exception:
                    pass
            _registered_ids.clear()
            冲突 = False
            for name, key in [('截屏', hotkeys['hotkey_screenshot'])]:
                if not key:
                    continue
                parts = key.lower().split('+')
                mod = 0
                vk = None
                for p in parts:
                    p = p.strip()
                    if p in _MOD_MAP:
                        mod |= _MOD_MAP[p]
                    elif len(p) == 1:
                        vk = ord(p.upper())
                    elif p == 'space':
                        vk = 0x20
                if vk is None:
                    continue
                test_id = 9999
                if not user32.RegisterHotKey(None, test_id, mod | _MOD_NOREPEAT, vk):
                    QMessageBox.warning(self, '热键冲突',
                                        f'{name}热键 "{key}" 已被其他程序占用，请更换。')
                    冲突 = True
                    break
                user32.UnregisterHotKey(None, test_id)
            if 冲突:
                _register_hotkeys()  # 恢复原来的
                return
        if _save_hotkey_config(hotkeys):
            _register_hotkeys()
            self.accept()
        else:
            QMessageBox.warning(self, '错误', '保存配置失败')


# ── 全局热键注册（Windows API RegisterHotKey，不需要管理员权限）──
import sys as _sys

_WM_HOTKEY = 0x0312
_MOD_MAP = {
    'alt': 0x0001, 'ctrl': 0x0002, 'control': 0x0002,
    'shift': 0x0004, 'win': 0x0008,
}
_MOD_NOREPEAT = 0x4000

# 热键 ID
_HOTKEY_ID_SHOT = 1
_HOTKEY_ID_REC = 2

_registered_ids = []
_hwnd = None


def _parse_hotkey(combo):
    """把 'ctrl+alt+a' 解析为 (modifiers, vk)。"""
    parts = [p.strip().lower() for p in combo.split('+') if p.strip()]
    mods = 0
    vk = 0
    for p in parts:
        if p in _MOD_MAP:
            mods |= _MOD_MAP[p]
        elif len(p) == 1:
            c = p.upper()
            if 'A' <= c <= 'Z':
                vk = ord(c)
            elif '0' <= c <= '9':
                vk = ord(c)
        # 功能键 F1-F24
        elif p.startswith('f') and p[1:].isdigit():
            num = int(p[1:])
            if 1 <= num <= 24:
                vk = 0x70 + num - 1  # VK_F1 = 0x70
    return mods, vk


def _register_hotkeys():
    """从配置读取热键并通过 RegisterHotKey 注册（无需管理员权限）。"""
    global _registered_ids, _hwnd
    if not _sys.platform.startswith('win'):
        _register_hotkeys_unix()
        return
    import ctypes
    user32 = ctypes.windll.user32

    # 先注销旧的
    for hid in _registered_ids:
        try:
            user32.UnregisterHotKey(None, hid)
        except Exception:
            pass
    _registered_ids.clear()

    # 获取主窗口句柄
    app = QApplication.instance()
    if app is None:
        return
    win = app.activeWindow()
    if win is None:
        win = app.topLevelWidgets()[0] if app.topLevelWidgets() else None
    if win is None:
        return
    _hwnd = int(win.winId())

    cfg = _load_hotkey_config()
    shot_key = cfg.get('hotkey_screenshot', '')
    rec_key = cfg.get('hotkey_recording', '')

    # 注册截屏热键
    mods, vk = _parse_hotkey(shot_key)
    if vk:
        if user32.RegisterHotKey(None, _HOTKEY_ID_SHOT, mods | _MOD_NOREPEAT, vk):
            _registered_ids.append(_HOTKEY_ID_SHOT)
        else:
            err = ctypes.GetLastError()
            print(f'[快捷键] 截屏热键注册失败: {shot_key}, 错误码={err}')
            if err == 1409:
                print(f'[快捷键] 热键被其他程序占用')

    # 注册录屏热键
    mods, vk = _parse_hotkey(rec_key)
    if vk:
        if user32.RegisterHotKey(None, _HOTKEY_ID_REC, mods | _MOD_NOREPEAT, vk):
            _registered_ids.append(_HOTKEY_ID_REC)
        else:
            err = ctypes.GetLastError()
            print(f'[快捷键] 录屏热键注册失败: {rec_key}, 错误码={err}')

    # 安装 nativeEvent 过滤器接收 WM_HOTKEY
    _HotkeyFilter.install()


class _HotkeyFilter:
    """事件过滤器：接收 WM_HOTKEY 消息。"""
    _inst = None

    @classmethod
    def install(cls):
        app = QApplication.instance()
        if app is None:
            return
        if cls._inst is None:
            cls._inst = _NativeEventFilter()
        app.installNativeEventFilter(cls._inst)


from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray


class _NativeEventFilter(QAbstractNativeEventFilter):
    def nativeEventFilter(self, eventType, message):
        if bytes(eventType) == b"windows_generic_MSG" or eventType == b"windows_generic_MSG":
            try:
                import ctypes
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == _WM_HOTKEY:
                    hotkey_id = int(msg.wParam)
                    if hotkey_id == _HOTKEY_ID_SHOT:
                        _global_start_screenshot()
                    elif hotkey_id == _HOTKEY_ID_REC:
                        _global_start_recording()
                    return True, 0
            except Exception:
                pass
        return False, 0


def _global_start_screenshot():
    """全局热键触发：弹出框选截图覆盖层。"""
    overlay = _C框选覆盖层(on_captured=_global_do_screenshot, parent=None)
    overlay.show()
    overlay.activateWindow()


def _global_do_screenshot(rect):
    """框选完成，截图并弹出预览工具条。"""
    # 隐藏覆盖层和所有窗口再截图
    app = QApplication.instance()
    for w in app.topLevelWidgets():
        if w.isVisible() and w is not None:
            w.hide()
    QApplication.processEvents()
    screen = QGuiApplication.primaryScreen()
    pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
    # 恢复窗口
    for w in app.topLevelWidgets():
        w.show()
    # 弹出预览工具条
    preview = _C截图工具条(pixmap, rect, parent=None)
    _F全局预览列表.append(preview)


def _global_start_recording():
    """全局热键触发录屏（占位）。"""
    QMessageBox.information(None, '录屏', '录屏功能开发中')


# ── 标注画布 ──
# ── 标注画布 ──
class _C图形基类(QWidget):
    """矩形/椭圆/箭头的浮动基类，可拖动、选中、调整大小。"""
    手柄大小 = 8

    def __init__(self, canvas, start, color, pen, 类型, 比例=1.0):
        super().__init__(canvas)
        self._F画布 = canvas
        self._F比例 = 比例
        self._F起点 = start
        self._F终点 = start
        self._F颜色 = color
        self._F粗 = pen
        self._F类型 = 类型
        self._F拖动偏移 = None
        self._F调整大小 = False
        self._F选中 = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def setEnd(self, end):
        self._F终点 = end
        self._F更新几何()

    def _F更新几何(self):
        x = min(self._F起点.x(), self._F终点.x())
        y = min(self._F起点.y(), self._F终点.y())
        w = abs(self._F终点.x() - self._F起点.x())
        h = abs(self._F终点.y() - self._F起点.y())
        sx = int(x * self._F比例)
        sy = int(y * self._F比例)
        sw = max(int(w * self._F比例), 1)
        sh = max(int(h * self._F比例), 1)
        self.setGeometry(sx, sy, sw, sh)
        self.update()

    def setSelected(self, sel):
        self._F选中 = sel
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            # 检查是否点中右下角调整大小手柄
            手柄区 = QRect(self.width() - self.手柄大小, self.height() - self.手柄大小,
                          self.手柄大小, self.手柄大小)
            if self._F选中 and 手柄区.contains(pos):
                self._F调整大小 = True
            else:
                self._F拖动偏移 = pos
            # 选中自己
            self._F画布.F选中图形(self)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._F调整大小:
            # 调整大小
            self._F终点 = self.pos() + pos
            self._F更新几何()
        elif self._F拖动偏移 and event.buttons() & Qt.MouseButton.LeftButton:
            parent = self.parentWidget()
            if parent:
                global_pos = event.globalPosition().toPoint()
                local_pos = parent.mapFromGlobal(global_pos)
                new_pos = local_pos - self._F拖动偏移
                dx = new_pos.x() - self.pos().x()
                dy = new_pos.y() - self.pos().y()
                self.move(new_pos)
                self._F起点 += QPoint(dx, dy)
                self._F终点 += QPoint(dx, dy)

    def mouseReleaseEvent(self, event):
        self._F拖动偏移 = None
        self._F调整大小 = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(self._F颜色, self._F粗))
        w = self.width()
        h = self.height()
        if self._F类型 == 'rect':
            painter.drawRect(0, 0, w-1, h-1)
        elif self._F类型 == 'ellipse':
            painter.drawEllipse(0, 0, w-1, h-1)
        elif self._F类型 == 'arrow':
            import math
            # 根据实际起点终点计算相对坐标
            ox = self._F起点.x() - self.x()
            oy = self._F起点.y() - self.y()
            ex = self._F终点.x() - self.x()
            ey = self._F终点.y() - self.y()
            p1 = QPoint(ox, oy)
            p2 = QPoint(ex, ey)
            painter.drawLine(p1, p2)
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            angle = math.atan2(dy, dx)
            al = 12
            aw = math.pi / 7
            ax1 = p2.x() - al * math.cos(angle - aw)
            ay1 = p2.y() - al * math.sin(angle - aw)
            ax2 = p2.x() - al * math.cos(angle + aw)
            ay2 = p2.y() - al * math.sin(angle + aw)
            painter.setBrush(self._F颜色)
            painter.drawPolygon([p2, QPoint(int(ax1), int(ay1)), QPoint(int(ax2), int(ay2))])
        # 选中时画虚线边框和右下角手柄
        if self._F选中:
            painter.setPen(QPen(QColor(0, 200, 255), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(0, 0, w-1, h-1)
            # 右下角调整手柄
            painter.setBrush(QColor(0, 200, 255))
            painter.drawRect(QRect(w - self.手柄大小, h - self.手柄大小,
                                   self.手柄大小, self.手柄大小))


class _C标注画布(QLabel):
    """可在截图上标注：矩形/椭圆/箭头/文字，全部浮动控件可拖动。"""
    工具_选择 = 'select'
    工具_矩形 = 'rect'
    工具_椭圆 = 'ellipse'
    工具_箭头 = 'arrow'
    工具_文字 = 'text'

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._F原图 = pixmap
        self.setStyleSheet("background: transparent; border-radius: 6px;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._F工具 = self.工具_选择
        self._F颜色 = QColor(255, 0, 0)
        self._F线条粗 = 2
        self._F图形控件列表 = []
        self._F临时图形 = None
        self._F起点 = None
        self._F文字控件列表 = []
        self._F选中图形 = None
        self._F调整回调 = None
        self._F调整中 = False
        self._F窗口拖拽起点 = None
        self._F工具切换回调 = None
        self._F调整起点 = None
        self._F原始尺寸 = None
        # 缩放：根据屏幕可用大小（考虑高DPI）
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry()
        dpr = screen.devicePixelRatio()
        # 屏幕逻辑尺寸
        最大宽 = int(screen_geo.width() * 0.7)
        最大高 = int(screen_geo.height() * 0.7)
        # pixmap 是物理像素，转逻辑像素
        逻辑宽 = pixmap.width() / dpr
        逻辑高 = pixmap.height() / dpr
        比例宽 = 最大宽 / 逻辑宽
        比例高 = 最大高 / 逻辑高
        self._F比例 = min(比例宽, 比例高, 1.0)
        sw = int(逻辑宽 * self._F比例)
        sh = int(逻辑高 * self._F比例)
        self.setFixedSize(sw, sh)
        # 缩放图片到逻辑尺寸
        self.setPixmap(pixmap.scaled(sw * dpr, sh * dpr, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
        self._F_dpr = dpr

    def _F屏幕到原图(self, pos):
        """屏幕坐标转原图坐标。"""
        return QPoint(int(pos.x() / self._F比例), int(pos.y() / self._F比例))

    def _F原图到屏幕(self, pos):
        """原图坐标转屏幕坐标。"""
        return QPoint(int(pos.x() * self._F比例), int(pos.y() * self._F比例))

    def F设置工具(self, 工具):
        self._F工具 = 工具
        self.F取消选中()
        if 工具 == self.工具_选择:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif 工具 == self.工具_文字:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def F选中图形(self, 图形):
        for w in self._F图形控件列表:
            w.setSelected(w is 图形)
        self._F选中图形 = 图形

    def F取消选中(self):
        for w in self._F图形控件列表:
            w.setSelected(False)
        self._F选中图形 = None

    def F设置颜色(self, 颜色):
        self._F颜色 = 颜色
        if self._F选中图形:
            self._F选中图形._F颜色 = 颜色
            self._F选中图形.update()

    def F撤销(self):
        # 先关闭正在编辑的文字框
        for child in self.findChildren(QLineEdit):
            if child.isVisible():
                child.deleteLater()
                return
        if self._F图形控件列表:
            w = self._F图形控件列表.pop()
            w.deleteLater()
        elif self._F文字控件列表:
            lbl = self._F文字控件列表.pop()
            lbl.deleteLater()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # 右下角 resize 手柄
        手柄区 = QRect(self.width() - 20, self.height() - 20, 20, 20)
        if 手柄区.contains(event.position().toPoint()):
            self._F调整中 = True
            self._F调整起点 = event.globalPosition().toPoint()
            self._F原始尺寸 = self.size()
            return
        # 选择模式下，在空白处按住拖拽移动窗口
        if self._F工具 == self.工具_选择:
            self._F窗口拖拽起点 = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        pos = self._F屏幕到原图(event.position().toPoint())
        self.F取消选中()

        if self._F工具 == self.工具_文字:
            self._F创建文字编辑器(pos)
            return

        if self._F工具 in (self.工具_矩形, self.工具_椭圆, self.工具_箭头):
            self._F起点 = pos
            self._F临时图形 = _C图形基类(self, pos, self._F颜色, self._F线条粗, self._F工具, self._F比例)
            self._F临时图形.show()

    def mouseMoveEvent(self, event):
        if self._F窗口拖拽起点 and event.buttons() & Qt.MouseButton.LeftButton and self._F工具 == self.工具_选择:
            self.window().move(event.globalPosition().toPoint() - self._F窗口拖拽起点)
            return
        if self._F调整中 and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._F调整起点
            new_w = max(200, self._F原始尺寸.width() + delta.x())
            new_h = max(150, self._F原始尺寸.height() + delta.y())
            self.setFixedSize(new_w, new_h)
            self.setPixmap(self._F原图.scaled(new_w, new_h, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
            self._F比例 = new_w / self._F原图.width()
            if self._F调整回调:
                self._F调整回调()
            return
        # 右下角 hover 光标
        手柄区 = QRect(self.width() - 20, self.height() - 20, 20, 20)
        if 手柄区.contains(event.position().toPoint()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.unsetCursor()
        if self._F起点 and self._F临时图形:
            pos = self._F屏幕到原图(event.position().toPoint())
            self._F临时图形.setEnd(pos)

    def mouseReleaseEvent(self, event):
        self._F窗口拖拽起点 = None
        if self._F调整中:
            self._F调整中 = False
            return
        if not self._F起点:
            return
        end = self._F屏幕到原图(event.position().toPoint())
        if (end - self._F起点).manhattanLength() > 5:
            self._F临时图形._F终点 = end
            self._F图形控件列表.append(self._F临时图形)
        else:
            self._F临时图形.deleteLater()
        self._F起点 = None
        self._F临时图形 = None
        self.F设置工具(self.工具_选择)
        if self._F工具切换回调:
            self._F工具切换回调('select')

    def mouseDoubleClickEvent(self, event):
        pos = self._F屏幕到原图(event.position().toPoint())
        for lbl in self._F文字控件列表:
            屏幕pos = self._F原图到屏幕(lbl.pos())
            if QRect(屏幕pos, lbl.size()).contains(event.position().toPoint()):
                self._F把标签变编辑器(lbl)
                return

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            if self._F临时图形:
                return
            if self._F选中图形:
                g = self._F选中图形
                if g in self._F图形控件列表:
                    self._F图形控件列表.remove(g)
                g.deleteLater()
                self._F选中图形 = None
            elif self._F图形控件列表:
                w = self._F图形控件列表.pop()
                w.deleteLater()
            elif self._F文字控件列表:
                lbl = self._F文字控件列表.pop()
                lbl.deleteLater()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.F取消选中()

    def _F创建文字编辑器(self, pos):
        屏幕pos = self._F原图到屏幕(pos)
        editor = QLineEdit(self)
        editor.setStyleSheet("background: transparent; color: red; border: 1px dashed blue; padding: 2px; selection-background-color: #0078d4;")
        editor.setGeometry(屏幕pos.x(), 屏幕pos.y(), 200, 28)
        editor.show()
        editor.setFocus()
        # 立即切回选择工具，按钮恢复
        if self._F工具切换回调:
            self._F工具切换回调('select')
        已完成 = [False]
        def 完成():
            if 已完成[0]:
                return
            已完成[0] = True
            text = editor.text().strip()
            editor_pos = editor.pos()
            editor.deleteLater()
            if text:
                self._F把编辑器变标签(text, editor_pos)
            p = self.parentWidget()
            while p and not hasattr(p, '_F切换工具'):
                p = p.parentWidget()
            if p:
                p._F切换工具('select')
        editor.editingFinished.connect(完成)

    def _F把编辑器变标签(self, text, 屏幕pos):
        lbl = QLabel(text, self)
        lbl.setStyleSheet(f"color: {self._F颜色.name()}; background: transparent; font-size: 14px;")
        lbl.setGeometry(屏幕pos.x(), 屏幕pos.y(), 200, 24)
        lbl.setCursor(Qt.CursorShape.SizeAllCursor)
        lbl.show()
        lbl._F文字 = text
        lbl._F颜色 = self._F颜色
        self._F文字控件列表.append(lbl)
        lbl.mousePressEvent = lambda e, l=lbl: self._F文字拖动开始(l, e)
        lbl.mouseMoveEvent = lambda e, l=lbl: self._F文字拖动(l, e)
        lbl.mouseReleaseEvent = lambda e: None

    def _F把标签变编辑器(self, lbl):
        text = lbl._F文字
        pos = lbl.pos()
        lbl.deleteLater()
        self._F文字控件列表.remove(lbl)
        editor = QLineEdit(self)
        editor.setText(text)
        editor.setStyleSheet("background: transparent; color: red; border: 1px dashed blue; padding: 2px;")
        editor.setGeometry(pos.x(), pos.y(), 200, 28)
        editor.show()
        editor.setFocus()
        editor.selectAll()
        已完成 = [False]
        def 完成():
            if 已完成[0]:
                return
            已完成[0] = True
            new_text = editor.text().strip()
            editor.deleteLater()
            if new_text:
                self._F把编辑器变标签(new_text, pos)
        editor.editingFinished.connect(完成)

    def _F文字拖动开始(self, lbl, event):
        if event.button() == Qt.MouseButton.LeftButton:
            lbl._F拖动偏移 = event.globalPosition().toPoint() - lbl.pos()
            lbl.raise_()

    def _F文字拖动(self, lbl, event):
        if hasattr(lbl, '_F拖动偏移') and event.buttons() & Qt.MouseButton.LeftButton:
            lbl.move(event.globalPosition().toPoint() - lbl._F拖动偏移)

    def F合成图片(self):
        result = self._F原图.copy()
        painter = QPainter(result)
        for w in self._F图形控件列表:
            painter.setPen(QPen(w._F颜色, w._F粗))
            import math
            x, y = w.pos().x(), w.pos().y()
            rw, rh = w.width(), w.height()
            ox = int(x / self._F比例)
            oy = int(y / self._F比例)
            rw_o = int(rw / self._F比例)
            rh_o = int(rh / self._F比例)
            if w._F类型 == 'rect':
                painter.drawRect(ox, oy, rw_o, rh_o)
            elif w._F类型 == 'ellipse':
                painter.drawEllipse(ox, oy, rw_o, rh_o)
            elif w._F类型 == 'arrow':
                p1 = QPoint(int(w._F起点.x()), int(w._F起点.y()))
                p2 = QPoint(int(w._F终点.x()), int(w._F终点.y()))
                painter.drawLine(p1, p2)
                dx = p2.x() - p1.x()
                dy = p2.y() - p1.y()
                angle = math.atan2(dy, dx)
                al = 12
                aw = math.pi / 7
                ax1 = p2.x() - al * math.cos(angle - aw)
                ay1 = p2.y() - al * math.sin(angle - aw)
                ax2 = p2.x() - al * math.cos(angle + aw)
                ay2 = p2.y() - al * math.sin(angle + aw)
                painter.setBrush(w._F颜色)
                painter.drawPolygon([p2, QPoint(int(ax1), int(ay1)), QPoint(int(ax2), int(ay2))])
        for lbl in self._F文字控件列表:
            painter.setPen(QPen(lbl._F颜色, 2))
            pos_o = lbl.pos()
            painter.drawText(QPoint(int(pos_o.x()/self._F比例), int(pos_o.y()/self._F比例)), lbl._F文字)
        painter.end()
        return result


class _C截图工具条(QObject):
    """截图预览：画布窗口 + 底部吸附按钮栏窗口。"""

    def __init__(self, pixmap, rect, parent=None):
        super().__init__(parent)
        self._F区域 = rect
        self._F画布窗口 = QWidget()
        self._F画布窗口.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window |
            Qt.WindowType.Tool
        )
        self._F画布窗口.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 画布 card
        card = QWidget(self._F画布窗口)
        card.setObjectName('popupCard')
        accent = (29, 233, 182)
        try:
            from 项目UI.界面样式 import get_stylesheet, get_current_theme_id, THEMES
            from 项目UI.弹窗样式 import add_green_glow, highlight_card_style
            theme_id = get_current_theme_id(self._F画布窗口)
            card.setStyleSheet(highlight_card_style(theme_id))
            add_green_glow(card, accent=QColor(*accent))
        except Exception:
            card.setStyleSheet(f"#popupCard {{ border: 4px solid rgb{accent}; border-radius: 12px; background: #2b2b2b; }}")

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._F画布 = _C标注画布(pixmap)
        lay.addWidget(self._F画布)

        outer = QVBoxLayout(self._F画布窗口)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(card)

        # 按钮栏窗口
        self._F按钮栏 = QWidget()
        self._F按钮栏.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window |
            Qt.WindowType.Tool
        )
        self._F按钮栏.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._F按钮栏.setStyleSheet("QWidget { background: #2b2b2b; border-radius: 8px; }")

        toolbar = QHBoxLayout(self._F按钮栏)
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(4)

        self._F按钮 = {}
        for key, label in [('select', '选择'), ('rect', '矩形'), ('ellipse', '椭圆'),
                           ('arrow', '箭头'), ('text', '文字')]:
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { padding: 2px 10px; border: 1px solid transparent; border-radius: 4px; color: #eee; }"
                "QPushButton:checked { background: rgb(29,233,182); color: black; font-weight: bold; }"
            )
            btn.clicked.connect(lambda checked, k=key: self._F切换工具(k))
            toolbar.addWidget(btn)
            self._F按钮[key] = btn
        self._F按钮['select'].setChecked(True)

        btn_undo = QPushButton('撤销')
        btn_undo.setStyleSheet("padding: 2px 10px; color: #eee;")
        btn_undo.clicked.connect(self._F画布.F撤销)
        toolbar.addWidget(btn_undo)

        toolbar.addSpacing(10)
        self._F颜色按钮 = []
        for rgb in [(255,0,0), (255,255,0), (0,255,0), (0,120,255), (255,255,255)]:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.setCheckable(True)
            btn.setStyleSheet(f"QPushButton {{ background: rgb{rgb}; border: 2px solid #888; border-radius: 12px; }}"
                              f"QPushButton:checked {{ border: 2px solid white; }}")
            btn.clicked.connect(lambda checked, c=rgb, b=btn: self._F切换颜色(c, b))
            toolbar.addWidget(btn)
            self._F颜色按钮.append(btn)
        self._F颜色按钮[0].setChecked(True)

        toolbar.addStretch()

        btn_save = QPushButton('保存')
        btn_copy = QPushButton('复制')
        btn_cancel = QPushButton('关闭')
        for b in (btn_save, btn_copy, btn_cancel):
            b.setMinimumWidth(60)
            b.setStyleSheet("padding: 2px 10px; color: #eee;")
        btn_save.clicked.connect(self._F保存)
        btn_copy.clicked.connect(self._F复制)
        btn_cancel.clicked.connect(self._F关闭)
        toolbar.addWidget(btn_save)
        toolbar.addWidget(btn_copy)
        toolbar.addWidget(btn_cancel)

        self._F按钮栏.adjustSize()

        # 定位：画布居中，按钮栏吸附在画布下方
        cw = self._F画布窗口
        cw.adjustSize()
        x = rect.x() + rect.width() // 2 - cw.width() // 2
        y = rect.y() + rect.height() + 10
        screen_geo = QGuiApplication.primaryScreen().availableGeometry()
        if y + cw.height() + self._F按钮栏.height() + 10 > screen_geo.bottom():
            y = rect.y() - cw.height() - self._F按钮栏.height() - 10
        cw.move(max(0, x), max(0, y))

        # 同步移动按钮栏
        self._F同步按钮栏位置()
        cw.moveEvent = self._F画布移动
        self._F拖拽起点 = None

        self._F画布._F调整回调 = self._F同步按钮栏位置
        self._F画布._F工具切换回调 = self._F切换工具
        cw.installEventFilter(self)
        self._F移动拖拽起点 = None

        cw.show()
        self._F按钮栏.show()

    def eventFilter(self, obj, event):
        # 在画布窗口空白区域拖拽移动
        if obj == self._F画布窗口:
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                # 不在画布上（在 card 边框区域）才开始移动
                child = self._F画布窗口.childAt(event.position().toPoint())
                if child is None or child == self._F画布:
                    self._F移动拖拽起点 = event.globalPosition().toPoint() - self._F画布窗口.frameGeometry().topLeft()
            elif event.type() == event.Type.MouseMove and self._F移动拖拽起点 and event.buttons() & Qt.MouseButton.LeftButton:
                self._F画布窗口.move(event.globalPosition().toPoint() - self._F移动拖拽起点)
            elif event.type() == event.Type.MouseButtonRelease:
                self._F移动拖拽起点 = None
        return False

    def _F同步按钮栏位置(self):
        cw = self._F画布窗口
        bw = self._F按钮栏
        bx = cw.x() + (cw.width() - bw.width()) // 2
        by = cw.y() + cw.height() + 8
        bw.move(max(0, bx), by)
        bw.raise_()

    def _F画布移动(self, event):
        self._F同步按钮栏位置()

    def _F切换工具(self, key):
        self._F画布.F设置工具(key)
        for k, btn in self._F按钮.items():
            btn.setChecked(k == key)

    def _F切换颜色(self, rgb, btn):
        self._F画布.F设置颜色(QColor(*rgb))
        for b in self._F颜色按钮:
            b.setChecked(b == btn)

    def _F保存(self):
        final = self._F画布.F合成图片()
        save_dir = os.path.join(os.path.expanduser('~'), 'Desktop', 'Super_ADB', '截图')
        os.makedirs(save_dir, exist_ok=True)
        name = datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.png'
        path = os.path.join(save_dir, name)
        final.save(path, 'PNG')
        self._F关闭()
        QMessageBox.information(None, '截图成功', f'已保存到:\n{path}')

    def _F复制(self):
        final = self._F画布.F合成图片()
        QGuiApplication.clipboard().setPixmap(final)
        self._F关闭()

    def _F关闭(self):
        self._F画布窗口.close()
        self._F按钮栏.close()


# ── Mac / Linux 全局热键 ──
_mac_monitors = []
_linux_dpy = None

def _parse_hotkey_unix(combo):
    """解析热键字符串，返回 (modifiers_set, key_char_or_name)。"""
    parts = [p.strip().lower() for p in combo.split('+') if p.strip()]
    mods = set()
    key = None
    for p in parts:
        if p in ('ctrl', 'control'):
            mods.add('ctrl')
        elif p == 'alt':
            mods.add('alt')
        elif p == 'shift':
            mods.add('shift')
        elif p == 'cmd':
            mods.add('cmd')
        elif p == 'win':
            mods.add('cmd')
        else:
            key = p
    return mods, key


def _register_hotkeys_unix():
    """Mac: PyObjC NSEvent; Linux: python-xlib XGrabKey。"""
    cfg = _load_hotkey_config()
    shot_key = cfg.get('hotkey_screenshot', '')
    rec_key = cfg.get('hotkey_recording', '')

    if _sys.platform == 'darwin':
        _register_hotkey_mac(shot_key, rec_key)
    else:
        _register_hotkey_linux(shot_key, rec_key)


def _register_hotkey_mac(shot_key, rec_key):
    """Mac: NSEvent 全局事件监听。"""
    global _mac_monitors
    try:
        from AppKit import NSEvent, NSKeyDownMask
        from Foundation import NSObject
    except ImportError:
        print('[快捷键] Mac 需要 PyObjC: pip install pyobjc')
        return

    _mac_monitors.clear()

    def _make_handler(cb):
        def handler(event):
            try:
                cb()
            except Exception:
                pass
        return handler

    for combo, cb in [(shot_key, _global_start_screenshot),
                      (rec_key, _global_start_recording)]:
        mods, key = _parse_hotkey_unix(combo)
        if not key:
            continue
        # keyCode: 字母 a=0, b=1, ..., z=25
        key_lower = key.lower()
        if len(key_lower) == 1 and 'a' <= key_lower <= 'z':
            key_code = ord(key_lower) - ord('a')
        elif len(key_lower) == 1 and '0' <= key_lower <= '9':
            key_code = ord(key_lower) - ord('0') + 18  # 数字键
        else:
            print(f'[快捷键] Mac 暂不支持 {key}')
            continue
        # 修饰键 flags
        flags = 0
        if 'ctrl' in mods:
            flags |= (1 << 20)  # NSControlKeyMask
        if 'alt' in mods:
            flags |= (1 << 19)  # NSAlternateKeyMask
        if 'shift' in mods:
            flags |= (1 << 17)  # NSShiftKeyMask
        if 'cmd' in mods:
            flags |= (1 << 23)  # NSCommandKeyMask

        monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, _make_handler(cb))
        _mac_monitors.append(monitor)
        print(f'[快捷键] Mac 热键已注册: {combo}')


def _register_hotkey_linux(shot_key, rec_key):
    """Linux: Xlib XGrabKey。"""
    global _linux_dpy
    try:
        from Xlib.display import Display
        from Xlib import X
    except ImportError:
        print('[快捷键] Linux 需要 python-xlib: pip install python-xlib')
        return

    try:
        dpy = Display()
        root = dpy.screen().root

        # 修饰键映射
        def _mod_mask(mods):
            m = 0
            if 'ctrl' in mods:
                m |= X.ControlMask
            if 'alt' in mods:
                m |= X.Mod1Mask  # Alt 通常是 Mod1
            if 'shift' in mods:
                m |= X.ShiftMask
            if 'cmd' in mods or 'win' in mods:
                m |= X.Mod4Mask
            return m

        for combo, cb in [(shot_key, _global_start_screenshot),
                          (rec_key, _global_start_recording)]:
            mods, key = _parse_hotkey_unix(combo)
            if not key:
                continue
            # X11 keysym: 字母和数字直接用
            if len(key) == 1:
                ks = ord(key.lower())
            elif key.startswith('f') and key[1:].isdigit():
                # F1=0xFFBE ... F35=0xFFE2
                ks = 0xFFBE + int(key[1:]) - 1
            else:
                print(f'[快捷键] Linux 暂不支持 {key}')
                continue

            keycode = dpy.keysym_to_keycode(ks)
            mod_mask = _mod_mask(mods)
            root.grab_key(keycode, mod_mask, True,
                          X.GrabModeAsync, X.GrabModeAsync)
            print(f'[快捷键] Linux 热键已注册: {combo} (keycode={keycode})')

        dpy.flush()
        _linux_dpy = dpy
    except Exception as e:
        print(f'[快捷键] Linux 注册失败: {e}')
