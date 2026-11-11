# -*- coding: utf-8 -*-
"""
弹窗高亮边框样式
================
统一给项目中的自定义弹窗/独立窗口加上青绿色高亮边框 + 外发光，
并提供可在多个弹窗复用的拖拽区控件 ``拖拽区域``。

运行期主题切换
--------------
本模块的所有颜色都可以由调用方传入 ``theme_id``（来自 ``界面样式.THEMES`` 的 key），
并通过 ``apply_theme()`` 同步刷新。默认 ``dark_teal`` 与 ``界面样式.DEFAULT_THEME`` 一致。
"""

from PySide6.QtCore import (
    Qt, Signal, QPoint, QCoreApplication, QEvent, QRect, QObject, QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPolygon, QImage, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QLabel,
    QFileDialog,
    QWidget,
    QVBoxLayout,
)

import sys

from 项目UI.界面样式 import (
    FONT_FAMILY,
    THEMES,
    DEFAULT_THEME,
)


def _禁用窗口淡入过渡(dlg):
    """Windows：关闭该窗口的 DWM 过渡/淡入动画。

    录屏实证：弹窗映射上屏的瞬间，DWM 淡入动画会先合成一帧「尚未绘制」
    的窗口后缓冲 —— 表现为整片半透明白、桌面从底下透出，等 Qt 画完才变
    深色。关掉过渡动画后窗口直接以最终状态出现，不再有半透明白阶段。
    DWMWA_TRANSITIONS_FORCEDISABLED = 3。非 Windows 直接返回。
    """
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        hwnd = int(dlg.winId())
        if not hwnd:
            return
        # Win32 BOOL 是 4 字节 int：必须用 c_int 而不是 c_bool（1 字节）。
        # 旧实现传 c_bool，cbAttribute=1 与 DWM 期望的 4 字节不符，Set 返回
        # E_INVALIDARG(0x80070057) 被 except 静默吞掉，淡入过渡从未被禁用，
        # 弹窗首帧仍先播半透明淡入（实测 c_int 后 Set 返回 S_OK）。
        enable = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 3, ctypes.byref(enable), ctypes.sizeof(enable))
    except Exception:
        pass


def _预热首帧(dlg):
    """show/exec 之前调用：创建原生窗口 + 离屏预热首帧（不含 DWM 处理）。

    grab() 离屏渲染一帧，把 style polish、QSS 解析、布局计算全部预热，
    让随后的真实首帧绘制只剩纯 blit。repaint() 则把当前（已 polish 的）
    深色背景直接画进窗口真实后缓冲，避免映射瞬间后缓冲还是未绘制的默认白。
    供 exec 模态弹窗与全局过滤器复用。
    """
    try:
        dlg.winId()          # 强制创建原生窗口（此时尚未映射，不触发淡入）
        dlg.grab()           # 离屏预热：跑完 polish + QSS 解析 + 布局
        dlg.repaint()        # 同步绘制真实后缓冲，抢在首次 DWM 合成前填深
    except Exception:
        pass


def 无闪预热弹窗(dlg):
    """show/exec 之前调用：创建原生窗口 + 预热首帧 + 关闭 DWM 淡入。

    与全局过滤器 ``首帧防闪过滤器`` 共用同一套底层步骤；模态弹窗（exec）
    在 exec 前调本函数即可。
    """
    _预热首帧(dlg)
    _禁用窗口淡入过渡(dlg)


def 无闪显示弹窗(dlg):
    """显示弹窗并消除 Windows / DWM 首帧白闪（仅 Windows 有此现象）。

    根因（录屏实证）：弹窗刚映射上屏时，DWM 的窗口淡入动画会先合成一帧
    「尚未绘制」的窗口后缓冲 —— 表现为整片半透明白、桌面从底下透出，等
    Qt 画完第一帧才变深色。首帧绘制越慢（QSS 解析 + 布局 + 大控件），白帧
    停留越久、越容易被肉眼捕捉，所以同一弹窗「有时闪有时不闪」，负载高时
    更明显。调色板 / 窗口类背景刷都改不到这一层：白来自后缓冲的初始内容，
    不是原生擦除色；grab() 只渲染到独立位图、填不进窗口真实后缓冲。

    对策（三者配合）：
    1. 无闪预热弹窗：grab 预热 polish + QSS + 布局，并关闭 DWM 淡入；
    2. show() 后立刻 repaint() 同步绘制真实后缓冲，抢在首次合成前；
    3. raise + activateWindow 保持原有前置/焦点行为。
    透明背景弹窗同样适用：淡入关闭后内容直接出现，不再渐变。
    """
    无闪预热弹窗(dlg)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    try:
        dlg.repaint()        # 映射后立即同步绘制真实后缓冲，压掉白帧
    except Exception:
        pass


