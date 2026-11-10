# -*- coding: utf-8 -*-
"""
桌面宠物小猫 —— DeskCatWidget
============================
在 Super_ADB 主窗口里养一只会玩耍、会躲避鼠标的小猫。

架构
----
* 独立顶层透明窗口（FramelessWindowHint | Tool | WindowDoesNotAcceptFocus
  | WindowTransparentForInput），而不是主窗口里的子控件。
* 为什么必须是顶层窗口：半透明无边框主窗口上的透明子控件，每帧 move 后
  要"擦掉父窗口旧区域"，而父窗口的 backing store 合成与 DWM 帧调度存在
  竞态——旧帧被 DWM 先合成出去就留下猫影，只能靠 repaint/整窗 update/
  定时重建堆补丁，越补越乱。顶层窗口的移动由 DWM 整窗重定位，不存在
  "擦旧区"这一步，残影从根上消失。
* 位置用父窗口局部坐标维护（跟随主窗口移动/缩放），真正 move 时换算成
  屏幕坐标。
* 点击穿透靠 WindowTransparentForInput（Windows 下即
  WS_EX_LAYERED | WS_EX_TRANSPARENT），不抢焦点。
* 唯一例外：Linux Wayland 会话不允许客户端给顶层窗口定位，此时自动退回
  父窗口子控件模式（`_F可创建顶层窗口`），Windows / macOS / X11 均走顶层窗口。
* 状态机：待机 / 走动 / 奔跑 / 玩耍 / 睡觉
* 鼠标进入警戒范围自动逃跑
* 气泡文字互动

图片要求
--------
推荐使用带透明背景的 PNG，例如用户放在桌面的那只橘白小猫。
"""

import math
import random
import os
import sys

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QCursor, QTransform, QFont, QBitmap, QRegion,
    qAlpha, qRgba,
)
from PySide6.QtWidgets import (
    QWidget, QLabel
)

from 项目UI.界面样式 import THEMES, get_current_theme_id

# 注册编译后的资源文件，确保 :/desk_cat.png 可用（打包后不依赖外部图片路径）
try:
    import png_rc  # noqa: F401
except ImportError:
    pass


