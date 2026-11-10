# -*- coding: utf-8 -*-
"""
ADB 交互式终端弹窗
==================
点击「便携工具 → ADB命令行」打开的独立窗口。
类似 adb shell 不带参数进入的交互式终端，可持续敲命令、实时看输出。

连接方式按环境配置自动分流：
  - 自研 ADB 模式：自研adb客户端.交互式Shell（真 PTY，保持 cd/环境变量）
  - 非自研模式：行模式会话（每条命令独立 `adb -s serial shell <cmd>`，
    不保持工作目录；无 PTY，命令由 GUI 本地回显）

功能:
  - 设备下拉框列所有已连接设备，点击自动连接终端
  - 与主窗口三个设备选择栏双向同步
  - 命令历史（上下箭头）、Ctrl+C / Ctrl+D、清屏
  - ANSI 转义序列过滤，深色终端风格

样式:
  - 复用 弹窗样式.py 的 _create_popup_card + add_green_glow
  - 与 JSON/MD5/时间戳弹窗同款青绿色高亮边框 + 外发光
  - apply_theme() 支持运行时主题切换
"""

import codecs
import re
from collections import deque

from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent
from PySide6.QtGui import QFont, QIcon, QColor, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QLabel, QLineEdit, QPlainTextEdit, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog, QMessageBox,
    QScrollArea, QWidget,
)

from 项目UI import png_rc  # noqa: F401
from 项目UI.界面样式 import get_stylesheet, get_current_theme_id, THEMES
from 项目UI.弹窗样式 import add_green_glow, highlight_card_style, _create_popup_card
from 工具.android调试工具.ADB工具 import 格式化设备标签

# ANSI 转义序列过滤（字节级，在解码前过滤，避免 UTF-8 多字节字符干扰）
# 注意：所有分支都要求 ESC(0x1b) 前缀。曾经的 `\[[0-9;?]*[a-zA-Z~]` 分支不带
# ESC，会把正常文本当「被分割的残留序列」删掉——实测 [INFO] → NFO]、
# [kworker/0:1] → worker/0:1]、[E] → ]，输出被静默篡改，已删除。
_ANSI_BYTES_RE = re.compile(
    rb'\x1b\[[0-9;?]*[a-zA-Z~]'     # 标准 CSI 序列
    rb'|\x1b\][^\x07]*\x07'          # OSC 序列
    rb'|\x1b[()][AB012]'              # 字符集切换
    rb'|\x1b[>=<c]'                   # 其他单字节 ESC
    rb'|\x0f|\x0e|\x07'               # 移位/BEL 控制字符
)
# 「尚未收全」的 ANSI 序列前缀：只有匹配这个才允许扣留到下一包，
# 避免像旧实现那样把任意短数据或整段文本都扣在残余缓冲里。
_INCOMPLETE_ANSI_RE = re.compile(
    rb'^\x1b(?:\[[0-9;?]*|\][^\x07]*|[()]?)$'
)
# 文本级 ANSI 过滤（兼容旧代码路径）
_ANSI_RE = re.compile(
    r'\x1b\[[0-9;?]*[a-zA-Z~]'
    r'|\x1b\][^\x07]*\x07'
    r'|\x1b[()][AB012]'
    r'|\x1b[>=<c]'
    r'|\x0f|\x0e|\x07'
)


class _终端信号桥(QObject):
    """跨线程信号桥：交互式Shell 的回调在后台线程，通过信号回主线程。"""
    输出 = Signal(bytes)
    关闭 = Signal()
    # (shell或None, 错误信息, 设备序列号, 连接代际)
    连接完成 = Signal(object, str, str, int)


class _AdbShell行会话:
    """非自研模式下的 adb shell 行模式会话（每条命令独立 subprocess）。

    与 自研adb客户端.交互式Shell 接口对齐：on_output / on_close / 启动() /
    发送输入() / 关闭() / 已关闭，使上层 _连接完成/_发送输入/_断开终端 零改动。

    区别：
      - 不保持 PTY/工作目录/环境变量，每条命令独立 `adb -s serial shell <cmd>`
      - 无设备端回显，命令由 GUI 本地回显（`$ cmd`）
      - on_close 不会主动触发（无持久进程）；设备掉线时下一条命令报错
    """

    def __init__(self, adb_helper, serial, on_output, on_close):
        self._adb = adb_helper
        self._serial = serial
        self.on_output = on_output
        self.on_close = on_close
        self.已关闭 = False
        # 行模式无 PTY：stty 依赖 TTY 调用 tcgetattr，终端初始化需跳过宽度设置
        self.是行模式 = True

    def 启动(self):
        """行模式无需预连接，立即就绪。"""

    def 发送输入(self, data):
        if self.已关闭:
            return
        if isinstance(data, bytes):
            text = data.decode('utf-8', 'replace')
        else:
            text = data
        text = text.strip()
        if not text:
            return
        # 本地回显（无 PTY，设备端不回显命令）
        try:
            self.on_output(f'$ {text}\n'.encode('utf-8'))
        except Exception:
            pass
        import threading
        threading.Thread(target=self._执行, args=(text,), daemon=True).start()

    def _执行(self, cmd):
        try:
            out = self._adb.执行shell(self._serial, cmd, timeout=30)
            if out:
                if not out.endswith('\n'):
                    out += '\n'
                self.on_output(out.encode('utf-8', 'replace'))
        except Exception as e:
            try:
                self.on_output(f'[错误] {e}\n'.encode('utf-8'))
            except Exception:
                pass

    def 关闭(self):
        self.已关闭 = True