# ----------------------------------------------------------------------
# 全局首帧防闪过滤器（装到 QApplication）
# ----------------------------------------------------------------------
# 已处理过的顶层窗口身份集合：避免同一窗口 show/hide 反复预热、重复关 DWM。
# 存 Python 对象弱引用更稳妥，但顶层弹窗生命周期通常与会话一致；这里用
# id() 并在窗口 destroyed 时清理，避免长期残留。
_已处理窗口id = set()


def _F是否跳过防闪(win):
    """判断该顶层窗口是否应跳过首帧防闪处理。

    跳过规则：
    - 非 Windows（DWM 淡入是 Windows 专有现象，其他平台不处理）；
    - 透明背景窗口（WA_TranslucentBackground）：本身没有「先白后画」的
      不透明后缓冲，无线调试 / 关于 / 环境配置 / 截图覆盖层等保持原样；
    - 工具提示、菜单、弹窗类原生浮层（Qt 自己管理其出现动画）；
    - 已被处理过的窗口（复用 hide/show 的弹窗）。
    """
    if sys.platform != 'win32':
        return True
    if not isinstance(win, QWidget):
        return True
    # 内嵌子控件不是顶层窗口，不做窗口级预热（isWindow() 才是顶层判据，
    # 不能用 parent() is None：带 parent 的 Dialog 仍是顶层窗口）。
    if not win.isWindow():
        return True
    if win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
        return True
    # 窗口类型是枚举值（Dialog=3 / Popup=9 / ToolTip=13 / SplashScreen=15），
    # 不是位掩码，必须用 windowType() 精确比较，不能用 & 位与（会误命中）。
    wtype = win.windowType()
    if wtype in (Qt.WindowType.ToolTip, Qt.WindowType.Popup,
                 Qt.WindowType.SplashScreen):
        return True
    if id(win) in _已处理窗口id:
        return True
    return False


def _F递归开自动填充(w):
    """递归把不透明子孙控件的背景自动填充打开。

    实测：铺满弹窗的 card、QPlainTextEdit 的 viewport 这类容器，在窗口
    polish 阶段 autoFillBackground 会被 Qt 重置回 False；此时调色板虽已是
    深色，但 autoFill 关闭时首帧未绘制阶段不刷底色，露出系统默认白（白块
    主要落在这些面积最大的子层上，而非弹窗本体）。Show 分支在 polish 完成、
    即将映射上屏前最后一刻递归兜底强制开启。带 WA_TranslucentBackground 的
    子控件跳过，不影响透明自绘浮层。
    """
    try:
        if isinstance(w, QWidget) and not w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            w.setAutoFillBackground(True)
    except Exception:
        pass
    for ch in getattr(w, 'children', lambda: [])():
        _F递归开自动填充(ch)


def _F执行防闪(win):
    """对一个未处理过的不透明顶层窗口执行预热 + 关 DWM 淡入 + 背景自动填充。"""
    _预热首帧(win)
    _禁用窗口淡入过渡(win)
    try:
        # 弹窗自身自动填充背景：不开时 Qt 不在首帧擦除背景，backing store 保留
        # 系统默认白（最小复现实测首帧 RGB 255,255,255）；开启后首帧原生擦除
        # 阶段即用调色板 Window 深色填充。属性在窗口存活期保留，复用重开仍有效。
        win.setAutoFillBackground(True)
        # 递归兜底：card / viewport 等子容器在 polish 阶段 autoFill 会被重置，
        # 这里最后一刻再强制打开，压掉子层首帧白块。
        _F递归开自动填充(win)
    except Exception:
        pass
    _已处理窗口id.add(id(win))
    try:
        win.destroyed.connect(lambda _obj=None, _k=id(win): _已处理窗口id.discard(_k))
    except Exception:
        pass


class 首帧防闪过滤器(QObject):
    """装到 QApplication 的全局事件过滤器：自动消除顶层弹窗首帧白闪。

    背景：逐个弹窗改 show/exec 调用点既啰嗦又会漏掉以后新增的弹窗。本过滤器
    统一在事件层拦截顶层窗口的显示流程：
    - ``Polish`` 事件（窗口样式即将生效、尚未映射）：对未处理过的不透明顶层
      窗口做离屏预热首帧；
    - ``Show`` 事件（映射上屏前）：关闭该窗口的 DWM 淡入动画；
    - ``Show`` 之后由 ``DynamicPropertyChange``/映射后立即 repaint 同步绘制真实
      后缓冲，抢在 DWM 首次合成之前。

    透明背景窗口、工具提示 / 菜单 / 启动图、非 Windows 平台自动跳过，不受
    影响。用法（main() 内 QApplication 创建后）::

        app.installEventFilter(首帧防闪过滤器(app))
    """

    def eventFilter(self, obj, event):
        # 防御：个别场景绑定层会把非 QObject 传入 watched（PYSIDE-3143 变体）
        if not isinstance(obj, QWidget):
            return False
        try:
            etype = event.type()
        except Exception:
            return False
        if etype in (QEvent.Type.Polish, QEvent.Type.Show):
            # 只处理顶层窗口；内嵌子控件不做任何窗口级处理。
            # 注意：不能用 parent() is None 判断顶层——带 parent 的 QDialog
            # 仍是独立顶层窗口（isWindow()=True），用 parent 判断会把这类
            # 弹窗误当成内嵌子控件跳过预热，首帧直接闪白（实测终端弹窗纯白）。
            if not obj.isWindow():
                return False
            复用中 = id(obj) in _已处理窗口id
            if _F是否跳过防闪(obj) and not 复用中:
                # 透明浮层 / 工具提示 / 非顶层 / 非 Windows：保持原样不动。
                # 复用窗口例外：已在 _已处理窗口id 中，走到下面的兜底重绘。
                return False
            if etype == QEvent.Type.Polish:
                # 样式 polish 前先预热：跑完 QSS 解析 + 布局，避免首帧卡住。
                # 复用窗口已预热过，不重复。
                if not 复用中:
                    try:
                        obj.winId()
                        obj.grab()
                    except Exception:
                        pass
            elif etype == QEvent.Type.Show:
                if not 复用中:
                    _F执行防闪(obj)
                # showEvent 派发早于 native 窗口映射，此时 repaint 不保证写进
                # 真实后缓冲；先同步重绘一次，再排到上屏后的事件循环首轮补一次，
                # 压住残留的未绘制白帧。receiver 传 obj，窗口销毁时定时器自动取消。
                try:
                    obj.repaint()
                    QTimer.singleShot(0, obj, obj.repaint)
                except Exception:
                    pass
        return super().eventFilter(obj, event)