class DeskCatWidget(QWidget):
    """桌面宠物小猫控件。"""

    # 状态常量
    STATE_IDLE = 'idle'
    STATE_WALK = 'walk'
    STATE_RUN = 'run'
    STATE_PLAY = 'play'
    STATE_SLEEP = 'sleep'

    # 小猫相对于主窗口的默认停靠位置（右下角留白）
    DEFAULT_OFFSET = QPoint(40, 60)

    # 顶层窗口标志。
    # ★ 不加 WindowStaysOnTopHint：Qt::Tool 带父窗口时已经有 owner 关系，
    #   始终压在主窗口之上；再加 StaysOnTop 会让小猫飘到别的应用窗口上面。
    # ★ WindowTransparentForInput：鼠标点击击穿到下层窗口（Windows 下由 Qt
    #   补上 WS_EX_LAYERED | WS_EX_TRANSPARENT），不抢焦点、不进任务栏。
    _顶层窗口标志 = (
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.Tool
        | Qt.WindowType.WindowDoesNotAcceptFocus
        | Qt.WindowType.NoDropShadowWindowHint
        | Qt.WindowType.WindowTransparentForInput
    )

    def __init__(self, parent=None, image_path=None, size=85):
        # parent 只作为「归属窗口」传入：顶层窗口会绑定到 parent 的 HWND，
        # 生命周期跟着主窗口走，同时保持独立原生窗口（DWM 整窗重定位）。
        # Linux Wayland 会话下客户端无权给顶层窗口定位，只能退回子控件模式。
        self._有顶层窗口 = self._F可创建顶层窗口()
        if self._有顶层窗口:
            super().__init__(parent, self._顶层窗口标志)
        else:
            super().__init__(parent)
        self._parent = parent
        self._image_path = image_path  # 保留图片路径，便于需要时重新加载
        self._cat_size = QSize(int(size * 1.8), int(size * 1.6))  # 窗口略大于猫图，留出阴影和留白
        self._cat_display_size = QSize(int(size * 1.6), int(size * 1.4))  # 小猫图片实际显示大小
        self._placed = False  # 是否已完成首次随机落位
        self._state = self.STATE_IDLE
        self._facing_right = True
        self._frame = 0
        self._paused = False
        self._hidden_by_user = False
        # 隐藏后 20 秒是否自动回来；由主入口按开关状态控制，
        # _do_hide 不再重置本标志（否则取消勾选置的 False 会被覆盖）
        self._should_come_back = True

        # 移动相关
        self._pos = QPoint(0, 0)
        self._velocity = QPoint(0, 0)
        self._target = None
        self._speed = 0
        self._bounds = QRect(0, 0, 0, 0)

        # 动画相位（呼吸、摇摆、弹跳）
        self._breath_phase = 0.0
        self._bob_phase = 0.0
        self._play_phase = 0.0

        # 鼠标躲避参数
        self._flee_radius = 75  # 进入此半径开始逃跑（调小，避免鼠标稍靠近就逃）
        self._flee_cooldown = 0  # 逃跑冷却帧数

        # 鼠标静止检测：鼠标不动时小猫不应持续逃跑，否则会一直被逼到边缘
        self._last_mouse_pos = QPoint()
        self._mouse_still_frames = 0
        self._mouse_still_threshold = 5  # 约 200ms 鼠标没动才算静止

        # 配置窗口属性
        # 顶层窗口 + 透明背景：DWM 直接合成整窗，配 WindowTransparentForInput
        # 后鼠标事件穿透到下面的窗口。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self._cat_size)

        # 加载图片
        self._pixmap = self._load_pixmap(image_path)
        self._scaled_pixmap = self._pixmap.scaled(
            self._cat_display_size.width(), self._cat_display_size.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # 装饰标签（展示气泡文字）
        # ★ parent 必须是父窗口而不是 self：避免子控件层级问题。
        self._bubble = QLabel(self._parent if self._parent is not None else self)
        self._bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._theme_id = get_current_theme_id(self)
        self._apply_bubble_style()
        self._bubble.hide()

        # 行为决策定时器
        self._think_timer = QTimer(self)
        self._think_timer.timeout.connect(self._think)
        self._think_timer.start(1800)

        # 动画帧定时器（约 25 FPS）
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(40)

        # 泡泡文字隐藏定时器
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self._bubble.hide)

    # ------------------------------------------------------------------
    # 主题切换
    # ------------------------------------------------------------------
    def _apply_bubble_style(self):
        """根据当前主题设置气泡标签样式。"""
        t = THEMES.get(self._theme_id, THEMES.get('dark_cyan', {}))
        bg = t.get('bg_window', '#1e1e1e')
        text = t.get('text_primary', '#ffffff')
        # 背景用主题色 + 半透明，文字用主题文字色
        r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        self._bubble.setStyleSheet(
            f'background:rgba({r},{g},{b},200); color:{text};'
            f' border-radius:8px; padding:4px 8px; font-size:11px;'
        )

    def apply_theme(self, theme_id):
        """运行时切换主题：更新气泡标签样式。"""
        if theme_id not in THEMES:
            theme_id = 'dark_cyan'
        self._theme_id = theme_id
        self._apply_bubble_style()
        self.update()

    # ------------------------------------------------------------------
    # 图片加载
    # ------------------------------------------------------------------
    @staticmethod
    def _load_pixmap(image_path):
        """加载小猫图片，若失败则返回一只纯色占位猫。

        优先使用 qrc 资源路径（以 ':' 开头，打包后随程序发布），
        也兼容普通文件系统路径。
        """
        if image_path:
            # 资源路径（:/xxx）无法用 os.path.isfile 判断，直接交给 QPixmap
            is_resource = image_path.startswith(':')
            if is_resource or os.path.isfile(image_path):
                pm = QPixmap(image_path)
                if not pm.isNull():
                    return pm

        # 默认占位：画一只圆滚滚的橘猫
        pm = QPixmap(120, 132)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 身体
        p.setBrush(QColor('#f5b971'))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(20, 40, 80, 80)
        # 头
        p.drawEllipse(30, 10, 60, 60)
        # 耳朵
        p.drawEllipse(28, 8, 18, 28)
        p.drawEllipse(74, 8, 18, 28)
        # 眼睛
        p.setBrush(QColor('#333'))
        p.drawEllipse(44, 32, 8, 10)
        p.drawEllipse(68, 32, 8, 10)
        # 鼻子
        p.setBrush(QColor('#ffb7b2'))
        p.drawEllipse(56, 42, 8, 6)
        # 肚皮白毛
        p.setBrush(QColor('#fff8f0'))
        p.drawEllipse(40, 80, 40, 50)
        p.end()
        return pm

    # ------------------------------------------------------------------
    # 顶层窗口
    # ------------------------------------------------------------------
    @staticmethod
    def _F可创建顶层窗口():
        """是否用独立顶层窗口承载小猫。

        Wayland 会话不允许客户端给顶层窗口定位（move() 会被合成器忽略），
        小猫会卡死在屏幕上某处；这种环境只能退回父窗口子控件模式。
        Windows / macOS / X11 都返回 True。
        """
        if sys.platform.startswith('linux'):
            try:
                from PySide6.QtGui import QGuiApplication
                V平台名 = (QGuiApplication.platformName() or '').lower()
                if 'wayland' in V平台名:
                    return False
            except Exception:
                pass
        return True

    def _F应用顶层穿透样式(self):
        """给顶层窗口补上点击穿透 / 不抢焦点的 Windows 扩展样式（双保险）。

        Qt 的 WindowTransparentForInput 已经会让窗口带上
        WS_EX_TRANSPARENT（Qt 半透明窗口本身已带 WS_EX_LAYERED），
        这里再做一次幂等确认，防止某些 Qt 版本或打包环境没带上。
        实测：手动补 LAYERED|TRANSPARENT 后的扩展样式与 Qt 自己算的一致，
        不会破坏透明绘制。
        """
        if sys.platform != 'win32' or not getattr(self, '_有顶层窗口', True):
            return
        try:
            import ctypes
            V用户32 = ctypes.WinDLL('user32', use_last_error=True)
            V有长指针 = hasattr(V用户32, 'GetWindowLongPtrW')
            V取长 = V用户32.GetWindowLongPtrW if V有长指针 else V用户32.GetWindowLongW
            V设长 = V用户32.SetWindowLongPtrW if V有长指针 else V用户32.SetWindowLongW
            V长整类型 = ctypes.c_ssize_t if V有长指针 else ctypes.c_long
            V取长.argtypes = [ctypes.c_void_p, ctypes.c_int]
            V取长.restype = V长整类型
            V设长.argtypes = [ctypes.c_void_p, ctypes.c_int, V长整类型]
            V设长.restype = V长整类型
            V句柄 = ctypes.c_void_p(int(self.winId()))
            V原样式 = V取长(V句柄, -20)  # GWL_EXSTYLE
            # LAYERED | TRANSPARENT | NOACTIVATE
            V目标样式 = V原样式 | 0x00080000 | 0x00000020 | 0x08000000
            if V目标样式 != V原样式:
                V设长(V句柄, -20, V目标样式)
        except Exception:
            pass  # 样式设置失败不影响小猫显示（Qt 侧已经设过）

    def _F父窗口局部转屏幕(self, 点):
        """父窗口局部坐标 → 屏幕坐标（小猫是顶层窗口，move 用屏幕坐标）。"""
        if self._parent is not None:
            return self._parent.mapToGlobal(点)
        return QPoint(点)


    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def set_bounds(self, rect: QRect):
        """设置小猫的活动边界（父窗口坐标）。"""
        self._bounds = rect
        if not self._bounds.isEmpty() and not self._placed:
            # 首次设定边界时随机落位，避免小猫停在角落
            self._placed = True
            min_x = self._bounds.left() + 4
            max_x = max(min_x, self._bounds.right() - self.width() - 4)
            min_y = self._bounds.top() + 4
            max_y = max(min_y, self._bounds.bottom() - self.height() - 4)
            self.set_position(QPoint(
                random.randint(min_x, max_x),
                random.randint(min_y, max_y),
            ))
        else:
            # 主窗口移动/缩放时会重设边界：局部坐标没变，屏幕位置却已经变了，
            # 必须重新定位，否则小猫会跟丢主窗口。
            self._clamp_position()
            self._move_to_position()

    def set_position(self, pos: QPoint):
        """立即把小猫放到指定位置（父窗口坐标）。"""
        self._pos = QPoint(pos)
        self._clamp_position()
        self._move_to_position()

    def say(self, text: str, ms: int = 2000):
        """头顶冒出一句话。"""
        self._bubble.setText(text)
        self._bubble.adjustSize()
        # 气泡用父窗口坐标定位在小猫头顶上方
        cx = self._pos.x() + self.width() // 2
        bx = cx - self._bubble.width() // 2
        by = self._pos.y() - self._bubble.height() - 4
        self._bubble.move(bx, by)
        self._bubble.show()
        self._bubble.raise_()
        self._bubble_timer.start(ms)

    def pause(self):
        """暂停小猫的自动行为。"""
        self._paused = True
        self._velocity = QPoint(0, 0)
        self._target = None
        self._state = self.STATE_IDLE

    def resume(self):
        """恢复小猫的自动行为。"""
        self._paused = False

    def hide_cat(self):
        """用户主动隐藏小猫（停止所有后台定时器，不消耗资源）。"""
        self._hidden_by_user = True
        # 关闭前说点话
        import random
        bye_words = ['去吃饭了~', '去找女朋友了~', '去捣乱了~', '溜了溜了~', '下次再玩~']
        self.say(random.choice(bye_words), 3000)
        # 延迟3秒再隐藏，让气泡能完整看完
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, self._do_hide)

    def _do_hide(self):
        """真正隐藏小猫并停止定时器，20秒后自动回来。"""
        self.hide()
        self._bubble.hide()
        # 停止后台定时器，隐藏时不运行不耗资源
        try:
            self._think_timer.stop()
            self._anim_timer.stop()
        except Exception:
            pass
        # 延迟20秒后自动重新展示出来（用户取消勾选时不要自动回来）
        # ★ 不要在这里重置 _should_come_back：取消勾选路径已由主入口置 False，
        #   若此处覆盖回 True，20 秒后小猫会在用户明确关闭后自己复活。
        from PySide6.QtCore import QTimer
        import random
        def _自动回来():
            try:
                if not self._hidden_by_user:
                    return  # 用户已经手动显示了
                if not self._should_come_back:
                    return  # 用户取消勾选了，不自动回来
                self.show()
                self.raise_()
                self.update()
                # 重启定时器
                self._think_timer.start(1800)
                self._anim_timer.start(40)
                # 延迟3秒再说话（等小猫位置和重绘就绪），展示3秒
                welcome_words = ['我又回来啦~', '想我了没~', '我胡汉三又回来了~', '还是这里好玩~']
                word = random.choice(welcome_words)
                QTimer.singleShot(3000, lambda: self.say(word, 3000))
            except Exception:
                pass
        QTimer.singleShot(20000, _自动回来)

    def show_cat(self):
        """重新显示被隐藏的小猫（重启后台定时器）。"""
        self._hidden_by_user = False
        # 顶层窗口 show() 就够了，不需要再去强制主窗口整窗重绘
        self.show()
        self.raise_()
        self.update()
        self._move_to_position()
        # 重启后台定时器
        try:
            self._think_timer.start(1800)
            self._anim_timer.start(40)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------
    def showEvent(self, event):
        """每次显示时确认顶层窗口样式并重新定位。"""
        super().showEvent(event)
        self._F应用顶层穿透样式()
        self._move_to_position()

    def paintEvent(self, event):
        """绘制小猫，根据状态做动态变换。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 基础变换：呼吸缩放 + 走路摇摆 + 逃跑倾斜 + 玩耍旋转
        transform = QTransform()
        cx = self.width() / 2
        cy = self.height() * 0.85  # 以底部中心为锚点
        transform.translate(cx, cy)

        # 朝向
        sx = -1.0 if not self._facing_right else 1.0

        # 呼吸
        breath = 1.0 + math.sin(self._breath_phase) * 0.03
        transform.scale(sx * breath, breath)

        # 走路摇摆
        if self._state == self.STATE_WALK:
            rot = math.sin(self._bob_phase) * 2.0
            transform.rotate(rot)

        # 逃跑时身体前倾
        if self._state == self.STATE_RUN:
            lean = 8.0 if self._facing_right else -8.0
            transform.rotate(lean)

        # 玩耍时原地转圈 + 弹跳
        if self._state == self.STATE_PLAY:
            bounce = abs(math.sin(self._play_phase * 3)) * 10
            transform.translate(0, -bounce)
            transform.rotate(math.sin(self._play_phase) * 10)

        # 睡觉时会缩成一团（轻微缩小并下移）
        if self._state == self.STATE_SLEEP:
            transform.scale(1.05, 0.85)
            transform.translate(0, 8)

        transform.translate(-cx, -cy)
        painter.setTransform(transform)

        # 绘制阴影
        shadow_opacity = 0.25
        if self._state == self.STATE_RUN:
            shadow_opacity = 0.15
        painter.setBrush(QColor(0, 0, 0, int(255 * shadow_opacity)))
        painter.setPen(Qt.PenStyle.NoPen)
        shadow_w = self.width() * 0.55
        shadow_h = self.height() * 0.12
        painter.drawEllipse(
            int((self.width() - shadow_w) / 2),
            int(self.height() - shadow_h - 4),
            int(shadow_w),
            int(shadow_h)
        )

        # 绘制小猫
        pm = self._scaled_pixmap
        x = (self.width() - pm.width()) // 2
        y = self.height() - pm.height() - 6  # 底部对齐，留一点空间给阴影
        painter.drawPixmap(x, y, pm)

        # 睡觉画 "Zzz"
        if self._state == self.STATE_SLEEP:
            painter.resetTransform()
            painter.setPen(QColor('#fff'))
            painter.setFont(QFont('Microsoft YaHei', 10))
            painter.drawText(self.width() - 28, 24, 'Z')
            painter.setFont(QFont('Microsoft YaHei', 8))
            painter.drawText(self.width() - 18, 16, 'z')
            painter.setFont(QFont('Microsoft YaHei', 6))
            painter.drawText(self.width() - 10, 10, 'z')

        painter.end()

    # ------------------------------------------------------------------
    # 行为决策
    # ------------------------------------------------------------------
    def _mouse_is_moving(self) -> bool:
        """检测鼠标是否在移动（静止时不应持续驱赶小猫）。"""
        global_mouse = QCursor.pos()
        if global_mouse == self._last_mouse_pos:
            self._mouse_still_frames += 1
        else:
            self._mouse_still_frames = 0
            self._last_mouse_pos = QPoint(global_mouse)
        return self._mouse_still_frames < self._mouse_still_threshold

    def _think(self):
        """每隔一段时间做一次状态决策。"""
        if self._paused or not self.isVisible():
            return

        mouse_pos = self._mouse_in_parent()
        cat_center = self._center_in_parent()
        dist = self._distance(cat_center, mouse_pos)
        mouse_moving = self._mouse_is_moving()

        # 逃跑优先级最高，但鼠标静止时不逃（避免小猫被逼到墙角后一直僵住）
        if (dist < self._flee_radius and self._flee_cooldown <= 0
                and mouse_moving):
            self._flee_from(mouse_pos)
            self.say('呀！别过来~', 1000)
            return

        # 逃跑冷却递减
        if self._flee_cooldown > 0:
            self._flee_cooldown -= 1

        # 已经在移动就继续，不做新的随机决策
        if self._state in (self.STATE_WALK, self.STATE_RUN) and self._target:
            return

        # 随机选择下一个动作
        r = random.random()
        if r < 0.45:
            self._start_walk()
        elif r < 0.70:
            self._state = self.STATE_IDLE
            self._velocity = QPoint(0, 0)
            self._target = None
        elif r < 0.85:
            self._start_play()
        else:
            self._state = self.STATE_SLEEP
            self._velocity = QPoint(0, 0)
            self._target = None

    def _tick(self):
        """动画帧更新。"""
        if not self.isVisible():
            return

        self._frame += 1
        self._breath_phase += 0.08
        self._bob_phase += 0.25
        self._play_phase += 0.15

        # 持续检测鼠标，但鼠标静止/冷却中不逃跑
        mouse_pos = self._mouse_in_parent()
        cat_center = self._center_in_parent()
        dist = self._distance(cat_center, mouse_pos)
        mouse_moving = self._mouse_is_moving()
        if (dist < self._flee_radius and self._flee_cooldown <= 0
                and not self._paused and mouse_moving):
            self._flee_from(mouse_pos)

        if self._state in (self.STATE_WALK, self.STATE_RUN) and self._target:
            self._move_toward_target()

        self.update()

    # ------------------------------------------------------------------
    # 移动与动画
    # ------------------------------------------------------------------
    def _start_walk(self):
        """随机选一个目标点走过去，优先选择离鼠标较远的位置，减少被追边。"""
        if self._bounds.isEmpty():
            return
        margin = 8  # 小窗口时留更小边距，避免选不出点
        mouse = self._mouse_in_parent()
        candidates = []
        for _ in range(3):
            min_x = self._bounds.left() + margin
            max_x = max(min_x, self._bounds.right() - self.width() - margin)
            min_y = self._bounds.top() + margin
            max_y = max(min_y, self._bounds.bottom() - self.height() - margin)
            x = random.randint(min_x, max_x)
            y = random.randint(min_y, max_y)
            candidates.append(QPoint(x, y))
        # 选离鼠标最远的候选点，让小猫倾向于远离鼠标活动
        self._target = max(candidates, key=lambda p: self._distance(p, mouse))
        self._speed = random.randint(2, 4)
        self._state = self.STATE_WALK

    def _flee_from(self, mouse_pos: QPoint):
        """朝鼠标反方向逃跑。"""
        cat_center = self._center_in_parent()
        dx = cat_center.x() - mouse_pos.x()
        dy = cat_center.y() - mouse_pos.y()
        length = math.hypot(dx, dy) or 1.0

        # 逃跑距离：至少 250px
        flee_dist = max(250, int(self._flee_radius * 2.2))
        target_x = int(cat_center.x() + (dx / length) * flee_dist - self.width() / 2)
        target_y = int(cat_center.y() + (dy / length) * flee_dist - self.height() / 2)

        target = QPoint(target_x, target_y)
        self._clamp_target_to_bounds(target)  # 目标点也要落在边界内，避免卡墙
        self._target = target
        self._speed = random.randint(7, 11)
        self._state = self.STATE_RUN
        # 延长冷却：逃跑后约 1 秒内不再触发逃跑，让小猫有时间散步/玩耍
        self._flee_cooldown = 25

    def _start_play(self):
        """进入玩耍状态：原地转圈、扑腾。"""
        self._state = self.STATE_PLAY
        self._velocity = QPoint(0, 0)
        self._target = None
        self._play_phase = 0.0

    def _clamp_target_to_bounds(self, target: QPoint):
        """把逃跑目标点限制在活动边界内，避免目标落在边界外导致卡墙。"""
        if self._bounds.isEmpty():
            return
        target.setX(max(
            self._bounds.left(),
            min(target.x(), self._bounds.right() - self.width())
        ))
        target.setY(max(
            self._bounds.top(),
            min(target.y(), self._bounds.bottom() - self.height())
        ))

    def _move_toward_target(self):
        """朝当前目标点移动一步。"""
        if not self._target:
            return
        prev = QPoint(self._pos)
        dx = self._target.x() - self._pos.x()
        dy = self._target.y() - self._pos.y()
        dist = math.hypot(dx, dy)

        if dist < self._speed:
            self._pos = QPoint(self._target)
            self._target = None
            self._state = self.STATE_IDLE
            self._velocity = QPoint(0, 0)
        else:
            step_x = int(round(dx / dist * self._speed))
            step_y = int(round(dy / dist * self._speed))
            self._velocity = QPoint(step_x, step_y)
            self._pos += self._velocity

        # 根据速度方向决定朝向
        if abs(self._velocity.x()) > 0:
            self._facing_right = self._velocity.x() > 0

        self._clamp_position()
        # 撞墙检测：位置被 clamp 锁死且仍未到达目标点，说明目标在边界外，
        # 放弃该目标回到待机，避免小猫永远卡在边缘抖动。
        if self._target is not None and self._pos == prev:
            self._target = None
            self._state = self.STATE_IDLE
            self._velocity = QPoint(0, 0)
        self._move_to_position()

    def _clamp_position(self):
        """把位置限制在活动边界内。"""
        if self._bounds.isEmpty():
            return
        self._pos.setX(max(
            self._bounds.left(),
            min(self._pos.x(), self._bounds.right() - self.width())
        ))
        self._pos.setY(max(
            self._bounds.top(),
            min(self._pos.y(), self._bounds.bottom() - self.height())
        ))

    def _move_to_position(self):
        """把小猫顶层窗口移动到 _pos（父窗口局部坐标）对应的屏幕位置。

        ★ 这是本文件最关键的改动：小猫是独立顶层窗口，移动由 DWM 整窗
        重定位完成，不存在"父窗口要擦掉旧位置像素"这一步，也就不需要
        repaint(旧矩形) / update(新矩形) / 整窗 update() 的三连补丁。
        Wayland 退路下是普通子控件，move 用父窗口局部坐标。
        """
        if self._有顶层窗口:
            self.move(self._F父窗口局部转屏幕(self._pos))
        else:
            self.move(self._pos)

    # ------------------------------------------------------------------
    # 坐标工具
    # ------------------------------------------------------------------
    def _mouse_in_parent(self) -> QPoint:
        """鼠标在父窗口坐标系中的位置。"""
        global_mouse = QCursor.pos()
        if self._parent is None:
            return self.mapFromGlobal(global_mouse)
        return self._parent.mapFromGlobal(global_mouse)

    def _center_in_parent(self) -> QPoint:
        """小猫中心在父窗口坐标系中的位置。"""
        return QPoint(
            self._pos.x() + self.width() // 2,
            self._pos.y() + self.height() // 2
        )

    @staticmethod
    def _distance(a: QPoint, b: QPoint) -> float:
        return math.hypot(a.x() - b.x(), a.y() - b.y())

# ----------------------------------------------------------------------
# 便捷工厂函数
# ----------------------------------------------------------------------
def create_desk_cat(parent, image_path=None, size=85):
    """为父窗口创建一只桌面小猫并返回控件。

    参数
    ----
    parent : QWidget
        主窗口，小猫会跟随它移动。
    image_path : str, optional
        小猫 PNG 图片路径。缺省使用内置占位猫。
    size : int, optional
        小猫显示尺寸（像素），默认 85。
    """
    cat = DeskCatWidget(parent=parent, image_path=image_path, size=size)
    cat.show()
    cat.raise_()
    return cat
