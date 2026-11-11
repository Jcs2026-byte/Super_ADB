# -*- coding: utf-8 -*-
"""
自绘透明外壳对话框
==================
把「无边框 + 透明背景 + 自绘圆角背景/发光 + 自定义标题栏 + 拖拽/边缘缩放」
这套在关于 / 环境配置弹窗上已验证不闪白的外壳逻辑抽成可复用基类。

背景：原生不透明 QDialog 首次映射到屏幕时，Qt 首个 paintEvent 尚未绘制，
原生/DWM 合成表面先以默认白上屏，表现为整块客户区纯白（先透明 → 白 → 深色）。
WA_TranslucentBackground 分层窗口没有这层不透明默认表面，首帧未绘制时只是透出
后方，paintEvent 画出深色背景后即深色，不会出现整块白块。

子类接入方式
------------
1. ``class 某对话框(自绘外壳对话框)``；
2. ``super().__init__(parent, 标题='...', 最小尺寸=(620,480))``；
3. 业务控件加到 ``self.外壳内容布局``（或沿用既有 ``_create_popup_card(self, ...)``
   挂到自身布局）；
4. 主题切换时调 ``self.apply_theme(theme_id)``；
5. 若有 ``setGeometry`` 固定位置的内层 card，重写 ``resizeEvent`` 同步其几何。

注意
----
- 外发光/圆角背景/边框都在 ``paintEvent`` 直绘，不挂 ``QGraphicsDropShadowEffect``
  （WA_TranslucentBackground 下 effect 离屏缓冲会缓存旧帧，主题切换后不刷新）。
- 原生标题栏已去掉，窗口标题只显示在自绘标题栏的 ``self._标题标签`` 上。
"""
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QPainter, QColor, QIcon, QPen, QBrush, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSizePolicy,
)

from 项目UI.界面样式 import FONT_FAMILY, THEMES, DEFAULT_THEME, _parse_rgb, get_current_theme_id
from 项目UI.弹窗样式 import 无边框缩放Mixin