# ----------------------------------------------------------------------
# 魔法数字常量（集中管理，避免散落硬编码）
# ----------------------------------------------------------------------
发光默认模糊半径 = 24
发光默认透明度 = 200
发光模糊微差偏移 = 2          # rebuild_glow 中 blur_radius - 2 + hash → 22~25
发光颜色哈希掩码 = 0x03       # 取低 2 位，得到 0~3 的微差
二次踢延迟毫秒 = 150          # _post_glow_kick 延迟二次 nudge
分层窗口闪烁透明值 = 254       # SetLayeredWindowAttributes alpha flicker
分层窗口属性标志 = 0x02        # LWA_ALPHA
拖拽区最低高度 = 72
拖拽区底色透明度 = 30          # accent_low ~12%
拖拽区悬停透明度 = 90          # accent_mid ~35%（预留）


# ----------------------------------------------------------------------
# 发光控件注册表（优化项4：替代全树 findChildren 扫描）
# ----------------------------------------------------------------------
发光控件注册表 = []


def _注册发光控件(控件):
    """把挂过 add_green_glow 的控件登记到注册表，销毁时自动移除。"""
    if 控件 not in 发光控件注册表:
        发光控件注册表.append(控件)

        def _清理(_=None):
            try:
                发光控件注册表.remove(控件)
            except (ValueError, RuntimeError):
                pass

        控件.destroyed.connect(_清理)


def 重建所有发光效果(accent_rgb):
    """重建注册表中所有发光控件的 DropShadow，无需全树扫描。

    替代旧版 ``_rebuild_all_glow(root_widget, accent_rgb)`` 的
    ``findChildren(QWidget)`` 全树遍历——时间复杂度从 O(N) 降到
    O(G)（G 为实际挂过发光的控件数，通常个位数）。
    """
    for 控件 in list(发光控件注册表):
        try:
            rebuild_glow(控件, accent_rgb)
        except Exception as e:
            print(f'[发光] 重建失败: {e!r}')


# ----------------------------------------------------------------------
# 默认主题高亮样式（兼容旧调用）
# ----------------------------------------------------------------------
ACCENT = QColor(29, 233, 182)
ACCENT_CSS = 'rgb(29,233,182)'

# 卡片容器样式：深背景 + 青绿高亮边框 + 圆角
HIGHLIGHT_CARD_STYLE = """
    #popupCard {
        background-color: #2d2d2d;
        border: 4px solid rgb(29,233,182);
        border-radius: 12px;
    }
    QLabel {
        background: transparent;
        border: none;
        color: #e0e0e0;
    }
"""


def highlight_card_style(theme_id):
    """按主题生成高亮卡片样式（背景/边框/圆角 + 卡片内 QLabel 文字色）。

    硬编码的 ``HIGHLIGHT_CARD_STYLE`` 里 ``QLabel{color:#e0e0e0}`` 只适配深色
    主题；浅色主题下卡片背景变白、文字仍是白色 → 直接糊掉。这里按主题生成，
    浅色主题用深文字、深色主题维持原浅文字，边框用主题 accent。
    """
    t = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
    accent = t['accent']
    light = t['bg_window'].lower() in ('#f5f5f5', '#ffffff', '#fff', '#fafafa',
                                       '#f0f0f0', '#fbfbfb', '#fcfcfc')
    if light:
        label_color = t['text_primary']
    else:
        label_color = '#e0e0e0'
    return f"""
    #popupCard {{
        background-color: {t['bg_button']};
        border: 4px solid {accent};
        border-radius: 12px;
    }}
    QLabel {{
        background: transparent;
        border: none;
        color: {label_color};
    }}
"""


