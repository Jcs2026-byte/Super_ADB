# -*- coding: utf-8 -*-
"""
ADB 交互式终端弹窗
==================
自研 ADB 模式专属：点击「便携工具 → ADB命令行」打开的独立窗口。
类似 adb shell 不带参数进入的交互式终端，可持续敲命令、实时看输出。

功能:
  - 设备下拉框列所有已连接设备，点击自动连接终端
  - 与主窗口三个设备选择栏双向同步
  - 交互式 shell（自研adb客户端.交互式Shell），支持 TCP + USB
  - 命令历史（上下箭头）、Ctrl+C / Ctrl+D、清屏
  - ANSI 转义序列过滤，深色终端风格

样式:
  - 复用 弹窗样式.py 的 _create_popup_card + add_green_glow
  - 与 JSON/MD5/时间戳弹窗同款青绿色高亮边框 + 外发光
  - apply_theme() 支持运行时主题切换
"""

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
_ANSI_BYTES_RE = re.compile(
    rb'\x1b\[[0-9;?]*[a-zA-Z~]'     # 标准 CSI 序列
    rb'|\x1b\][^\x07]*\x07'          # OSC 序列
    rb'|\x1b[()][AB012]'              # 字符集切换
    rb'|\x1b[>=<c]'                   # 其他单字节 ESC
    rb'|\[[0-9;?]*[a-zA-Z~]'          # 被分割后残留的无 ESC CSI 序列
    rb'|\x0f|\x0e|\x07'               # 移位/BEL 控制字符
)
# 文本级 ANSI 过滤（兼容旧代码路径）
_ANSI_RE = re.compile(
    r'\x1b\[[0-9;?]*[a-zA-Z~]'
    r'|\x1b\][^\x07]*\x07'
    r'|\x1b[()][AB012]'
    r'|\x1b[>=<c]'
    r'|\[[0-9;?]*[a-zA-Z~]'
    r'|\x0f|\x0e|\x07'
)


class _终端信号桥(QObject):
    """跨线程信号桥：交互式Shell 的回调在后台线程，通过信号回主线程。"""
    输出 = Signal(bytes)
    关闭 = Signal()


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
        self._命令历史 = deque(maxlen=200)
        self._历史索引 = -1
        self._正在同步 = False
        self._输出残余 = b''  # 防止 ANSI 序列被 ADB 流分割的残余缓冲区
        self._不完整行 = ''  # 行级残余缓冲：上一包末尾不完整的行

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
        self.update()

    # ── UI 构建 ──

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
        # 终端风格：深色背景 + 浅色文字 + 滚动条样式
        self.output.setStyleSheet('''
            QPlainTextEdit {
                background-color: #0c0c0c;
                color: #cccccc;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 6px 8px;
                selection-background-color: #264f78;
                font-family: "Consolas", "Courier New", "Microsoft YaHei Mono", "SimSun", monospace;
            }
            QScrollBar:vertical {
                background: #1a1a1a;
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #444444;
                min-height: 30px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: #555555;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background: #1a1a1a;
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #444444;
                min-width: 30px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #555555;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
        ''')
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
        except Exception:
            pass

    # ── 终端连接 / 断开 ──

    def _连接终端(self, serial):
        """连接到指定设备的交互式 shell。"""
        # 先断开已有连接
        self._断开终端()
        # 切换设备时自动清屏，避免新旧设备输出混杂
        self.output.clear()

        try:
            连接源 = self._adb._获取自研adb(serial)
            if 连接源 is None:
                self.status_label.setText('自研 ADB 客户端不可用')
                return

            self.status_label.setText('正在打开终端...')
            from 工具.android调试工具.自研adb.自研adb客户端 import 交互式Shell
            self._shell = 交互式Shell(
                连接源,
                on_output=lambda data: self._信号桥.输出.emit(data),
                on_close=lambda: self._信号桥.关闭.emit(),
            )
            self._shell.启动()
            self._已连接UI()
            self.status_label.setText(f'已连接 {serial}')
            self.input_edit.setFocus()
            # 连接后刷新残余，确保 shell 提示符立即显示
            QTimer.singleShot(200, self._刷新残余)
        except Exception as e:
            self.status_label.setText(f'连接失败: {e}')
            self._shell = None

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

        字节级残余缓冲（防ANSI序列分割）→ 行级缓冲（防行分割）→
        制表符展开 → 输出。
        """
        # ── 1. 字节级残余缓冲：只在末尾有 ESC 时保留（ANSI序列以ESC开头）──
        full = self._输出残余 + data
        filtered = _ANSI_BYTES_RE.sub(b'', full)
        if len(filtered) > 8 and b'\x1b' in filtered[-8:]:
            self._输出残余 = filtered[-8:]
            output_bytes = filtered[:-8]
        elif len(filtered) > 8:
            self._输出残余 = b''
            output_bytes = filtered
        else:
            self._输出残余 = filtered
            output_bytes = b''
        if not output_bytes:
            return

        # ── 2. 解码 + 过滤控制字符 ──
        text = self._智能解码(output_bytes)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        # 换行符处理：\r\n → \n；单独的 \r（回车）去掉
        text = text.replace('\r\n', '\n').replace('\r', '')
        if not text:
            return

        # ── 3. 行级缓冲：确保每行完整，制表符展开基于完整行 ──
        # 合并上一次的不完整行
        text = self._不完整行 + text
        self._不完整行 = ''
        # 按换行分割
        if text.endswith('\n'):
            lines = text.split('\n')
            lines = lines[:-1]  # 末尾空行去掉
        else:
            lines = text.split('\n')
            # 最后一行不完整，保留到下次
            self._不完整行 = lines[-1]
            lines = lines[:-1]

        if not lines:
            return

        # ── 4. 制表符展开为空格（8字符对齐，含中文宽度计算）──
        expanded_lines = []
        for line in lines:
            expanded_lines.append(self._展开制表符(line))
        output_text = '\n'.join(expanded_lines) + '\n'

        # ── 5. 追加到终端输出区 ──
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(output_text)
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
        """强制输出残余缓冲区（发送命令后调用，确保提示符立即显示）。"""
        # 先刷新字节级残余
        if self._输出残余:
            data = self._输出残余
            self._输出残余 = b''
            self._追加输出(data)
        # 再刷新行级残余（不完整行直接输出）
        if self._不完整行:
            line = self._不完整行
            self._不完整行 = ''
            expanded = self._展开制表符(line)
            cursor = self.output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(expanded)
            self.output.setTextCursor(cursor)
            self.output.ensureCursorVisible()

    def _清屏(self):
        self.output.clear()

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
        # 直接用主窗口已加载好的设备列表，不需要重新扫描
        try:
            devices = []
            combo = getattr(self._主窗口, 'deviceCombo', None)
            if combo:
                for i in range(combo.count()):
                    serial = combo.itemData(i)
                    if serial:
                        devices.append({'serial': serial, 'model': '', 'state': 'device'})
            current = self._主窗口.当前序列号()
            self._设备列表已加载.emit(devices, current or '')
        except Exception:
            pass

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