class ADB终端对话框(QDialog):
    """ADB 交互式终端弹窗。

    Parameters
    ----------
    主窗口 : QWidget
        主窗口引用，用于设备双向同步和获取 AdbHelper。
    parent : QWidget, optional
        父窗口。
    """

    # 弹窗内设备切换时发出，主窗口接收后同步三个设备选择栏
    设备已切换 = Signal(str)
    # 后台线程加载设备列表完成时发出（参数: 设备列表, 当前选中序列号）
    _设备列表已加载 = Signal(list, str)

    def __init__(self, 主窗口, parent=None):
        super().__init__(parent)
        self._主窗口 = 主窗口
        self._adb = 主窗口.adb
        self._shell = None  # 交互式Shell 实例
        self._信号桥 = _终端信号桥()
        self._信号桥.输出.connect(self._追加输出)
        self._信号桥.关闭.connect(self._会话已关闭)
        self._信号桥.连接完成.connect(self._连接完成)
        self._命令历史 = deque(maxlen=200)
        self._历史索引 = -1
        self._正在同步 = False
        # 输出管线状态
        self._输出残余 = b''         # 只存「尚未收全的 ANSI 序列」
        self._不完整行 = ''          # 尚未遇到 \n 的尾巴行（原始文本，含 \r）
        self._已渲染残留 = ''        # 上一次已渲染到文档末尾的尾巴行（重绘时先删除）
        # 增量 UTF-8 解码器：跨包被劈开的多字节字符由它内部缓冲，
        # 替代旧「UTF-8 失败就试 GBK」的启发式（那会把中文解成伪汉字）
        self._解码器 = codecs.getincrementaldecoder('utf-8')(errors='replace')
        # 连接代际：每次发起连接自增，用于丢弃过期回调（防旧连接覆盖新会话）
        self._连接代际 = 0
        self._当前终端序列号 = None

        # 加载自定义命令配置
        self._自定义命令配置文件 = '配置/终端自定义命令.json'
        self._自定义命令列表 = self._加载自定义命令()

        # 窗口设置
        self.setWindowTitle("adb shell 交互式终端")
        self.setWindowIcon(QIcon(":/Super_ADB.png"))
        self.setMinimumSize(900, 600)
        self.resize(1100, 750)
        self.setAcceptDrops(True)  # 支持拖文件进来追加路径
        self._theme_id = get_current_theme_id(self)
        self.setStyleSheet(get_stylesheet(self._theme_id))

        # 内层亮边卡片（与其他弹窗同款）
        self.card, _ = _create_popup_card(self, self._theme_id)
        self._构建UI()
        # 后台线程加载设备列表完成 → 主线程更新下拉框
        self._设备列表已加载.connect(self._设备列表加载完成)

    # ── 主题切换 ──

    def apply_theme(self, theme_id):
        """运行时切换主题：更新全局 QSS + 外发光。"""
        if theme_id not in THEMES or theme_id == self._theme_id:
            return
        self._theme_id = theme_id
        self.setStyleSheet(get_stylesheet(theme_id))
        self.card.setStyleSheet(highlight_card_style(theme_id))
        add_green_glow(self.card, accent=QColor(THEMES[theme_id]['accent']))
        if getattr(self, 'output', None) is not None:
            self.output.setStyleSheet(self._终端输出样式())
        self.update()

    # ── UI 构建 ──

    def _终端输出样式(self):
        """终端输出区样式：随主题配色（浅色主题白底深字、深色主题黑底浅字），保证文字清晰。"""
        t = THEMES.get(self._theme_id, THEMES.get('dark_cyan', {}))
        s = t.get('bg_window', '#252f3d').lstrip('#')
        try:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            dark = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0 < 0.55
        except Exception:
            dark = True
        bg = t['bg_input']
        fg = t['text_primary']
        accent = t['accent']
        if dark:
            scroll_bg, handle, hover, sel = '#1a1a1a', '#444444', '#555555', '#264f78'
        else:
            scroll_bg, handle, hover, sel = '#e8eaed', '#b8bcc2', '#9aa0a6', 'rgba(66,133,244,120)'
        return f'''
            QPlainTextEdit {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {accent};
                border-radius: 4px;
                padding: 6px 8px;
                selection-background-color: {sel};
                font-family: "Consolas", "Courier New", "Microsoft YaHei Mono", "SimSun", monospace;
            }}
            QScrollBar:vertical {{
                background: {scroll_bg};
                width: 12px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {handle};
                min-height: 30px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar:horizontal {{
                background: {scroll_bg};
                height: 12px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {handle};
                min-width: 30px;
                border-radius: 6px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
            }}
        '''

    def _构建UI(self):
        root = QVBoxLayout(self.card)
        root.setSpacing(8)
        root.setContentsMargins(14, 14, 14, 14)

        # 顶部工具栏：设备选择 + 连接按钮 + 控制按钮
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel('设备:'))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(240)
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.device_combo.currentIndexChanged.connect(self._设备选择变化)
        top.addWidget(self.device_combo)

        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.setFixedWidth(56)
        self.btn_refresh.clicked.connect(self._刷新设备)
        top.addWidget(self.btn_refresh)

        self.btn_ctrlc = QPushButton('Ctrl+C')
        self.btn_ctrlc.setToolTip('发送中断信号 (\\x03)')
        self.btn_ctrlc.clicked.connect(lambda: self._发送控制字符(b'\x03'))
        self.btn_ctrlc.setEnabled(False)
        top.addWidget(self.btn_ctrlc)

        self.btn_ctrl_d = QPushButton('Ctrl+D')
        self.btn_ctrl_d.setToolTip('发送 EOF (\\x04)，退出当前 shell')
        self.btn_ctrl_d.clicked.connect(lambda: self._发送控制字符(b'\x04'))
        self.btn_ctrl_d.setEnabled(False)
        top.addWidget(self.btn_ctrl_d)

        self.btn_clear = QPushButton('清屏')
        self.btn_clear.setFixedWidth(56)
        self.btn_clear.clicked.connect(self._清屏)
        top.addWidget(self.btn_clear)

        top.addStretch()
        self.status_label = QLabel('')
        self.status_label.setStyleSheet('color: #888;')
        top.addWidget(self.status_label)

        root.addLayout(top)

        # 终端输出区
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(5000)
        # 不自动换行：长行用水平滚动条（真实终端行为）
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # 滚动条策略：垂直/水平按需显示
        self.output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 等宽字体：优先用系统 FixedFont，确保中英文都等宽
        from PySide6.QtGui import QFontDatabase
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        if font.pointSize() <= 0:
            font.setPointSize(10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.output.setFont(font)
        # 输入框也用同样字体
        self._终端字体 = font
        # 制表符宽度 = 8 个空格宽度（标准终端对齐方式）
        font_metrics = self.output.fontMetrics()
        char_width = font_metrics.horizontalAdvance(' ')
        self.output.setTabStopDistance(char_width * 8)
        # 终端风格：随主题（浅色主题白底深字、深色主题黑底浅字）
        self.output.setStyleSheet(self._终端输出样式())
        # 文档默认边距
        doc = self.output.document()
        doc.setDocumentMargin(4)
        root.addWidget(self.output, 1)

        # 自定义命令快捷按钮行
        custom_row = QHBoxLayout()
        custom_row.setSpacing(6)
        # 自定义命令按钮滚动区域
        self.custom_scroll = QScrollArea()
        self.custom_scroll.setWidgetResizable(True)
        self.custom_scroll.setFixedHeight(38)
        self.custom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.custom_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.custom_scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        # 按钮容器
        self._custom_btn_container = QWidget()
        self._custom_btn_container.setStyleSheet('background: transparent;')
        self._自定义按钮容器 = QHBoxLayout(self._custom_btn_container)
        self._自定义按钮容器.setContentsMargins(2, 0, 2, 0)
        self._自定义按钮容器.setSpacing(6)
        self.custom_scroll.setWidget(self._custom_btn_container)
        custom_row.addWidget(self.custom_scroll, 1)
        # 右下角：自定义配置按钮
        self.btn_custom_config = QPushButton('⚙ 常用命令配置')
        self.btn_custom_config.setFixedWidth(130)
        self.btn_custom_config.setToolTip('配置自定义快捷命令')
        self.btn_custom_config.clicked.connect(self._打开自定义配置)
        custom_row.addWidget(self.btn_custom_config)
        root.addLayout(custom_row)
        # 初始刷新自定义按钮
        self._刷新自定义按钮()

        # 底部输入栏
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText('输入命令，回车发送；上下箭头翻历史')
        self.input_edit.setFont(self._终端字体)
        self.input_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.input_edit.installEventFilter(self)
        self.input_edit.returnPressed.connect(self._发送输入)
        self.input_edit.setEnabled(False)
        bottom.addWidget(self.input_edit, 1)

        self.btn_send = QPushButton('发送')
        self.btn_send.setFixedWidth(64)
        self.btn_send.clicked.connect(self._发送输入)
        self.btn_send.setEnabled(False)
        bottom.addWidget(self.btn_send)

        root.addLayout(bottom)

    # ── 设备同步（供主窗口调用）──

    def sync_devices(self, devices, select_serial=None):
        """主窗口刷新设备后调用，同步本弹窗的设备下拉框。

        Parameters
        ----------
        devices : list[dict]
            设备列表，每项含 'serial' 和 'state'。
        select_serial : str, optional
            优先选中的设备序列号。
        """
        self._正在同步 = True
        try:
            prev = self.device_combo.currentData()
            self.device_combo.blockSignals(True)
            self.device_combo.clear()
            # 防御：上游偶发传入 bool/None 等非列表值
            if not isinstance(devices, (list, tuple)):
                devices = []
            online = [d for d in devices if isinstance(d, dict) and d.get('state') == 'device']
            for d in online:
                self.device_combo.addItem(格式化设备标签(d), d.get('serial'))
            if not online:
                self.device_combo.addItem('（无设备）', None)
            # 选中优先级：传入的 select_serial > 之前选中的设备
            target = select_serial or prev
            idx = self.device_combo.findData(target) if target else -1
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
            self.device_combo.blockSignals(False)
            # 会话跟随：下拉框选中的设备若与当前会话不一致就重连。
            # 旧实现用 blockSignals 改了选项却不通知会话，会出现
            # 「界面显示 B 设备、命令实际发往 A 设备」的静默错发。
            new_serial = self.device_combo.currentData()
            if (new_serial and self._shell is not None
                    and not self._shell.已关闭
                    and new_serial != self._当前终端序列号):
                QTimer.singleShot(0, lambda s=new_serial: self._连接终端(s))
        finally:
            self._正在同步 = False

    def _设备选择变化(self, index):
        """用户在弹窗内切换设备 → 自动连接终端 + 通知主窗口同步。"""
        if self._正在同步:
            return
        serial = self.device_combo.itemData(index)
        if not serial:
            return
        # 选中设备后立即可输入（连接在后台进行，不阻塞输入）
        self.input_edit.setEnabled(True)
        self.btn_send.setEnabled(True)
        # 通知主窗口同步三个设备选择栏
        self.设备已切换.emit(serial)
        # 自动连接终端
        self._连接终端(serial)
        # 焦点给到输入框
        QTimer.singleShot(100, self.input_edit.setFocus)

    def _刷新设备(self):
        """点击刷新按钮 → 调用主窗口的刷新设备（会同步所有下拉框）。"""
        try:
            self._主窗口.刷新设备()
        except Exception as e:
            # 旧实现 except: pass，刷新失败零反馈
            self.status_label.setText(f'刷新失败: {e}')

    # ── 终端连接 / 断开 ──

    def _连接终端(self, serial):
        """连接到指定设备的交互式 shell（后台线程，不阻塞 UI）。"""
        # 静默关闭旧会话：不能让 _断开终端() → _已断开UI() 把输入框禁用。
        # 旧实现在这里先禁用、连接失败路径又不恢复，导致「下拉框已选设备、
        # 输入框却永久灰掉，只能重选设备」的死锁。
        if self._shell:
            try:
                self._shell.关闭()
            except Exception:
                pass
        self._shell = None
        self._当前终端序列号 = None
        # 连接代际自增：过期回调据此丢弃
        self._连接代际 += 1
        代际 = self._连接代际
        # 切换设备/重连时清屏并丢弃旧设备残留的输出缓冲
        self.output.clear()
        self._重置输出缓冲()
        self.status_label.setText('正在打开终端...')

        import threading
        def _do_connect():
            try:
                on_out = lambda data: self._信号桥.输出.emit(data)
                on_close = lambda: self._信号桥.关闭.emit()
                if getattr(self._adb, '_用自研adb', False):
                    连接源 = self._adb._获取自研adb(serial)
                    if 连接源 is None:
                        self._信号桥.连接完成.emit(
                            None, '自研 ADB 客户端不可用', serial, 代际)
                        return
                    from 工具.android调试工具.自研adb.自研adb客户端 import 交互式Shell
                    shell = 交互式Shell(连接源, on_output=on_out, on_close=on_close)
                else:
                    # 非自研模式：行模式会话（每条命令独立 adb shell subprocess，
                    # 不依赖自研客户端，也不会去抢设备 5555 槽位）
                    shell = _AdbShell行会话(self._adb, serial,
                                            on_output=on_out, on_close=on_close)
                shell.启动()
                self._信号桥.连接完成.emit(shell, '', serial, 代际)
            except Exception as e:
                self._信号桥.连接完成.emit(None, str(e), serial, 代际)
        threading.Thread(target=_do_connect, daemon=True).start()

    def _连接完成(self, shell, err, serial, 代际):
        """后台连接完成 → 主线程更新 UI。"""
        # 竞态防护：用户连接期间又切了设备，丢弃过期回调；已建立的 shell
        # 无人认领必须关掉，否则设备端残留 shell 进程 + 连接泄漏
        if 代际 != self._连接代际:
            if shell is not None:
                try:
                    shell.关闭()
                except Exception:
                    pass
            return
        if shell is None:
            self.status_label.setText(f'连接失败: {err}（可重选设备或点刷新重试）')
            self._shell = None
            self._当前终端序列号 = None
            # 保持输入可用：_发送输入 在无 shell 时会自动重连并重发本次命令
            self.input_edit.setEnabled(True)
            self.btn_send.setEnabled(True)
            return
        self._shell = shell
        self._当前终端序列号 = serial
        self._已连接UI()
        self.status_label.setText(f'已连接 {serial}')
        self.input_edit.setFocus()
        # 连接后刷新残余，确保 shell 提示符立即显示
        QTimer.singleShot(200, self._刷新残余)
        # 设置 PTY 窗口宽度为 200 列
        QTimer.singleShot(250, self._设置终端宽度)

    def _设置终端宽度(self, cols: int = 200):
        """通过 stty 设置 PTY 窗口宽度，然后在 GUI 层面清理多余行。

        长命令超过默认 80 列时，mksh 会做行编辑重绘（输出 \\r、ANSI 光标
        移动、清除行等序列），本终端只过滤 ANSI 不模拟效果，会导致显示
        错乱。设置足够宽的终端可从根源避免折行。
        """
        if not self._shell or self._shell.已关闭:
            return
        # 行模式会话无 PTY：stty 对非 TTY 调用 tcgetattr 会报
        # "Inappropriate ioctl for device"，直接跳过宽度设置。
        if getattr(self._shell, '是行模式', False):
            return
        # 发送 stty 命令设置宽度（toybox 自带，绝大多数 Android 设备可用）
        self._shell.发送输入(f'stty cols {cols}\n')
        # 等 stty 执行完，清掉它自己产生的回显行（只清这些行，不动真实输出）。
        # 二次清理：慢设备上 stty 回显可能晚于 200ms 到达，首次清理会漏掉，
        # 800ms 再清一次兜底（幂等，只删含 'stty cols' 的行）。
        QTimer.singleShot(200, self._清理初始化回显)
        QTimer.singleShot(800, self._清理初始化回显)

    def _清理初始化回显(self):
        """删除连接初始化产生的噪声行（`stty cols ...` 回显），保留设备真实输出。

        旧实现 `_只保留最后一行提示符` 会无条件删除「除最后一行以外的全部
        内容」，连接后 450ms 内到达的设备欢迎信息/启动输出会被整段抹掉
        （实测 'Android 9 / API 28' + 'uid=2000 shell' 被清空）。
        """
        doc = self.output.document()
        if doc.blockCount() <= 1:
            return
        待删 = []
        V噪声关键字 = ('stty cols', 'tcgetattr', 'Inappropriate ioctl')
        block = doc.firstBlock()
        while block.isValid():
            if any(k in block.text() for k in V噪声关键字):
                待删.append(block.blockNumber())
            block = block.next()
        if not 待删:
            return
        cursor = self.output.textCursor()
        cursor.beginEditBlock()
        for num in reversed(待删):
            b = doc.findBlockByNumber(num)
            if not b.isValid():
                continue
            c = QTextCursor(b)
            c.select(QTextCursor.SelectionType.LineUnderCursor)
            c.removeSelectedText()
            c.deleteChar()   # 连同该行换行一起删掉，避免留下空行
        cursor.endEditBlock()

    def _断开终端(self):
        """断开当前终端连接。"""
        if self._shell:
            try:
                self._shell.关闭()
            except Exception:
                pass
        self._shell = None
        self._已断开UI()

    def _会话已关闭(self):
        """设备主动关闭或连接断开。"""
        self._shell = None
        self._当前终端序列号 = None
        self._已断开UI()
        self.status_label.setText('会话已结束')
        self._追加输出('[连接已关闭]\n'.encode('utf-8'))

    def _已连接UI(self):
        self.btn_ctrlc.setEnabled(True)
        self.btn_ctrl_d.setEnabled(True)
        self.input_edit.setEnabled(True)
        self.btn_send.setEnabled(True)

    def _已断开UI(self):
        self.btn_ctrlc.setEnabled(False)
        self.btn_ctrl_d.setEnabled(False)
        self.input_edit.setEnabled(False)
        self.btn_send.setEnabled(False)

    # ── 输入 / 输出 ──

    def _发送输入(self):
        text = self.input_edit.text()
        if not self._shell or self._shell.已关闭:
            # 未连接时提示用户选择设备
            serial = self.device_combo.currentData()
            if serial:
                self.status_label.setText('正在连接...')
                self._连接终端(serial)
                # 连接后重发本次输入
                if text:
                    QTimer.singleShot(500, lambda: self._重发输入(text))
            else:
                self.status_label.setText('请先选择设备')
            return
        if not text:
            self._shell.发送输入('\n')
            return
        # 智能预处理：去掉 adb shell / adb -s xxx shell 前缀（已在 shell 里，不需要前缀）
        text = self._预处理命令(text)
        if not text:
            return  # 只有 adb shell 没有后续命令，忽略
        self._命令历史.append(text)
        self._历史索引 = -1
        self._shell.发送输入(text + '\n')
        self.input_edit.clear()
        # 发送后刷新残余缓冲区，确保新提示符立即显示
        QTimer.singleShot(100, self._刷新残余)

    def _预处理命令(self, text: str) -> str:
        """智能去掉 adb shell 前缀（已在交互式 shell 里，不需要前缀）。

        支持:
          adb shell ls -la        → ls -la
          adb -s 1.2.3.4 shell ls → ls
          ADB SHELL ls            → ls（大小写不敏感）
        """
        t = text.strip()
        # 匹配 adb [可选 -s serial] shell 前缀
        m = re.match(r'^adb\s+(?:-s\s+\S+\s+)?shell\s*(.*)$', t, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return text

    def _重发输入(self, text):
        """连接建立后重发之前输入的命令。"""
        if self._shell and not self._shell.已关闭 and text:
            text = self._预处理命令(text)
            if text:
                self._shell.发送输入(text + '\n')
                self.input_edit.clear()

    def _发送控制字符(self, data: bytes):
        if self._shell and not self._shell.已关闭:
            self._shell.发送输入(data)

    def _追加输出(self, data: bytes):
        """将设备输出追加到终端显示区（主线程）。

        处理链：ANSI 残留缓冲 → 增量 UTF-8 解码 → 控制字符清理
        → 行合并（含 \\r 覆盖模拟）→ 制表符展开 → 渲染。

        与旧实现的三点关键差异：
          1. 彻底去掉「≤8 字节一律扣留」的门槛。旧逻辑会把 pwd/echo/id 这类
             短输出永久吞掉（实测 pwd 的 "/\\r\\n" 显示为空，连 _刷新残余 都
             无效，因为残余会被再次回灌）。
          2. 不完整的尾巴行也实时渲染；下次数据到达时先删除上次渲染的尾巴
             再重绘。旧实现只在收到 \\n 时输出，导致 PTY 提示符和命令回显
             （都没有换行）永远不显示——连上设备后终端一片空白。
          3. 解码改用增量解码器，中文被包边界劈开时不再回退 GBK。
        """
        if not data:
            return

        # ── 1. 只扣留「尚未收全」的 ANSI 序列（ESC 起始且未闭合）──
        full = self._输出残余 + data
        idx = full.rfind(b'\x1b')
        if idx >= 0 and len(full) - idx <= 64 and _INCOMPLETE_ANSI_RE.match(full[idx:]):
            self._输出残余 = full[idx:]
            ready = full[:idx]
        else:
            self._输出残余 = b''
            ready = full
        if not ready:
            return

        filtered = _ANSI_BYTES_RE.sub(b'', ready)
        if not filtered:
            return

        # ── 2. 增量解码（跨包多字节字符由解码器内部缓冲）──
        text = self._解码器.decode(filtered)
        if not text:
            return
        # 控制字符清理：保留 \n \t \r（\r 用于模拟回行覆盖）
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        if not text:
            return

        # ── 3. 行合并：整行入显示区，尾巴行单独渲染 ──
        parts = (self._不完整行 + text).split('\n')
        self._不完整行 = parts.pop() if parts else ''
        out_text = ''.join(
            self._展开制表符(self._处理回车(ln)) + '\n' for ln in parts)
        tail = (self._展开制表符(self._处理回车(self._不完整行))
                if self._不完整行 else '')

        # ── 4. 先删掉上次渲染的尾巴行，再整段写入 ──
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self._已渲染残留:
            cursor.movePosition(QTextCursor.MoveOperation.Left,
                               QTextCursor.MoveMode.KeepAnchor,
                               len(self._已渲染残留))
            cursor.removeSelectedText()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if out_text or tail:
            cursor.insertText(out_text + tail)
        self._已渲染残留 = tail
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    @staticmethod
    def _智能解码(data: bytes) -> str:
        """智能解码：优先 UTF-8，有乱码则尝试 GBK，最后 Latin-1。"""
        # 先试 UTF-8 严格解码
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            pass
        # UTF-8 严格失败，试 GBK（Android 部分应用/中文 ROM 可能用 GBK）
        try:
            return data.decode('gbk')
        except UnicodeDecodeError:
            pass
        # 最后用 UTF-8 替换模式（不会失败，但可能有 �）
        return data.decode('utf-8', errors='replace')

    @staticmethod
    def _字符显示宽度(ch: str) -> int:
        """计算字符的终端显示宽度（ASCII=1，中日韩等宽字符=2）。"""
        code = ord(ch)
        # CJK 统一表意文字、全角字符等显示宽度为 2
        if (
            0x1100 <= code <= 0x115F or  # Hangul Jamo
            0x2E80 <= code <= 0x303E or  # CJK Radicals
            0x3041 <= code <= 0x33FF or  # Hiragana/Katakana/CJK
            0x3400 <= code <= 0x4DBF or  # CJK Extension A
            0x4E00 <= code <= 0x9FFF or  # CJK Unified
            0xA000 <= code <= 0xA4CF or  # Yi
            0xAC00 <= code <= 0xD7A3 or  # Hangul Syllables
            0xF900 <= code <= 0xFAFF or  # CJK Compatibility
            0xFE30 <= code <= 0xFE4F or  # CJK Compatibility Forms
            0xFF00 <= code <= 0xFF60 or  # Fullwidth Forms
            0xFFE0 <= code <= 0xFFE6     # Fullwidth Signs
        ):
            return 2
        return 1

    @staticmethod
    def _处理回车(line: str) -> str:
        """模拟终端中 \\r（回车）的真实行为：回到行首，后续内容从行首开始覆盖。

        与简单删除 \\r 不同，此方法正确处理 shell 行编辑中的"清除行"操作
        （\\r + 大量空格 + \\r），避免长命令回显时出现大段空白。

        规则:
          - 每个 \\r 后的片段从行首开始覆盖当前内容
          - 新片段比当前行短时，未被覆盖的尾部保留
          - 空格也是可打印字符，会覆盖目标位置

        示例:
          'abc\\rdef'      → 'def'
          'abc\\rde'       → 'dec'
          'abc\\r   \\rxy' → 'xy'
        """
        if '\r' not in line:
            return line
        current = ''
        for part in line.split('\r'):
            if len(part) >= len(current):
                current = part
            else:
                current = part + current[len(part):]
        return current

    @classmethod
    def _展开制表符(cls, text: str, tab_size: int = 8) -> str:
        """把制表符展开为空格（按 tab_size 对齐，含中文宽度计算）。

        确保多列数据在等宽字体下严格对齐，即使含中文字符。
        """
        if '\t' not in text:
            return text
        lines = text.split('\n')
        result = []
        for line in lines:
            if '\t' not in line:
                result.append(line)
                continue
            expanded = []
            col = 0  # 当前显示列位置（按字符宽度计算）
            for ch in line:
                if ch == '\t':
                    # 计算到下一个 tab 边界需要多少空格
                    spaces = tab_size - (col % tab_size)
                    expanded.append(' ' * spaces)
                    col += spaces
                else:
                    expanded.append(ch)
                    col += cls._字符显示宽度(ch)
            result.append(''.join(expanded))
        return '\n'.join(result)

    @classmethod
    def _对齐空格分列(cls, text: str) -> str:
        """对空格分隔的多列输出进行对齐（含中文宽度计算）。

        只对连续 2 行以上、列数相同（>=2列）的表格行做对齐，
        避免破坏普通文本/命令输出的格式。
        列分隔：2个以上连续空格。
        """
        lines = text.split('\n')
        if len(lines) < 2:
            return text

        # 解析每行：(原始行, 缩进, 列列表)
        parsed = []
        for line in lines:
            stripped = line.lstrip()
            indent_len = len(line) - len(stripped)
            # 按2个以上空格分割列
            cols = re.split(r' {2,}', stripped) if stripped else []
            parsed.append((line, indent_len, cols))

        # 找出连续的表格行块（列数>=2且相邻行列数相同）
        i = 0
        while i < len(parsed):
            line, indent, cols = parsed[i]
            ncols = len(cols)
            if ncols < 2:
                i += 1
                continue
            # 找连续相同列数的行
            j = i + 1
            while j < len(parsed) and len(parsed[j][2]) == ncols:
                j += 1
            block_len = j - i
            if block_len < 2:
                i = j
                continue
            # 计算该块每列最大宽度
            col_widths = [0] * ncols
            for k in range(i, j):
                _, _, c = parsed[k]
                for ci, col in enumerate(c):
                    w = sum(cls._字符显示宽度(ch) for ch in col)
                    col_widths[ci] = max(col_widths[ci], w)
            # 重新对齐该块
            for k in range(i, j):
                orig, indent_len, c = parsed[k]
                indent_str = orig[:indent_len]
                aligned_parts = []
                for ci, col in enumerate(c):
                    if ci < ncols - 1:
                        w = sum(cls._字符显示宽度(ch) for ch in col)
                        padding = col_widths[ci] - w + 2  # 列间距2空格
                        aligned_parts.append(col + ' ' * padding)
                    else:
                        aligned_parts.append(col)
                new_line = indent_str + ''.join(aligned_parts)
                parsed[k] = (new_line, indent_len, c)
            i = j

        return '\n'.join(line for line, _, _ in parsed)

    def _刷新残余(self):
        """把视图滚到最新内容。

        旧实现会把字节残余回灌 _追加输出，但 ≤8 字节的残余会被再次扣留，
        等于无效刷新（实测 hi\\n 刷新后仍在缓冲里）。现在短输出和尾巴行都已
        实时渲染，这里只需保证光标/滚动条跟上。
        """
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def _重置输出缓冲(self):
        """清空输出管线全部中间状态（切设备、重连、清屏时调用）。

        旧实现清屏只调 output.clear()，字节残余和尾巴行仍留在内存里，
        下一段输出到达时会先把旧设备/旧内容拼进来（实测 'OLD0123456789'）。
        """
        self._输出残余 = b''
        self._不完整行 = ''
        self._已渲染残留 = ''
        try:
            self._解码器.reset()
        except Exception:
            pass

    def _清屏(self):
        self.output.clear()
        self._重置输出缓冲()

    # ── 命令历史 ──

    def _历史向上(self):
        if not self._命令历史:
            return
        if self._历史索引 < 0:
            self._历史索引 = len(self._命令历史) - 1
        elif self._历史索引 > 0:
            self._历史索引 -= 1
        self.input_edit.setText(self._命令历史[self._历史索引])

    def _历史向下(self):
        if not self._命令历史 or self._历史索引 < 0:
            return
        if self._历史索引 < len(self._命令历史) - 1:
            self._历史索引 += 1
            self.input_edit.setText(self._命令历史[self._历史索引])
        else:
            self._历史索引 = -1
            self.input_edit.clear()

    # ── 窗口生命周期 ──

    def eventFilter(self, obj, event):
        """输入框的事件过滤器：拦截上下箭头翻命令历史。"""
        if obj is self.input_edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._历史向上()
                return True
            if key == Qt.Key.Key_Down:
                self._历史向下()
                return True
        return super().eventFilter(obj, event)

    # ── 拖拽文件：拖进来在输入框光标处追加文件路径（跟 cmd 一样）──

    def dragEnterEvent(self, event):
        """文件拖入窗口时接受拖拽。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            # 拖拽时高亮输入框
            self.input_edit.setStyleSheet(self.input_edit.styleSheet() + '''
                QLineEdit { border: 2px solid #1de9b6; }
            ''')
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """拖拽离开时恢复输入框样式。"""
        self._恢复输入框样式()

    def dropEvent(self, event):
        """文件放下时在输入框光标位置追加文件路径。"""
        self._恢复输入框样式()
        paths = []
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path:
                paths.append(local_path)
        if not paths:
            event.ignore()
            return
        # 在输入框当前光标位置插入路径（多个文件用空格分隔）
        cursor_pos = self.input_edit.cursorPosition()
        current_text = self.input_edit.text()
        # 构建要插入的文本：路径含空格时加双引号（cmd 风格）
        insert_parts = []
        for p in paths:
            if ' ' in p:
                insert_parts.append(f'"{p}"')
            else:
                insert_parts.append(p)
        insert_text = ' '.join(insert_parts)
        # 如果光标不在开头且前一个字符不是空格，前面加空格
        if cursor_pos > 0 and current_text[cursor_pos - 1] not in (' ', '\t'):
            insert_text = ' ' + insert_text
        # 插入到光标位置
        new_text = current_text[:cursor_pos] + insert_text + current_text[cursor_pos:]
        self.input_edit.setText(new_text)
        # 光标移到插入内容之后
        self.input_edit.setCursorPosition(cursor_pos + len(insert_text))
        self.input_edit.setFocus()
        event.acceptProposedAction()

    def _恢复输入框样式(self):
        """恢复输入框默认样式（去掉拖拽高亮边框）。"""
        self.input_edit.setStyleSheet('')

    def closeEvent(self, event):
        """窗口关闭时断开终端连接。"""
        self._断开终端()
        super().closeEvent(event)

    def showEvent(self, event):
        """窗口显示时异步加载设备列表（不阻塞UI，避免弹窗延迟出现）。"""
        super().showEvent(event)
        # 直接用主窗口已加载好的设备列表，不需要重新扫描。
        # 注意：主窗口 deviceCombo 的 itemData 只存 serial，型号在 itemText（"型号  [serial]"）
        # 和 adb._设备名缓存 里；只取 serial 重建会让标签退化成 "serial [serial]"。
        try:
            devices = []
            combo = getattr(self._主窗口, 'deviceCombo', None)
            if combo:
                缓存 = getattr(getattr(self._主窗口, 'adb', None), '_设备名缓存', None) or {}
                for i in range(combo.count()):
                    serial = combo.itemData(i)
                    if serial:
                        型号 = 缓存.get(serial) or self._从标签取型号(combo.itemText(i), serial)
                        devices.append({'serial': serial, 'model': 型号, 'state': 'device'})
            current = self._主窗口.当前序列号()
            self._设备列表已加载.emit(devices, current or '')
        except Exception:
            pass

    @staticmethod
    def _从标签取型号(标签, serial):
        """从 "型号  [serial]" 形式的标签反解型号；取不到（标签就是 serial）返回空串。"""
        标签 = 标签 or ''
        尾部 = f'[{serial}]'
        if serial and 标签.endswith(尾部):
            型号 = 标签[:-len(尾部)].strip()
            return '' if 型号 == serial else 型号
        return '' if 标签 == serial else 标签

    def _设备列表加载完成(self, devices, current):
        """后台线程加载完成 → 主线程更新下拉框。"""
        self.sync_devices(devices, current or None)
        # 如果已有选中设备，启用输入框、聚焦，并自动连接终端
        if current and self.device_combo.findData(current) >= 0:
            self.input_edit.setEnabled(True)
            self.btn_send.setEnabled(True)
            QTimer.singleShot(100, self.input_edit.setFocus)
            # 自动连接到当前选中的设备（延迟避免与 UI 初始化竞争）
            if self._shell is None or self._shell.已关闭:
                QTimer.singleShot(300, lambda: self._连接终端(current))

    # ── 自定义快捷命令 ──

    def _加载自定义命令(self):
        """从配置文件加载自定义命令列表。"""
        from 工具.android调试工具.ADB工具 import 加载json配置
        data = 加载json配置(self._自定义命令配置文件)
        if isinstance(data, list):
            return data
        return []

    def _保存自定义命令(self):
        """保存自定义命令列表到配置文件。"""
        from 工具.android调试工具.ADB工具 import 保存json配置
        保存json配置(self._自定义命令配置文件, self._自定义命令列表)

    def _刷新自定义按钮(self):
        """根据配置刷新自定义命令按钮显示。"""
        # 清除旧按钮
        while self._自定义按钮容器.count():
            item = self._自定义按钮容器.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        # 创建新按钮（固定宽度，不拉伸）
        for cmd in self._自定义命令列表:
            name = cmd.get('name', '')
            if not name:
                continue
            btn = QPushButton(name)
            btn.setFixedHeight(28)
            btn.setMinimumWidth(80)
            btn.setMaximumWidth(160)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setToolTip(cmd.get('command', ''))
            cmd_text = cmd.get('command', '')
            btn.clicked.connect(lambda checked=False, t=cmd_text: self._填充命令到输入框(t))
            self._自定义按钮容器.addWidget(btn)

    def _填充命令到输入框(self, command):
        """点击自定义按钮 → 把命令填充到输入框。"""
        self.input_edit.setText(command)
        self.input_edit.setFocus()

    def _打开自定义配置(self):
        """打开自定义命令配置对话框。"""
        dlg = _自定义命令配置对话框(self._自定义命令列表, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._自定义命令列表 = dlg.获取配置()
            self._保存自定义命令()
            self._刷新自定义按钮()


class _自定义命令配置对话框(QDialog):
    """自定义快捷命令配置对话框：增删改查。"""

    def __init__(self, commands, parent=None):
        super().__init__(parent)
        # 关闭即释放：旧实现每次开关都 new 一个 QDialog 且不释放（轻微内存泄漏）
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._commands = [c.copy() for c in commands]  # 深拷贝，取消时不影响原列表
        self.setWindowTitle('自定义快捷命令配置')
        self.setMinimumSize(560, 460)
        self._theme_id = get_current_theme_id(self)
        self.setStyleSheet(get_stylesheet(self._theme_id))

        # 内层亮边卡片（与其他弹窗同款）
        self.card, _ = _create_popup_card(self, self._theme_id)

        self._构建UI()
        self._刷新列表()

    def _构建UI(self):
        root = QVBoxLayout(self.card)
        root.setSpacing(8)
        root.setContentsMargins(14, 14, 14, 14)

        # 命令表格（两列：名称 + 内容）
        self.table_widget = QTableWidget(0, 2)
        self.table_widget.setHorizontalHeaderLabels(['名称', '内容'])
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_widget.doubleClicked.connect(self._编辑当前选中)
        # 隐藏行号列
        self.table_widget.verticalHeader().setVisible(False)
        # 表格样式：跟随主题 accent 颜色
        accent_rgb = THEMES[self._theme_id]['accent']  # 格式: 'rgb(r,g,b)'
        # 提取 rgb 数值，方便生成带透明度的 rgba
        import re
        nums = re.findall(r'\d+', accent_rgb)
        r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
        self.table_widget.setStyleSheet(f'''
            QTableWidget {{
                background-color: transparent;
                border: 1px solid rgba({r}, {g}, {b}, 0.3);
                border-radius: 6px;
                gridline-color: rgba({r}, {g}, {b}, 0.15);
                outline: none;
            }}
            QTableWidget::item {{
                padding: 6px 8px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background-color: rgba({r}, {g}, {b}, 0.15);
                color: #ffffff;
            }}
            QHeaderView::section {{
                background-color: rgba({r}, {g}, {b}, 0.1);
                color: {accent_rgb};
                border: none;
                border-bottom: 1px solid rgba({r}, {g}, {b}, 0.3);
                padding: 6px 8px;
                font-weight: bold;
            }}
            QHeaderView::section:first {{
                border-top-left-radius: 6px;
            }}
            QHeaderView::section:last {{
                border-top-right-radius: 6px;
            }}
        ''')
        root.addWidget(self.table_widget, 1)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_add = QPushButton('添加')
        self.btn_add.clicked.connect(self._添加命令)
        btn_row.addWidget(self.btn_add)

        self.btn_edit = QPushButton('编辑')
        self.btn_edit.clicked.connect(self._编辑当前选中)
        btn_row.addWidget(self.btn_edit)

        self.btn_del = QPushButton('删除')
        self.btn_del.clicked.connect(self._删除命令)
        btn_row.addWidget(self.btn_del)

        btn_row.addStretch()

        self.btn_ok = QPushButton('确定')
        self.btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_ok)

        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        root.addLayout(btn_row)

    def _刷新列表(self):
        self.table_widget.setRowCount(len(self._commands))
        for i, cmd in enumerate(self._commands):
            name_item = QTableWidgetItem(cmd.get('name', ''))
            name_item.setData(Qt.ItemDataRole.UserRole, i)
            self.table_widget.setItem(i, 0, name_item)
            self.table_widget.setItem(i, 1, QTableWidgetItem(cmd.get('command', '')))
            self.table_widget.setRowHeight(i, 32)

    def _添加命令(self):
        dlg = _命令编辑对话框(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, command = dlg.获取值()
            if name:
                self._commands.append({'name': name, 'command': command})
                self._刷新列表()

    def _编辑当前选中(self):
        row = self.table_widget.currentRow()
        if row < 0:
            return
        self._编辑命令_at(row)

    def _编辑命令_at(self, idx):
        if idx < 0 or idx >= len(self._commands):
            return
        old = self._commands[idx]
        dlg = _命令编辑对话框(
            name=old.get('name', ''),
            command=old.get('command', ''),
            parent=self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, command = dlg.获取值()
            if name:
                self._commands[idx] = {'name': name, 'command': command}
                self._刷新列表()

    def _删除命令(self):
        row = self.table_widget.currentRow()
        if row < 0 or row >= len(self._commands):
            return
        name = self._commands[row].get('name', '')
        reply = QMessageBox.question(
            self, '确认删除', f'确定删除命令「{name}」吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self._commands[row]
            self._刷新列表()

    def 获取配置(self):
        """返回当前配置的命令列表。"""
        return self._commands


class _命令编辑对话框(QDialog):
    """编辑单个命令的对话框：名称 + 内容同时编辑。"""

    def __init__(self, name='', command='', parent=None):
        super().__init__(parent)
        # 关闭即释放：避免每次打开编辑框都残留一个未释放的 QDialog
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle('编辑命令')
        self.setMinimumSize(440, 260)
        self._theme_id = get_current_theme_id(self)
        self.setStyleSheet(get_stylesheet(self._theme_id))

        # 内层亮边卡片（与其他弹窗同款）
        self.card, _ = _create_popup_card(self, self._theme_id)

        self._构建UI(name, command)

    def _构建UI(self, name, command):
        root = QVBoxLayout(self.card)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # 名称输入
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel('名称:'))
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText('按钮显示名称，如：查看日志')
        name_layout.addWidget(self.name_edit, 1)
        root.addLayout(name_layout)

        # 内容输入（多行）
        root.addWidget(QLabel('命令内容:'))
        self.command_edit = QPlainTextEdit(command)
        self.command_edit.setPlaceholderText('要执行的命令，如：logcat -d | grep AndroidRuntime')
        root.addWidget(self.command_edit, 1)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_ok = QPushButton('确定')
        self.btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_ok)
        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

    def 获取值(self):
        """返回 (名称, 内容)。"""
        return self.name_edit.text().strip(), self.command_edit.toPlainText().strip()