def _create_popup_card(dialog, theme_id, margins=(10, 10, 10, 10),
                       card_style=None, glow=True):
    """弹窗统一高亮边框卡片工厂：4px 主题色边框圆角卡片 + 外发光。

    抽出各弹窗（时间戳 / 哈希校验 / WiFi / 证书安装 / 修改时间 /
    设备信息 / 投屏 / scrcpy 设置 / 哈希上下文菜单 / JSON 工具 /
    应用性能监控 / Monkey 压测等）完全一致的样板代码：
    建 card → setObjectName('popupCard') → 挂卡片样式 → 建 dialog
    主布局并挂 card → 挂主题色外发光。

    Parameters
    ----------
    dialog : QWidget
        弹窗本体；卡片挂为其子控件并加入其 QVBoxLayout 主布局。
    theme_id : str
        主题 id（``界面样式.THEMES`` 的 key）。
    margins : tuple[int, int, int, int]
        dialog 主布局内容边距，默认 (10, 10, 10, 10)。
    card_style : str | None
        自定义卡片 QSS；None 时用 ``highlight_card_style(theme_id)``。
    glow : bool
        是否挂主题色外发光（默认 True）。

    Returns
    -------
    tuple[QWidget, QVBoxLayout]
        ``(card, dialog 主布局)``；弹窗内部控件直接在 card 上建子布局即可。
    """
    card = QWidget(dialog)
    card.setObjectName('popupCard')
    card.setStyleSheet(card_style or highlight_card_style(theme_id))
    if glow:
        accent = THEMES.get(theme_id, THEMES[DEFAULT_THEME])['accent']
        add_green_glow(card, accent=QColor(accent))
    # 复用弹窗已有布局（自绘外壳对话框已建主布局）；无布局时才新建。
    outer = dialog.layout()
    if outer is None:
        outer = QVBoxLayout(dialog)
    outer.setContentsMargins(*margins)
    outer.addWidget(card)
    return card, outer


def add_green_glow(widget, blur_radius=发光默认模糊半径, alpha=发光默认透明度, accent=None):
    """给 widget 添加强调色外发光效果（无偏移，模拟高亮边框光晕）。

    Parameters
    ----------
    accent : QColor | None
        自定义发光颜色；None 则使用默认青绿色，保持旧调用兼容。

    主题切换支持
    ------------
    弹窗经常在 ``__init__`` 里调本函数只一次；后续主程序切换主题时，弹窗
    内部样式 (``setStyleSheet``) 由 ``Super_ADB_Win._传播主题到弹窗``
    同步刷新，但发光 ``QGraphicsDropShadowEffect`` 不会自动变色。本函数
    在 widget 上挂两个属性：

    - ``_green_glow_params = (blur_radius, alpha)``：标记 + 原始参数。
    - ``_green_glow_accent_rgb = (r, g, b)``：当前 accent（初始值）。

    同时把 widget 登记到 ``发光控件注册表``，主题切换时由 ``重建所有发光效果``
    统一重建，无需全树 findChildren 扫描。
    """
    color = accent if isinstance(accent, QColor) else ACCENT
    glow = QGraphicsDropShadowEffect(widget)
    glow.setBlurRadius(blur_radius)
    glow.setColor(QColor(color.red(), color.green(), color.blue(), alpha))
    glow.setOffset(0, 0)
    widget.setGraphicsEffect(glow)
    widget._green_glow_params = (blur_radius, alpha)
    widget._green_glow_accent_rgb = (color.red(), color.green(), color.blue())
    _注册发光控件(widget)