class 自绘外壳对话框(QDialog, 无边框缩放Mixin):
    """透明自绘外壳：标题栏 + 圆角背景/发光 + 拖拽/缩放，主题可切换。"""

    def __init__(self, parent=None, 标题='', 最小尺寸=(520, 400),
                 显示最小化=False, 显示最大化=False, 圆角=14):
        super().__init__(parent)
        # 无边框 + 分层透明背景：绕开原生不透明窗口的首帧默认白表面
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(*最小尺寸)
        self.setWindowTitle(标题)

        # paintEvent 颜色兜底（apply_theme 会按当前主题覆盖；这里先按默认主题解析，
        # 避免硬编码某套主题的 accent，导致首帧边框/发光色与当前主题不符）。
        _t0 = THEMES[DEFAULT_THEME]
        _r0, _g0, _b0 = _parse_rgb(_t0['accent'])
        self._bg_window = QColor(_t0['bg_window'])
        self._bg_border = QColor(_r0, _g0, _b0)
        self._bg_radius = 圆角
        # 外壳默认不画 accent 边框（边框交内层 card 承担）；需要外壳自身边框时置 True
        self._外壳画边框 = False

        # ── 主布局 ──────────────────────────────────────────────────
        self._主布局 = QVBoxLayout(self)
        self._主布局.setContentsMargins(0, 0, 0, 0)
        self._主布局.setSpacing(0)

        # ── 自定义标题栏 ────────────────────────────────────────────
        self._标题栏布局 = QHBoxLayout()
        self._标题栏布局.setContentsMargins(14, 10, 10, 10)
        self._标题栏布局.setSpacing(6)

        self._标题标签 = QLabel(标题)
        self._标题标签.setObjectName('shellTitle')
        self._标题标签.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._标题栏布局.addWidget(self._标题标签)

        self._最小化按钮 = None
        if 显示最小化:
            self._最小化按钮 = self._建标题按钮('—', 'minBtn')
            self._最小化按钮.clicked.connect(self.showMinimized)
            self._标题栏布局.addWidget(self._最小化按钮)

        self._最大化按钮 = None
        if 显示最大化:
            self._最大化按钮 = self._建标题按钮('□', 'maxBtn')
            self._最大化按钮.clicked.connect(self._切换最大化)
            self._标题栏布局.addWidget(self._最大化按钮)

        self._关闭按钮 = self._建标题按钮('✕', 'closeBtn')
        self._关闭按钮.clicked.connect(self.reject)
        self._标题栏布局.addWidget(self._关闭按钮)

        self._标题栏控件 = QWidget()
        self._标题栏控件.setObjectName('shellTitleBar')
        self._标题栏控件.setLayout(self._标题栏布局)
        self._主布局.addWidget(self._标题栏控件)

        # 业务控件直接挂到主布局（占标题栏下方剩余空间）。既有
        # ``_create_popup_card`` 会复用 ``dialog.layout()``，不再新建外层布局。
        self.外壳内容布局 = self._主布局

        # 拖拽状态（边缘缩放由 Mixin 接管）
        self._dragging = False
        self._drag_pos = QPoint()

        # 缩放状态兜底：Mixin._初始化缩放 会在子控件建完后再给子控件装
        # 事件过滤器；这里先置默认值，避免子类未调初始化外壳缩放时，
        # mouseMove/mouseRelease 读到不存在的 _缩放中等属性而抛 AttributeError。
        self._缩放中 = False
        self._缩放方向 = None
        self._缩放起点 = QPoint()
        self._缩放原几何 = QRect()
        self._缩放边距 = 8
        # 首次 show 时幂等开启鼠标追踪 + 给子控件装缩放事件过滤器（见 showEvent）
        self._缩放已初始化 = False
        # 嵌入标签页/布局内的子对话框：不画独立背景/发光/边框，不参与顶层居中，
        # 背景由父面板承担，避免与父面板、内层卡片形成嵌套双框或错位叠加。
        self._embedded = False

        # 兜底：构造即给标题栏按钮挂局部样式（apply_theme 会按主题再刷新），
        # 否则直接继承外壳的子类按钮会全吃全局 QPushButton 规则，符号被 padding/背景压掉。
        self._刷新标题栏按钮样式(THEMES[DEFAULT_THEME])
        # 构造即按父窗口当前主题刷新外壳背景/边框/发光色，避免首帧停留在默认主题兜底色。
        # 注意：这里只能调非虚的 _F刷新外壳自绘颜色，不能调 apply_theme——构造期子类
        # 的 __init__ 尚未创建业务控件，虚方法派发到子类 apply_theme 会读到不存在的
        # self.card 等属性而抛 AttributeError（如 WiFi对话框）。业务控件的主题刷新
        # 由子类自己在 __init__ 里做，运行期切换由主窗口传播。
        self._F刷新外壳自绘颜色(None)

    # ------------------------------------------------------------------
    # 标题栏按钮
    # ------------------------------------------------------------------
    def _建标题按钮(self, 文本, 对象名):
        btn = QPushButton(文本)
        btn.setObjectName(对象名)
        btn.setFixedSize(28, 22)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _切换最大化(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def setWindowTitle(self, 标题):
        """同步原生窗口标题与自绘标题栏标签。"""
        super().setWindowTitle(标题)
        if hasattr(self, '_标题标签'):
            self._标题标签.setText(标题)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def _解析主题(self, theme_id):
        """优先参数，其次父窗口链 _current_theme，再读持久化配置，最后 DEFAULT_THEME。"""
        if isinstance(theme_id, str) and theme_id in THEMES:
            return theme_id
        p = self.parent()
        cur = getattr(p, '_current_theme', None)
        if isinstance(cur, str) and cur in THEMES:
            return cur
        try:
            return get_current_theme_id(self)
        except Exception:
            return DEFAULT_THEME

    def _刷新标题栏按钮样式(self, t):
        """给标题栏按钮各自挂局部样式表（优先于继承的全局 QPushButton 规则）。"""
        次色 = t['text_disabled']
        标题色 = t['text_primary']
        普通 = (
            "QPushButton{background:transparent; color:%s; border:none; border-radius:6px;"
            "padding:0; font:14px 'Segoe UI','%s';}" % (次色, FONT_FAMILY)
        )
        for btn in (self._最小化按钮, self._最大化按钮):
            if btn is not None:
                btn.setStyleSheet(
                    普通 + "QPushButton:hover{background:%s; color:%s;}"
                    % (t['bg_button'], 标题色))
        if self._关闭按钮 is not None:
            self._关闭按钮.setStyleSheet(
                "QPushButton{background:transparent; color:%s; border:none; border-radius:6px;"
                "padding:0; font:14px 'Segoe UI','%s';}" % (次色, FONT_FAMILY)
                + "QPushButton:hover{background:#e81123; color:#ffffff;}"
                  "QPushButton:pressed{background:#b0091a; color:#ffffff;}")

    def _F刷新外壳自绘颜色(self, theme_id=None):
        """按主题重算外壳背景/边框/发光色与标题栏配色。

        抽成独立方法：主窗口传播主题时可对所有外壳弹窗强制调用，即使子类
        ``apply_theme`` 未调 super，外壳自绘颜色也能跟随主题。
        """
        tid = self._解析主题(theme_id)
        self._主题id = tid
        t = THEMES.get(tid, THEMES[DEFAULT_THEME])
        r, g, b = _parse_rgb(t['accent'])
        self._bg_window = QColor(t['bg_window'])
        self._bg_border = QColor(r, g, b)

        self._标题标签.setStyleSheet(
            f"color: {t['accent']}; font: 700 10pt '{FONT_FAMILY}'; background: transparent; border: none;")
        self._刷新标题栏按钮样式(t)
        self.update()

    def apply_theme(self, theme_id=None):
        """按主题刷新外壳；子类覆盖时先调 super()，否则外壳颜色由主窗口兜底重刷。"""
        self._F刷新外壳自绘颜色(theme_id)
        self.repaint()

    # ------------------------------------------------------------------
    # 自绘背景 / 发光 / 边框
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        # 嵌入标签页/布局内：不画外壳背景/发光/边框，背景由父面板承担。
        if getattr(self, '_embedded', False) or not self.isWindow():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        r = self._bg_radius
        border_c = self._bg_border

        # 外发光：多层同心圆角矩形模拟模糊（由外向内，透明度递增）
        发光层数 = 6
        for i in range(发光层数, 0, -1):
            inset = 4 - i
            glow_rect = QPainterPath()
            glow_rect.addRoundedRect(
                inset, inset, rect.width() - inset * 2, rect.height() - inset * 2,
                r + (发光层数 - i), r + (发光层数 - i))
            alpha = int(8 + (40 * (1 - i / 发光层数)))
            painter.fillPath(glow_rect, QBrush(
                QColor(border_c.red(), border_c.green(), border_c.blue(), alpha)))

        # 圆角背景
        bg = QPainterPath()
        bg.addRoundedRect(4, 4, rect.width() - 8, rect.height() - 8, r, r)
        painter.fillPath(bg, QBrush(self._bg_window))

        # 边框（可选；默认交内层 card）
        if self._外壳画边框:
            pen = QPen(border_c, 4)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(bg)
        painter.end()
        super().paintEvent(event)

    # ------------------------------------------------------------------
    # 拖拽 + 边缘缩放
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if self._缩放按下处理(event):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._缩放移动处理(event):
            return
        if self._dragging and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._缩放释放处理(event):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()

    def resizeEvent(self, event):
        """钩子：子类若有 setGeometry 固定位置的内层 card，在此同步几何。"""
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示时（子控件已全部创建、父级 QSS 已就位）幂等开启边缘缩放：
        # 开鼠标追踪 + 给子控件装事件过滤器。子类无需再手动调 初始化外壳缩放。
        if not self._缩放已初始化:
            self._初始化缩放(边距=8)
            self._缩放已初始化 = True
        # 首帧再按当前主题刷一次外壳自绘颜色/标题色：构造期 _F刷新 之后子类还会
        # setStyleSheet 全局 QSS，真实平台 polish 时标题局部色可能被类型选择器压回
        # 默认；首显示时父级 QSS 已落地，这里重刷一次确保标题/边框不残留默认浅色。
        if not getattr(self, '_首帧外壳已刷', False):
            self._首帧外壳已刷 = True
            if not getattr(self, '_embedded', False) and self.isWindow():
                self._F刷新外壳自绘颜色(None)
        # 相对父窗口居中（仅独立顶层窗口；嵌入标签页/布局内的子对话框
        # 由父布局管理几何，不能 move 居中，否则会覆盖布局位置导致错位叠加）
        if self.isWindow() and self.parent() is not None:
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.center().x() - self.width() // 2,
                parent_geo.center().y() - self.height() // 2,
            )

    def 初始化外壳缩放(self, 边距=8):
        """所有子控件创建完毕后调用（幂等），开启边缘缩放与鼠标追踪。"""
        self._初始化缩放(边距=边距)
