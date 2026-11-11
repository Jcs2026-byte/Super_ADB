# -*- coding: utf-8 -*-
"""
对话框基类
==========
所有弹窗的统一基类，集中处理：
- 透明自绘外壳（无边框 + 分层背景 + 自绘圆角背景/发光 + 自定义标题栏 + 拖拽/缩放）
- 窗口图标（:/Super_ADB.png）
- 主题样式（get_stylesheet + 自动跟随当前主题）
- 主题切换（apply_theme，子类可覆盖）

子类只需关注业务布局，不再重复写图标/样式样板。

用法：
    from 项目UI.对话框基类 import 对话框基类

    class 证书安装对话框(对话框基类):
        def __init__(self, adb, 获取序列号, parent=None):
            super().__init__(parent, 标题='证书安装', 最小尺寸=(620, 480))
            # 只写业务布局...
"""
from PySide6.QtGui import QIcon, QColor
from PySide6.QtWidgets import QDialog  # noqa: F401  保留给子类类型注解

try:
    from 项目UI import png_rc  # noqa: F401
except ModuleNotFoundError:
    pass

from 项目UI.界面样式 import get_stylesheet, get_current_theme_id, THEMES, DEFAULT_THEME, _parse_rgb
from 项目UI.透明外壳对话框 import 自绘外壳对话框


class 对话框基类(自绘外壳对话框):
    """弹窗基类：透明自绘外壳 + 图标、样式、主题切换。"""

    def __init__(self, parent=None, 标题='', 最小尺寸=(520, 400), 发光=True,
                 显示最小化=False, 显示最大化=False):
        # 发光参数保留兼容旧调用；外壳发光由 paintEvent 直绘，不再挂
        # QGraphicsDropShadowEffect（分层透明窗口下 effect 离屏缓冲会缓存旧帧）。
        super().__init__(parent, 标题=标题, 最小尺寸=最小尺寸,
                         显示最小化=显示最小化, 显示最大化=显示最大化)
        self.setWindowIcon(QIcon(':/Super_ADB.png'))
        self._主题id = get_current_theme_id(self)
        self._刷新外壳颜色()
        self.setStyleSheet(get_stylesheet(self._主题id))

    def _刷新外壳颜色(self):
        """按当前主题写外壳自绘颜色成员 + 标题栏配色。"""
        t = THEMES.get(self._主题id, THEMES[DEFAULT_THEME])
        r, g, b = _parse_rgb(t['accent'])
        self._bg_window = QColor(t['bg_window'])
        self._bg_border = QColor(r, g, b)
        self._标题标签.setStyleSheet(
            f"color: {t['text_primary']}; font: 700 10pt 'Segoe UI';"
            f"background: transparent; border: none;")
        self._刷新标题栏按钮样式(t)

    def apply_theme(self, theme_id):
        """主题切换时刷新外壳颜色与子控件样式。子类覆盖时先调 super()。"""
        if theme_id not in THEMES:
            return
        self._主题id = theme_id
        self._刷新外壳颜色()
        self.setStyleSheet(get_stylesheet(theme_id))