def rebuild_glow(widget, accent_rgb=None):
    """主题切换后重建 widget 上的 DropShadow。

    Returns
    -------
    bool
        是否真的做了重建（widget 上没有 ``_green_glow_params`` 标记时返 False）。

    关键技巧
    --------
    - **blurRadius 微差**（22~25 之间，按主题色 hash 浮动）强制 DWM 视作
      不同 effect bitmap，halo 旧 cache 必失效。
    - detach → ``processEvents`` → attach → ``processEvents`` flush 时序，
      避免 detach/reattach 在事件循环中被合并（实测 2026-08-20：合并执行
      时 DWM 仍认为 effect 没换）。
    - 末尾 ``repaint() + windowHandle().requestUpdate() + Win32 InvalidateRect``
      兜底 native 合成。
    """
    params = getattr(widget, '_green_glow_params', None)
    if params is None:
        return False
    blur_radius, alpha = params
    if accent_rgb is None:
        accent_rgb = widget._green_glow_accent_rgb
    r, g, b = accent_rgb[0], accent_rgb[1], accent_rgb[2]
    # blurRadius 微差（按主题色 hash 浮动，强制 DWM 视作不同 effect bitmap）
    color_hash = (r * 31 + g * 17 + b * 7) & 发光颜色哈希掩码
    new_blur = blur_radius - 发光模糊微差偏移 + color_hash

    new_glow = QGraphicsDropShadowEffect(widget)
    new_glow.setBlurRadius(new_blur)
    new_glow.setOffset(0, 0)
    new_glow.setColor(QColor(r, g, b, alpha))

    # detach 旧 effect
    widget.setGraphicsEffect(None)
    if QCoreApplication.instance() is not None:
        QCoreApplication.processEvents()
    # attach 新 effect
    widget.setGraphicsEffect(new_glow)
    if QCoreApplication.instance() is not None:
        QCoreApplication.processEvents()
    widget._green_glow_accent_rgb = (r, g, b)
    # native 层强制重画
    widget.repaint()
    wh = widget.windowHandle()
    if wh is not None:
        wh.requestUpdate()
    if sys.platform == 'win32':
        try:
            import ctypes
            hwnd = int(widget.winId())
            ctypes.windll.user32.InvalidateRect(hwnd, None, True)
            ctypes.windll.user32.UpdateWindow(hwnd)
        except Exception as e:
            print(f'[发光] Win32 重画失败: {e!r}')
    # ── 强刷 DropShadow halo bitmap ──
    # PySide6 6.11.1 + DWM 分层合成下，setGraphicsEffect(new) + repaint 偶尔
    # 让 DropShadow 的 halo bitmap 处于「已挂载未渲染」状态，必须靠真实
    # resizeEvent 触发 paintEvent 才能让 halo 真正重画（实测 2026-08-20）。
    # 临时 nudge 1px 几何再回原位（顶层 widget 才有效；最大化 / 全屏跳过）。
    _post_glow_kick(widget)
    return True


def _post_glow_kick(widget):
    """强刷 DropShadow halo bitmap：三层组合拳。

    PySide6 6.11.1 + DWM 分层窗口合成下，单层 nudge(1px) 在某些时序下
    仍可能让 DropShadow halo 处于「已挂载未渲染」状态。改用三重组合：

    1. **nudge 1px 几何再回原位** —— 触发真实 resizeEvent → paintEvent
    2. **Win32 WS_EX_LAYERED alpha flicker**（254 → 255）—— 强制 DWM
       重新合成整个 layered window 的 bitmap，包括所有 QGraphicsEffect halo
       （这是 Windows 主动刷新 layered window 的官方 API，绕开 Qt cache）
    3. **150ms 后再 nudge 一次** —— 兜底事件循环延迟 / paintEvent 未完成
       时 DWM 仍然持有的旧 frame

    最大化 / 全屏时几何 nudge 跟 WM 冲突，跳过。

    说明：本函数与 ``Super_ADB_Win._post_glow_attach_kick`` 同源思路；放在
    弹窗样式 是因为弹窗（card）也需要这套 kick，主窗口调它时复用。"""
    try:
        from PySide6.QtCore import QTimer
        if not widget.isWindow():
            # 嵌套 child widget 的 nudge 不会触发 native 层重画
            # 只有顶层 window 起作用——直接重画
            widget.repaint()
            return
        if widget.isMaximized() or widget.isFullScreen():
            widget.repaint()
            return
        # ── 第 1 拳：nudge 1px 几何 ──
        cur = widget.geometry()
        widget.setGeometry(cur.adjusted(0, 0, 0, 1))
        widget.setGeometry(cur)
        widget.repaint()
        # ── 第 2 拳：Win32 WS_EX_LAYERED alpha flicker ──
        # 这是 Windows 强制 layered window 重画的标准做法。对 WA_TranslucentBackground
        # 启用的 QWidget 来说，进程外调 SetLayeredWindowAttributes 会让 DWM
        # 立即重排 layer bitmap（不让 Qt 的 effect cache 有机会停住）。
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd = int(widget.winId())
                if hwnd:
                    # LWA_ALPHA = 分层窗口属性标志
                    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 分层窗口闪烁透明值, 分层窗口属性标志)
                    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, 分层窗口属性标志)
            except Exception as e:
                print(f'[发光] alpha flicker 失败: {e!r}')
        # ── 第 3 拳：延迟再 nudge（兜底事件循环延迟） ──
        QTimer.singleShot(二次踢延迟毫秒, lambda: _post_glow_kick_secondary(widget))
    except Exception as e:
        print(f'[发光] post kick 失败: {e!r}')


def _post_glow_kick_secondary(widget):
    """150ms 后的二次 kick：再 nudge 一次 + repaint + Win32 重画请求。"""
    try:
        if widget.isWindow() and not widget.isMaximized() and not widget.isFullScreen():
            cur = widget.geometry()
            widget.setGeometry(cur.adjusted(0, 0, 0, 1))
            widget.setGeometry(cur)
        widget.repaint()
        wh = widget.windowHandle()
        if wh is not None:
            wh.requestUpdate()
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd = int(widget.winId())
                if hwnd:
                    ctypes.windll.user32.InvalidateRect(hwnd, None, True)
                    ctypes.windll.user32.UpdateWindow(hwnd)
                    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 分层窗口闪烁透明值, 分层窗口属性标志)
                    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, 分层窗口属性标志)
            except Exception as e:
                print(f'[发光] 二次 kick Win32 失败: {e!r}')
    except Exception as e:
        print(f'[发光] 二次 kick 失败: {e!r}')


def _parse_rgb(rgb_str):
    """解析 'rgb(29,233,182)' / 'rgb(29, 233, 182)' → (29, 233, 182)。"""
    s = rgb_str
    if s.startswith('rgb(') and s.endswith(')'):
        s = s[4:-1]
    parts = [p.strip() for p in s.split(',') if p.strip()]
    return tuple(int(p) for p in parts[:3])


def _accent_rgb(theme_id):
    """返回主题强调色的 (r, g, b) 三元组。"""
    t = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
    return _parse_rgb(t['accent'])


def _hex_to_rgb(s):
    """解析 '#a7ffeb' / '#fff' → (r, g, b)；解析失败返回 None。"""
    if not isinstance(s, str) or not s.startswith('#'):
        return None
    s = s[1:]
    if len(s) == 3:
        s = ''.join(ch * 2 for ch in s)
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _rgba_string(rgb_or_str, alpha):
    """根据 ''#a7ffeb'' / 'rgb(0,0,0)' / (r,g,b) 拼出 rgba(r,g,b,a)。"""
    if isinstance(rgb_or_str, (tuple, list)) and len(rgb_or_str) >= 3:
        r, g, b = rgb_or_str[:3]
        return f'rgba({r},{g},{b},{alpha})'
    parsed = _parse_rgb(str(rgb_or_str)) if str(rgb_or_str).startswith('rgb') else None
    if parsed is None:
        parsed = _hex_to_rgb(str(rgb_or_str)) or (0, 0, 0)
    r, g, b = parsed
    return f'rgba({r},{g},{b},{alpha})'


# ----------------------------------------------------------------------
# 拖拽区域：可复用拖拽区
# ----------------------------------------------------------------------
class 拖拽区域(QLabel):
    """可拖入文件 / 点击选择文件的虚线框区域。

    把 ``安装解包对话框`` 里的同名类提到本模块共用，并扩展为多文件拖入。

    Parameters
    ----------
    text : str
        居中显示的提示文案，建议格式 ``"拖拽 X 到此处\\n（或点击下方按钮选择）"``。
    file_filter : str
        点击弹出 ``QFileDialog`` 时使用的过滤串，例如 ``"所有文件 (*)"``；
        传 ``""`` 表示不限制。
    file_mode : str
        ``"single"`` 只取拖入的第一个文件；``"multi"`` 把多个文件/文件夹都传给调用方。
    theme_id : str
        初始主题 id，可在创建后通过 ``apply_theme()`` 切换。
    """

    # 全部已转为本地文件路径（多文件 / 多文件夹模式：调用方展开）
    paths_dropped = Signal(list)

    def __init__(self, parent=None, text='', file_filter='', file_mode='single',
                 theme_id=DEFAULT_THEME):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(拖拽区最低高度)
        self._text = text or '拖入文件\n（或点击选择文件）'
        self._filter = file_filter
        self._mode = file_mode
        self._theme_id = theme_id if theme_id in THEMES else DEFAULT_THEME
        self._active = False  # 拖拽悬停中标记
        self.setText(self._text)
        self._apply_style()

    # -- 主题切换 ------------------------------------------------------
    def apply_theme(self, theme_id):
        if theme_id not in THEMES:
            return
        self._theme_id = theme_id
        self._apply_style()

    def _apply_style(self):
        t = THEMES[self._theme_id]
        accent = t['accent']
        text_primary = t['text_primary']
        # 用 accent 的低透明色作拖入时的底色提示
        accent_low = _rgba_string(accent, 拖拽区底色透明度)
        # 拖拽悬停态用 accent 色文字，默认态用主题文字色；hover 规则仅默认态需要
        文字色 = accent if self._active else text_primary
        悬停规则 = '' if self._active else f'QLabel:hover{{border: 2px solid {accent}; color: {accent};}}'
        self.setStyleSheet(
            f'QLabel{{background: {accent_low}; border: 2px dashed {accent};'
            f' border-radius: 8px; color: {文字色};'
            f' font: 10pt "{FONT_FAMILY}"; padding: 12px;}}'
            + 悬停规则)

    # -- 用户交互 ------------------------------------------------------
    def mousePressEvent(self, ev):
        if not self._filter:
            return
        dlg = QFileDialog(self, '选择文件', '', self._filter)
        if self._mode == 'multi':
            dlg.setFileMode(QFileDialog.ExistingFiles)
        else:
            dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec():
            paths = [p for p in dlg.selectedFiles() if p]
            if paths:
                self.paths_dropped.emit(paths)

    def dragEnterEvent(self, ev: QDragEnterEvent):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            self._active = True
            self._apply_style()

    def dragLeaveEvent(self, _ev):
        self._active = False
        self._apply_style()

    def dropEvent(self, ev: QDropEvent):
        self._active = False
        self._apply_style()
        urls = ev.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        paths = [p for p in paths if p]
        if paths:
            self.paths_dropped.emit(paths)
            ev.acceptProposedAction()


# ----------------------------------------------------------------------
# Down-Arrow 图标：主题感知版（替代 界面样式._arrow_icon_path 中默认值的复用入口）
# ----------------------------------------------------------------------
def make_down_arrow_pixmap(theme_id, size=16):
    """生成主题色向下箭头 QPixmap，用于自定义下拉箭头位置仍需要纯 QPixmap 的场景。"""
    r, g, b = _accent_rgb(theme_id)
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(0x00000000)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(r, g, b))
    p.setBrush(QColor(r, g, b))
    p.drawPolygon(QPolygon([QPoint(3, 5), QPoint(13, 5), QPoint(8, 12)]))
    p.end()
    return img


# ----------------------------------------------------------------------
# 无边框弹窗边缘缩放 Mixin
# ----------------------------------------------------------------------
class 无边框缩放Mixin:
    """给无边框 QDialog 增加边缘缩放能力（与已有的拖拽逻辑共存）。

    用法
    ----
    1. 类多继承::

        class MyDialog(QDialog, 无边框缩放Mixin):

    2. ``__init__`` 末尾（所有子控件创建完后）调用::

        self._初始化缩放(边距=8)

    3. 不要用 ``setFixedSize``，改用 ``setMinimumSize`` + ``resize``。
    4. 在自身的 ``mousePressEvent`` / ``mouseMoveEvent`` / ``mouseReleaseEvent``
       开头分别调用 ``_缩放按下处理`` / ``_缩放移动处理`` /
       ``_缩放释放处理``，返回 True 表示事件已被缩放逻辑消费，不应再走拖拽。
    5. 如果弹窗内有用 ``setGeometry`` 固定位置的 card，重写 ``resizeEvent``
       同步其几何（见 关于对话框 / 环境配置对话框）。

    设计要点
    --------
    - 子控件（按钮/输入框/标签等）会吞掉鼠标事件，因此仅靠弹窗自身的
      ``mouse*Event`` 无法覆盖子控件上方的边缘热区。本 mixin 通过
      ``eventFilter`` 给所有子控件装过滤器，把边缘热区内的鼠标事件拦截
      回弹窗处理缩放。
    - 顶部边缘不参与缩放（``_取缩放方向`` 对纯 top 返回 None），留给
      标题栏拖拽，避免与拖拽冲突。
    - 交互型控件（按钮/输入框等）在非边缘区域正常放行，不影响原有交互。
    """

    def _初始化缩放(self, 边距=8):
        """初始化缩放状态并给所有子控件安装事件过滤器。

        必须在所有子控件创建完毕后调用；后续动态新增的子控件如需支持
        边缘缩放，可再次调用本方法（幂等：已装过过滤器的控件不会重复装）。

        关键：必须给弹窗自身和所有子控件开启 ``setMouseTracking(True)``，
        否则鼠标悬停（未按键）时 ``MouseMove`` 事件不会发送到子控件，
        ``eventFilter`` 收不到，边缘光标就不会切换成调整箭头。
        """
        self._缩放中 = False
        self._缩放方向 = None
        self._缩放起点 = QPoint()
        self._缩放原几何 = QRect()
        self._缩放边距 = 边距
        # 弹窗自身开启鼠标追踪（鼠标在弹窗本体空白区域移动时也能触发光标更新）
        self.setMouseTracking(True)
        from PySide6.QtWidgets import QWidget as _QWidget
        for child in self.findChildren(_QWidget):
            try:
                # 开启鼠标追踪：悬停（未按键）时也能收到 MouseMove，eventFilter 才能更新边缘光标
                child.setMouseTracking(True)
                child.installEventFilter(self)
            except Exception:
                pass

    def _取缩放方向(self, 坐标):
        """根据鼠标在弹窗内的坐标判断边缘缩放方向，不在边缘返回 None。

        纯顶部（top only）返回 None——留给标题栏拖拽，避免与拖拽冲突。
        四角 + 左右 + 底部均可缩放。
        """
        rect = self.rect()
        m = getattr(self, '_缩放边距', 8)
        左 = 坐标.x() < m
        右 = 坐标.x() > rect.width() - m
        上 = 坐标.y() < m
        下 = 坐标.y() > rect.height() - m
        if 上 and 左:
            return Qt.Edge.TopEdge | Qt.Edge.LeftEdge
        if 上 and 右:
            return Qt.Edge.TopEdge | Qt.Edge.RightEdge
        if 下 and 左:
            return Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        if 下 and 右:
            return Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        if 左:
            return Qt.Edge.LeftEdge
        if 右:
            return Qt.Edge.RightEdge
        if 下:
            return Qt.Edge.BottomEdge
        # 纯顶部不缩放，留给拖拽
        return None

    def _更新缩放光标(self, 方向):
        """根据缩放方向更新鼠标光标形状，方向为 None 时恢复默认。"""
        if 方向 is None:
            self.unsetCursor()
            return
        CS = Qt.CursorShape
        if 方向 in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
                    Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            self.setCursor(CS.SizeFDiagCursor)
        elif 方向 in (Qt.Edge.TopEdge | Qt.Edge.RightEdge,
                      Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            self.setCursor(CS.SizeBDiagCursor)
        elif 方向 in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            self.setCursor(CS.SizeHorCursor)
        elif 方向 in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            self.setCursor(CS.SizeVerCursor)
        else:
            self.setCursor(CS.SizeAllCursor)

    def _执行缩放(self, 全局坐标):
        """根据鼠标全局位移量执行窗口缩放，最小尺寸由 minimumWidth/Height 约束。"""
        位移 = 全局坐标 - self._缩放起点
        几何 = QRect(self._缩放原几何)
        最小宽 = max(self.minimumWidth(), 1)
        最小高 = max(self.minimumHeight(), 1)
        if self._缩放方向 & Qt.Edge.RightEdge:
            几何.setWidth(max(最小宽, self._缩放原几何.width() + 位移.x()))
        if self._缩放方向 & Qt.Edge.LeftEdge:
            新宽 = max(最小宽, self._缩放原几何.width() - 位移.x())
            几何.setLeft(self._缩放原几何.left() + self._缩放原几何.width() - 新宽)
            几何.setWidth(新宽)
        if self._缩放方向 & Qt.Edge.BottomEdge:
            几何.setHeight(max(最小高, self._缩放原几何.height() + 位移.y()))
        if self._缩放方向 & Qt.Edge.TopEdge:
            新高 = max(最小高, self._缩放原几何.height() - 位移.y())
            几何.setTop(self._缩放原几何.top() + self._缩放原几何.height() - 新高)
            几何.setHeight(新高)
        self.setGeometry(几何)

    # -- 供弹窗 mouse*Event 调用的接口（返回 True 表示已消费） --

    def _缩放按下处理(self, 事件):
        """在弹窗自身 mousePressEvent 开头调用：边缘按下则启动缩放。"""
        if 事件.button() != Qt.MouseButton.LeftButton:
            return False
        方向 = self._取缩放方向(事件.position().toPoint())
        if 方向 is None:
            return False
        self._缩放中 = True
        self._缩放方向 = 方向
        self._缩放起点 = 事件.globalPosition().toPoint()
        self._缩放原几何 = self.geometry()
        事件.accept()
        return True

    def _缩放移动处理(self, 事件):
        """在弹窗自身 mouseMoveEvent 开头调用：缩放中则执行缩放，否则更新光标。"""
        if getattr(self, '_缩放中', False):
            if 事件.buttons() & Qt.MouseButton.LeftButton:
                self._执行缩放(事件.globalPosition().toPoint())
            事件.accept()
            return True
        # 非缩放中：更新边缘光标提示
        方向 = self._取缩放方向(事件.position().toPoint())
        self._更新缩放光标(方向)
        return False

    def _缩放释放处理(self, 事件):
        """在弹窗自身 mouseReleaseEvent 开头调用：结束缩放状态。"""
        if getattr(self, '_缩放中', False):
            self._缩放中 = False
            self._缩放方向 = None
            self.unsetCursor()
            事件.accept()
            return True
        return False

    # -- 子控件事件过滤器：让子控件上方的边缘热区也能触发缩放 --

    def eventFilter(self, obj, event):
        """拦截子控件上的鼠标事件：边缘热区内交给缩放逻辑，否则放行。

        仅拦截 LeftButton 按下/移动/释放 + HoverMove，其余事件一律放行，
        不影响按钮点击、输入框编辑等正常交互。
        """
        from PySide6.QtWidgets import QWidget as _QWidget
        if not isinstance(obj, _QWidget):
            return super().eventFilter(obj, event)
        et = event.type()
        if et == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                局部 = obj.mapTo(self, event.position().toPoint())
                if self._取缩放方向(局部) is not None:
                    self._缩放中 = True
                    self._缩放方向 = self._取缩放方向(局部)
                    self._缩放起点 = event.globalPosition().toPoint()
                    self._缩放原几何 = self.geometry()
                    return True
        elif et == QEvent.Type.MouseMove:
            if self._缩放中:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self._执行缩放(event.globalPosition().toPoint())
                return True
            # 非缩放中：更新边缘光标（仅当鼠标在子控件上时）
            局部 = obj.mapTo(self, event.position().toPoint())
            方向 = self._取缩放方向(局部)
            self._更新缩放光标(方向)
        elif et == QEvent.Type.MouseButtonRelease:
            if self._缩放中:
                self._缩放中 = False
                self._缩放方向 = None
                self.unsetCursor()
                return True
        elif et == QEvent.Type.HoverMove:
            局部 = obj.mapTo(self, event.position().toPoint())
            方向 = self._取缩放方向(局部)
            self._更新缩放光标(方向)
        return super().eventFilter(obj, event)
