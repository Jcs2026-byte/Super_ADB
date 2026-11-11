# -*- coding: utf-8 -*-
"""
ADB 交互式终端弹窗
==================
点击「便携工具 → ADB命令行」打开的独立窗口。
类似 adb shell 不带参数进入的交互式终端，可持续敲命令、实时看输出。

连接方式按环境配置自动分流：
  - 自研 ADB 模式：自研adb客户端.交互式Shell（真 PTY，保持 cd/环境变量）
  - 非自研模式：优先 pywinpty 伪终端真 PTY 会话；依赖缺失时回退行模式会话
    （每条命令独立 `adb -s serial shell <cmd>`，不保持工作目录，无 PTY，
    命令由 GUI 本地回显）

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

from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent, QStringListModel
from PySide6.QtGui import QFont, QIcon, QColor, QPalette, QTextCursor, QTextCharFormat
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QLabel, QLineEdit, QPlainTextEdit, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog, QMessageBox,
    QScrollArea, QWidget, QListView, QAbstractScrollArea,
)

from 项目UI import png_rc  # noqa: F401
from 项目UI.界面样式 import get_stylesheet, get_current_theme_id, THEMES
from 项目UI.弹窗样式 import add_green_glow, highlight_card_style, _create_popup_card
from 项目UI.透明外壳对话框 import 自绘外壳对话框
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
# 临时调试：True 时把每包原始字节 / 解码文本追加写到同目录「终端输出调试日志.txt」，
# 用于定位命令回显被吃、列表挤行、前导空格等问题；定位完成后改回 False。
_V调试字节日志 = False
# 文本级 ANSI 过滤（兼容旧代码路径）
_ANSI_RE = re.compile(
    r'\x1b\[[0-9;?]*[a-zA-Z~]'
    r'|\x1b\][^\x07]*\x07'
    r'|\x1b[()][AB012]'
    r'|\x1b[>=<c]'
    r'|\x0f|\x0e|\x07'
)

# 路径补全：这些命令的参数位按设备目录名联想
_V路径命令集 = {
    'cd', 'ls', 'push', 'pull', 'cat', 'rm', 'cp', 'mv',
    'find', 'tail', 'head', 'grep', 'open', 'touch', 'mkdir',
}

# ── ls 输出美化：文件类型分类 ──
# 类别 → (emoji 图标, 深色主题颜色, 浅色主题颜色)；颜色为 None 时沿用主题前景色
_V_LS类别配色 = {
    '目录':   ('📁', '#6db3ff', '#1d6fe0'),
    '可执行': ('⚙',  '#7ee787', '#1a9e4b'),
    '链接':   ('🔗', '#56d4dd', '#0e8fa0'),
    '图片':   ('🖼', '#d2a6ff', '#8b4fd8'),
    '视频':   ('🎬', '#ff8fd0', '#d63384'),
    '音频':   ('🎵', '#63e6be', '#0f9d8a'),
    '压缩':   ('📦', '#ffc266', '#d97706'),
    '文本':   ('📜', '#c9d1d9', '#475569'),
    '其他':   ('📄', None,       None),
}

# 扩展名 → 类别（小写，不含点）
_V_扩展名类别 = {
    # 图片
    'png': '图片', 'jpg': '图片', 'jpeg': '图片', 'gif': '图片',
    'bmp': '图片', 'webp': '图片', 'svg': '图片', 'ico': '图片',
    'heic': '图片', 'avif': '图片', 'tiff': '图片', 'tif': '图片',
    # 视频
    'mp4': '视频', 'mkv': '视频', 'avi': '视频', 'mov': '视频',
    'wmv': '视频', 'flv': '视频', 'webm': '视频', 'm4v': '视频',
    '3gp': '视频', 'ts': '视频', 'm3u8': '视频',
    # 音频
    'mp3': '音频', 'wav': '音频', 'flac': '音频', 'aac': '音频',
    'ogg': '音频', 'm4a': '音频', 'wma': '音频', 'ape': '音频',
    'opus': '音频', 'mid': '音频', 'midi': '音频',
    # 压缩包
    'zip': '压缩', 'tar': '压缩', 'gz': '压缩', 'bz2': '压缩',
    'xz': '压缩', '7z': '压缩', 'rar': '压缩', 'iso': '压缩',
    'jar': '压缩', 'apk': '压缩', 'tgz': '压缩', 'tbz2': '压缩',
    # 脚本 / 可执行
    'sh': '可执行', 'bash': '可执行', 'py': '可执行', 'java': '可执行',
    'so': '可执行', 'dex': '可执行', 'bat': '可执行', 'cmd': '可执行',
    'elf': '可执行', 'bin': '可执行',
    # 文本 / 配置
    'txt': '文本', 'md': '文本', 'log': '文本', 'json': '文本',
    'xml': '文本', 'yaml': '文本', 'yml': '文本', 'ini': '文本',
    'conf': '文本', 'rc': '文本', 'prop': '文本', 'cfg': '文本',
    'properties': '文本', 'html': '文本', 'htm': '文本', 'css': '文本',
    'js': '文本', 'csv': '文本',
}

# -F 后缀标记 → 类型（toybox/mksh ls -F：目录 /、可执行 *、链接 @、管道 |、套接字 =）
_V_F后缀标记 = {'/', '*', '@', '|', '='}

# 提示符行：行尾为 $ 或 #（如 "raven:/ $ "、":/ # "），用于闭合 ls 美化窗口。
# $/# 前必须是行首或空白：避免把 foo# / bar$ 这类以符号结尾的文件名误判成提示符。
_V提示符行RE = re.compile(r'^.*(?:^|\s)[\$#]\s*$')
# 命令回显行：提示符 $/# 后还跟命令文本（如 "raven:/ $ ls -F"、行模式 "$ ls -F"），
# 属于刚下发的命令本身，不能当 ls 列表条目染色加图标
_V回显行RE = re.compile(r'^.*[\$#]\s+\S')
# 复合命令分隔符：管道 / 后台 / 顺序执行 / 重定向，含这些符号时下游输出不属于 ls 列表
_V复合命令RE = re.compile(r'\||&|;|>')
# 长格式权限串首字符：d 目录 / l 链接 / - 普通文件 / b c p s 设备与管道
_V长格式权限RE = re.compile(r'^([bcCdDlMpPsStT-][rwxXstT-]{9}[.+-?]?)')


class _终端信号桥(QObject):
    """跨线程信号桥：交互式Shell 的回调在后台线程，通过信号回主线程。"""
    输出 = Signal(bytes)
    关闭 = Signal()
    # (shell或None, 错误信息, 设备序列号, 连接代际)
    连接完成 = Signal(object, str, str, int)
    # (路径补全代际, 目录前缀, 设备条目列表)
    路径候选 = Signal(int, str, list)


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


class ADB终端对话框(自绘外壳对话框):
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
        super().__init__(parent, 标题="adb shell 交互式终端",
                         最小尺寸=(900, 600), 显示最小化=True, 显示最大化=True)
        self._主窗口 = 主窗口
        self._adb = 主窗口.adb
        self._shell = None  # 交互式Shell 实例
        self._信号桥 = _终端信号桥()
        self._信号桥.输出.connect(self._追加输出)
        self._信号桥.关闭.connect(self._会话已关闭)
        self._信号桥.连接完成.connect(self._连接完成)
        self._命令历史 = deque(maxlen=200)
        self._历史索引 = -1
        self._历史草稿 = ''  # 进入历史前暂存当前半截输入，↓ 到末尾时恢复
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
        # ls 美化窗口：None 表示当前不在 ls 输出段；'列' 多列格式 / '长' 长格式
        self._V美化窗口 = None
        # 上一次渲染到文档末尾的尾巴行：原始文本 + 实际渲染字符数（重绘时按后者删除）
        self._V残留渲染长度 = 0
        # 类别 → QTextCharFormat 缓存（按 类别/深色 区分）
        self._V格式缓存 = {}
        # 最近下发的命令原文：用于识别 PTY 回显行，避免命令被当列表条目染色
        self._V最近命令 = ''
        # 用户实际输入的原文：回显识别 / 拆粘连的兜底匹配（命令原样透传，无改写命令）
        self._V原文命令 = ''
        # ls 列模式平铺缓冲：条目先入缓冲，提示符到达时按视口列宽统一重排
        self._V列条目缓冲 = []
        # 当前尾巴行贡献的缓冲条数：尾巴重解析前先撤销，防重复计入
        self._V列缓冲尾巴条数 = 0
        # 路径补全回填快照：前缀（命令+空格）与后缀（光标后文本），选中候选时按快照回填
        self._V回填前缀 = ''
        self._V回填后缀 = ''
        # 加载自定义命令配置
        self._自定义命令配置文件 = '配置/终端自定义命令.json'
        self._自定义命令列表 = self._加载自定义命令()

        # 命令联想补全（阶段1：本地候选，不查询设备）
        self._补全模型 = QStringListModel(self)
        self._候选面板 = None  # 内嵌 QListView，构建 UI 时赋值
        self._命令候选列表 = []
        self._补全模式 = '命令'  # '命令' | '路径'
        # 阶段2：设备路径补全状态
        self._会话cwd = '/'
        self._路径补全代际 = 0
        self._当前路径目录 = ''
        self._当前路径词 = ''
        # 路径补全全量候选（过滤前的 ls 结果，_F面板刷新 按当前词过滤）
        self._路径候选全量 = []
        # 命令候选接受后抑制一次面板自动刷新（否则面板立刻弹出刚选中的命令）
        self._忽略一次面板刷新 = False
        # 路径补全防抖定时器：输入停顿后自动查询设备目录（输入即弹），避免逐键发 ls
        self._路径防抖定时器 = QTimer(self)
        self._路径防抖定时器.setSingleShot(True)
        self._路径防抖定时器.timeout.connect(self._F触发路径补全)
        # 终端尺寸防抖定时器：窗口/视口连续 resize 时节流，避免拖拽过程中反复 SIGWINCH
        self._尺寸防抖定时器 = QTimer(self)
        self._尺寸防抖定时器.setSingleShot(True)
        self._尺寸防抖定时器.timeout.connect(self._F同步终端尺寸)
        self._信号桥.路径候选.connect(self._F路径候选就绪)

        # 窗口尺寸（标题栏/图标/最小化/最大化由自绘外壳提供，不再叠加原生 flags）
        self.resize(1100, 750)
        self.setAcceptDrops(True)  # 支持拖文件进来追加路径
        self._theme_id = get_current_theme_id(self)
        self.setStyleSheet(get_stylesheet(self._theme_id))
        # 调色板底色同步设为主题背景：否则窗口映射到屏幕、Qt 画第一帧之前，
        # 系统会用调色板默认的白色擦一次背景，表现为「打开弹窗先闪一下白」。
        self._F应用调色板底色()

        # 内层亮边卡片（与其他弹窗同款）
        self.card, _ = _create_popup_card(self, self._theme_id)
        self._构建UI()
        # 卡片与输出区在 _构建UI 之后才存在：再跑一次把子控件底色也写上。
        self._F应用调色板底色()
        # 后台线程加载设备列表完成 → 主线程更新下拉框
        self._设备列表已加载.connect(self._设备列表加载完成)

    # ── 主题切换 ──

    def _F应用调色板底色(self):
        """把主题背景色写进调色板 Window/Base，消除弹窗首帧原生擦白。

        深色背景由 QSS 提供，但 QSS 只在 Qt 绘制阶段起作用；窗口映射到
        屏幕、Qt 画第一帧之前，系统会先用调色板 Window 色擦一次原生背景
        （默认白），表现为「打开弹窗先闪一下白」。show 之前让调色板底色
        与主题一致，原生擦除阶段就是深色，白闪消失。

        卡片与终端输出区是面积最大的两块，且都在本方法首次调用之后才
        创建（_构建UI 里）：它们的调色板若仍是默认浅色，首帧 QSS 未生效
        时就是白块来源。所以 _构建UI 之后会再调一次，把子控件一并刷上。
        """
        t = THEMES.get(self._theme_id, THEMES.get('dark_cyan', {}))
        bg = QColor(t.get('bg_window', '#252f3d'))
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, bg)
        pal.setColor(QPalette.ColorRole.Base, bg)
        self.setPalette(pal)
        # 弹窗自身也要自动填充背景：不开时 Qt 不在首帧擦除背景，backing store
        # 保留系统默认白（最小复现实测首帧 RGB 255,255,255），表现为闪白；
        # 开启后首帧原生擦除阶段即用调色板 Window 深色填充。
        self.setAutoFillBackground(True)
        # 子控件：卡片用按钮底色（与 #popupCard QSS 一致），输出区用输入底色
        for w, role_bg in (
            (getattr(self, 'card', None), t.get('bg_button')),
            (getattr(self, 'output', None), t.get('bg_input')),
        ):
            if w is None:
                continue
            w.setAutoFillBackground(True)
            wp = w.palette()
            wp.setColor(QPalette.ColorRole.Window, QColor(role_bg or '#252f3d'))
            wp.setColor(QPalette.ColorRole.Base, QColor(role_bg or '#252f3d'))
            w.setPalette(wp)
            # 输出区这类滚动区域真正可见的是 viewport 子控件，一并刷上
            vp = w.viewport() if isinstance(w, QAbstractScrollArea) else None
            if vp is not None:
                vp.setAutoFillBackground(True)
                vpal = vp.palette()
                vpal.setColor(QPalette.ColorRole.Base, QColor(role_bg or '#252f3d'))
                vp.setPalette(vpal)

    def apply_theme(self, theme_id):
        """运行时切换主题：更新全局 QSS + 调色板底色 + 外发光。"""
        if theme_id not in THEMES or theme_id == self._theme_id:
            return
        self._theme_id = theme_id
        self.setStyleSheet(get_stylesheet(theme_id))
        self._F应用调色板底色()
        self.card.setStyleSheet(highlight_card_style(theme_id))
        add_green_glow(self.card, accent=QColor(THEMES[theme_id]['accent']))
        if getattr(self, 'output', None) is not None:
            self.output.setStyleSheet(self._终端输出样式())
        if getattr(self, '_候选面板', None) is not None:
            self._候选面板.setStyleSheet(self._候选面板样式())
        self.update()

    def _候选面板样式(self):
        """候选面板样式：随主题配色，青绿边框 + 选中行高亮。"""
        t = THEMES.get(self._theme_id, THEMES.get('dark_cyan', {}))
        bg = t['bg_input']
        fg = t['text_primary']
        accent = t['accent']
        s = t.get('bg_window', '#252f3d').lstrip('#')
        try:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            dark = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0 < 0.55
        except Exception:
            dark = True
        sel_bg = '#0f4c3f' if dark else 'rgba(66,133,244,80)'
        return f'''
            QListView {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {accent};
                border-radius: 4px;
                outline: none;
                padding: 2px;
            }}
            QListView::item {{
                height: 24px;
                padding: 0 8px;
                border-radius: 3px;
            }}
            QListView::item:selected {{
                background-color: {sel_bg};
                color: {accent};
            }}
        '''

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
        # 自动折行：超宽行折到下一行，ls 列表在窗口宽度内完整显示
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
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
        # 监听输出区视口尺寸变化（布局/主题/字号改变也会触发），经防抖后同步 PTY 尺寸
        self.output.viewport().installEventFilter(self)
        # 文档默认边距
        doc = self.output.document()
        doc.setDocumentMargin(4)
        root.addWidget(self.output, 1)

        # 内嵌候选面板：固定高度、无候选时隐藏（不占布局空间）。
        # 候选列表内嵌于布局中，天然不会遮挡输入框与快捷命令按钮行
        self._候选面板 = QListView(self.card)
        self._候选面板.setModel(self._补全模型)
        self._候选面板.setFont(self._终端字体)
        self._候选面板.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._候选面板.setUniformItemSizes(True)
        self._候选面板.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._候选面板.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._候选面板.setStyleSheet(self._候选面板样式())
        self._候选面板.clicked.connect(self._F面板点击)
        self._候选面板.setVisible(False)
        self._候选面板.setFixedHeight(0)
        root.addWidget(self._候选面板)

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
        # 本地命令联想补全：候选来自历史 / 自定义命令 / 内置命令库，不查询设备。
        # 候选数据经 _F刷新补全候选 / _F路径候选就绪 写入面板模型，
        # 输入变化统一走 _F输入文本变化（不使用 QCompleter，补全由内嵌面板呈现）
        self.input_edit.setCompleter(None)
        self.input_edit.textChanged.connect(self._F输入文本变化)
        self._F刷新补全候选()
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
            # 会话跟随：下拉框选中的设备若与当前会话不一致就重连。
            # 旧实现用 blockSignals 改了选项却不通知会话，会出现
            # 「界面显示 B 设备、命令实际发往 A 设备」的静默错发。
            new_serial = self.device_combo.currentData()
            if (new_serial and self._shell is not None
                    and not self._shell.已关闭
                    and new_serial != self._当前终端序列号):
                QTimer.singleShot(0, lambda s=new_serial: self._连接终端(s))
        finally:
            # 异常路径下也要解除信号阻塞，否则下拉框信号被永久关闭、后续选择无响应
            self.device_combo.blockSignals(False)
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
        # 换设备后重置会话工作目录与路径补全快照：否则在 A 设备 cd 到
        # /data/local/tmp 后切到 B 设备，相对路径补全仍按 A 的目录去 B 上 ls。
        # 注意清屏（_清屏）不走到这里，保留当前会话 cwd。
        self._会话cwd = '/'
        self._当前路径目录 = ''
        self._当前路径词 = ''
        self._路径候选全量 = []
        self._V回填前缀 = ''
        self._V回填后缀 = ''
        self._补全模式 = '命令'
        self._路径补全代际 += 1  # 丢弃旧设备尚未返回的路径补全结果
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
                    shell.启动()
                else:
                    shell = self._F创建非自研会话(serial, on_out, on_close)
                self._信号桥.连接完成.emit(shell, '', serial, 代际)
            except Exception as e:
                self._信号桥.连接完成.emit(None, str(e), serial, 代际)
        threading.Thread(target=_do_connect, daemon=True).start()

    def _F创建非自研会话(self, serial, on_out, on_close):
        """非自研（系统/官方 adb）会话：优先 pywinpty 伪终端真 PTY，失败回退行模式。

        伪终端依赖缺失 / spawn 失败 / 后端不支持时，自动降级到无 PTY 的行模式
        会话（每条命令独立 ``adb shell <cmd>``），保证终端可用、不空白崩溃。
        降级原因会回传到终端输出，便于排查为何没起真 PTY。
        """
        try:
            from 工具.android调试工具.伪终端adb会话 import _C伪终端Adb会话
            V会话 = _C伪终端Adb会话(self._adb, serial,
                                    on_output=on_out, on_close=on_close)
            V会话.启动()
            return V会话
        except Exception as V异常:
            try:
                on_out(f'[终端] 伪终端不可用，已回退行模式：{V异常}\n'.encode('utf-8'))
            except Exception:
                pass
            V会话 = _AdbShell行会话(self._adb, serial,
                                    on_output=on_out, on_close=on_close)
            V会话.启动()
            return V会话

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
        # 按视口实测尺寸同步 PTY（首次 show 的 resize 早于建连，这里补一次）；
        # 无尺寸接口的自研会话由 _设置终端宽度 走 stty 兜底
        QTimer.singleShot(250, self._F同步终端尺寸)
        QTimer.singleShot(300, self._设置终端宽度)

    def _设置终端宽度(self, cols: int = 0):
        """设置 PTY 窗口宽度；cols<=0 时按视口实测估算，然后清理 stty 回显噪声行。

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
        # 伪终端真 PTY：优先走伪终端尺寸同步，不发 stty
        if hasattr(self._shell, '设置尺寸'):
            V列, V行 = self._F估算行列()
            self._shell.设置尺寸(V列, V行)
            return
        # 自研 PTY 会话暂未暴露尺寸接口，保留 stty cols 兜底
        if cols <= 0:
            cols, _ = self._F估算行列()
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
        # 关闭时退出 ls 美化窗口，避免关闭提示行被当列表条目染色；
        # 平铺缓冲里还没落盘的条目先输出，避免整段 ls 结果丢失
        if self._V列条目缓冲:
            cursor = self.output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._F平铺列表(cursor)
        self._V美化窗口 = None
        # 追加关闭提示前，先给尚未换行的尾巴提示符补一个换行收尾：
        # 旧实现先把 _V残留渲染长度 清零再追加，已渲染到文档末尾的尾巴行
        # 不再被下次重绘删除，设备退出前回显的第二个提示符就和 [连接已关闭]
        # 直接粘在同一行（实测 "raven:/ $ raven:/ $ [连接已关闭]"）。
        if self._V残留渲染长度:
            cursor = self.output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText('\n')
        # 内存管线残留一并清空：否则关闭提示会和 _不完整行 里的尾巴文本再次拼接
        self._V残留渲染长度 = 0
        self._已渲染残留 = ''
        self._不完整行 = ''
        self._V最近命令 = ''
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
        # 跟踪会话内工作目录，供相对路径补全解析（真 PTY 会话 cwd 保持；行模式为近似值）
        Vcd = re.match(r'^cd\s+(.+)$', text.strip())
        if Vcd:
            V目标 = Vcd.group(1).strip().strip('\'"')
            if V目标.startswith('/'):
                self._会话cwd = V目标
            else:
                self._会话cwd = self._F归一化路径(self._会话cwd, V目标)
        self._命令历史.append(text)
        self._历史索引 = -1
        self._历史草稿 = ''
        self._F刷新补全候选()
        self._F发送命令(text)
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

    def _重发输入(self, text, 重试: int = 0):
        """连接建立后重发之前输入的命令；建连未完成时轮询等待，超时提示而非静默丢弃。"""
        if self._shell and not self._shell.已关闭 and text:
            # 等待建连期间用户已重新编辑输入框：放弃旧命令，保留当前草稿，不覆盖清空
            if self.input_edit.text() != text:
                return
            V命令 = self._预处理命令(text)
            if V命令:
                self._命令历史.append(V命令)
                self._历史索引 = -1
                self._F刷新补全候选()
                self._F发送命令(V命令)
                self.input_edit.clear()
            return
        # 建连尚未完成：每 300ms 重试一次，最多约 3s；超时恢复输入并提示
        if 重试 < 10:
            QTimer.singleShot(300, lambda: self._重发输入(text, 重试 + 1))
        else:
            self.status_label.setText('连接超时，命令未发送，请重选设备后重试')
            self.input_edit.setEnabled(True)
            self.btn_send.setEnabled(True)

    def _F识别Ls命令(self, 原文: str):
        """识别 ls/ll 命令。

        返回 ``(形态, 下发命令)``；非 ls 命令返回 None。
          - 长格式（含 ``-l``，或 ``ll`` 别名）：靠权限列首字符判类型。
          - 列格式：命令原样透传，不再自动补 -F；条目类型由本地按扩展名 /
            设备自带的 -F 后缀（目录 /、可执行 *、链接 @）识别。
        """
        t = 原文.strip()
        m = re.match(r'^(ls|ll)\b(.*)$', t, re.IGNORECASE)
        if not m:
            return None
        # 管道 / 后台 / 顺序执行 / 重定向：下游输出不是 ls 列表，不进入美化窗口
        if _V复合命令RE.search(t):
            return None
        命令名 = m.group(1).lower()
        选项串 = m.group(2)
        选项 = ''.join(re.findall(r'-[A-Za-z]+', 选项串))
        是长格式 = ('l' in 选项) or (命令名 == 'll')
        if 是长格式:
            # ll 在精简 Android 上可能不是内置命令，改写为 ls -l
            if 命令名 == 'll':
                改写 = re.sub(r'^ll\b', 'ls -l', t, count=1, flags=re.IGNORECASE)
                return '长', 改写
            return '长', 原文
        # 列格式：原样下发，不追加 -F/-p
        return '列', 原文

    def _F发送命令(self, text: str):
        """识别命令并下发；ls/ll 进入美化窗口，其余命令退出美化窗口。"""
        # 上一条 ls 的提示符没被识别到时，列表可能还压在平铺缓冲里：
        # 发新命令前先落盘，避免上一批输出丢失
        if self._V美化窗口 == '列' and self._V列条目缓冲:
            cursor = self.output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._F平铺列表(cursor)
        self._V原文命令 = text
        识别 = self._F识别Ls命令(text)
        if 识别 is not None:
            形态, 下发命令 = 识别
            self._V美化窗口 = 形态
            # 回显识别与拆粘连都按用户原文命令匹配；命令原样透传，无改写命令
            self._V最近命令 = 下发命令
            self._shell.发送输入(下发命令 + '\n')
        else:
            self._V美化窗口 = None
            self._V最近命令 = text
            self._shell.发送输入(text + '\n')

    def _发送控制字符(self, data: bytes):
        if self._shell and not self._shell.已关闭:
            self._shell.发送输入(data)

    def _F记录调试文本(self, V字节: bytes, V文本: str):
        """临时调试：把每包原始字节与解码文本追加到日志（_V调试字节日志 为 False 时不写）。"""
        if not _V调试字节日志:
            return
        try:
            import os, time
            V路径 = os.path.join(os.path.dirname(__file__), '终端输出调试日志.txt')
            V行模式 = getattr(self._shell, '是行模式', None)
            V有尺寸接口 = hasattr(self._shell, '设置尺寸') if self._shell else None
            with open(V路径, 'a', encoding='utf-8') as F:
                F.write(f'[{time.strftime("%H:%M:%S")}] 行模式={V行模式} 尺寸接口={V有尺寸接口}\n'
                        f'  bytes={V字节!r}\n  text={V文本!r}\n')
        except Exception:
            pass

    def _F记调试(self, V消息: str):
        """临时调试：追加一行任意文本到调试日志（_V调试字节日志 为 False 时不写）。"""
        if not _V调试字节日志:
            return
        try:
            import os, time
            V路径 = os.path.join(os.path.dirname(__file__), '终端输出调试日志.txt')
            with open(V路径, 'a', encoding='utf-8') as F:
                F.write(f'[{time.strftime("%H:%M:%S")}] {V消息}\n')
        except Exception:
            pass

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
        # 控制字符清理：保留 \n \t \r（\r 模拟回行覆盖）与 \b（退格，单独走退格处理）
        text = re.sub(r'[\x00-\x07\x0b\x0c\x0e-\x1f\x7f]', '', text)
        self._F记录调试文本(filtered, text)
        if not text:
            return

        # ── 3. 行合并：整行入显示区，尾巴行单独渲染 ──
        合并文本 = self._不完整行 + text
        if self._V美化窗口 is not None:
            # 回显包不带换行时，列表首行会与回显粘成一行（甚至把回显整行覆盖掉）
            合并文本 = self._F拆回显粘连(合并文本)
        # 列模式下尾巴行的条目已入平铺缓冲：本包重解析前先撤销上包的贡献，防重复
        if self._V列缓冲尾巴条数:
            del self._V列条目缓冲[len(self._V列条目缓冲) - self._V列缓冲尾巴条数:]
            self._V列缓冲尾巴条数 = 0
        parts = 合并文本.split('\n')
        self._不完整行 = parts.pop() if parts else ''
        out_lines = [
            self._展开制表符(self._F应用退格(self._处理回车(ln))) for ln in parts]
        tail = (self._展开制表符(self._F应用退格(self._处理回车(self._不完整行)))
                if self._不完整行 else '')

        # ── 4. 先删掉上次渲染的尾巴行，再逐行写入（ls 行按类型着色加图标）──
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self._V残留渲染长度:
            cursor.movePosition(QTextCursor.MoveOperation.Left,
                               QTextCursor.MoveMode.KeepAnchor,
                               self._V残留渲染长度)
            cursor.removeSelectedText()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # 完整行直接落盘；残留长度只统计尾巴行（下次重绘按它删除）。
        # 列模式下列表行只入平铺缓冲、不写文档（_F渲染一行 返回 -1），此时不补换行
        for ln in out_lines:
            if self._F渲染一行(cursor, ln) >= 0:
                cursor.insertText('\n')
        if tail:
            残留长度 = max(0, self._F渲染一行(cursor, tail, 是尾巴=True))
        else:
            残留长度 = 0
        self._已渲染残留 = tail
        self._V残留渲染长度 = 残留长度
        # 用户正在选中文本、或视图停在历史位置时，新输出不拉回底部、不取消选中
        V当前光标 = self.output.textCursor()
        if not V当前光标.hasSelection() and self._F视图在底部():
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
        """计算字符的终端显示宽度（ASCII=1，中日韩/emoji 等宽字符=2）。"""
        code = ord(ch)
        # 零宽变体选择符 / emoji 肤色调色板不占列宽
        if code == 0xFE0F or 0x1F3FB <= code <= 0x1F3FF:
            return 0
        # Emoji 区段（📁⚙🔗📄 等）在多数等宽字体下占 2 列
        if (
            0x2600 <= code <= 0x27BF or  # 杂项符号 / 装饰符号
            0x2B00 <= code <= 0x2BFF or  # 箭头/补充符号
            0x1F000 <= code <= 0x1FAFF   # emoji 主段 + 扩展-A
        ):
            return 2
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
    def _F应用退格(text: str) -> str:
        """模拟退格 \\b：回退一格、删除前一个字符。

        shell 重绘提示符/清行常输出「大段空格 + \\b×N」：空格覆盖旧内容、
        \\b 退格回行首。若把 \\b 当普通控制字符删掉而保留空格，会残留大段空格。
        """
        栈 = []
        for ch in text:
            if ch == '\b':
                # 清行序列为「空格 + \b」成对出现：\b 只抵消紧邻空格，
                # 不弹掉已写入的真实字符（退格在清行里是回行首定位，非删字符）。
                if 栈 and 栈[-1] == ' ':
                    栈.pop()
            else:
                栈.append(ch)
        return ''.join(栈)

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
        # CRLF：\r 只是回车归位，换行交给 \n，不触发行首覆盖。
        # 分包时 \r 在包尾、\n 在下包头，合并后若按覆盖处理，会把上一行
        # 命令回显整行盖掉（实测 ls 回显行消失、与列表首行挤一行）。
        line = line.replace('\r\n', '\n')
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

    # ── ls 输出美化渲染 ──

    def _F是否深色主题(self) -> bool:
        """按主题背景亮度判断是否深色（浅色主题用深一点的类别色）。"""
        t = THEMES.get(self._theme_id, THEMES.get('dark_cyan', {}))
        s = t.get('bg_window', '#252f3d').lstrip('#')
        try:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0 < 0.55
        except Exception:
            return True

    def _F取类别格式(self, 类别):
        """取类别对应的字符格式；None/其他类别返回 None（沿用主题前景色）。"""
        if not 类别 or 类别 == '其他':
            return None
        深色 = self._F是否深色主题()
        缓存键 = (类别, 深色)
        fmt = self._V格式缓存.get(缓存键)
        if fmt is None:
            _, 深色值, 浅色值 = _V_LS类别配色.get(
                类别, _V_LS类别配色['其他'])
            色值 = 深色值 if 深色 else 浅色值
            fmt = QTextCharFormat()
            if 色值:
                fmt.setForeground(QColor(色值))
            self._V格式缓存[缓存键] = fmt
        return fmt

    def _F插入段(self, cursor, 文本, 类别):
        """按类别颜色把一段文本插入光标处。"""
        if not 文本:
            return
        fmt = self._F取类别格式(类别)
        if fmt is None:
            cursor.insertText(文本)
        else:
            cursor.insertText(文本, fmt)

    def _F分类条目(self, 名称, 标记='', 权限首字符=None, 可执行位=False) -> str:
        """按 -F 后缀标记 / 长格式权限 / 扩展名判定条目类别。"""
        if 标记 == '/' or 权限首字符 == 'd':
            return '目录'
        if 标记 == '@' or 权限首字符 == 'l':
            return '链接'
        if 标记 == '*' or 可执行位:
            return '可执行'
        点 = 名称.rfind('.')
        扩展名 = 名称[点 + 1:].lower() if 点 > 0 else ''
        return _V_扩展名类别.get(扩展名, '其他')

    def _F是否回显行(self, 行: str) -> bool:
        """判断一行是否为命令回显（而非 ls 列表输出）。

        PTY 回显分批到达、提示符可能被 \\r 覆盖清空，单靠行内提示符正则不可靠；
        除正则外，再用最近下发命令的命令名 / 选项 token 做词边界匹配兜底。
        """
        去首 = 行.strip()
        if not 去首:
            return False
        if _V回显行RE.match(去首):
            return True
        # 同时按「下发命令」与「用户原文命令」做 token 兜底匹配，避免回显被误判成列表条目。
        # 只认首命令名 + 选项：参数/路径 token 不参与，短词/纯数字极易与同名列表条目撞词。
        候选命令 = [self._V最近命令, self._V原文命令]
        for 命令 in 候选命令:
            命令 = (命令 or '').strip()
            if not 命令:
                continue
            for 序号, token in enumerate(命令.split()):
                if not token:
                    continue
                if token.startswith('-'):
                    # 选项（如 -l）直接子串匹配；选项名不会出现在普通列表名里
                    if token in 去首:
                        return True
                    continue
                if 序号 != 0:
                    continue
                # 首命令名：跳过单字符 / 纯数字，避免列表里同名短条目被判成回显
                if len(token) < 2 or token.isdigit():
                    continue
                if re.search(r'(?<!\S)' + re.escape(token) + r'(?!\S)', 去首):
                    return True
        return False

    def _F拆回显粘连(self, 合并文本: str) -> str:
        """ls 美化窗口内，回显与后续输出之间没有换行时在命令末尾强制断行。

        部分设备/分包下回显包不带换行、列表首行紧随其后到达，合并后回显与
        列表首条粘成一行（实测 'raven:/Reserve0 $ ls -F⚙ disp_rs1.fex'）；
        回显若以 \\r 收尾还会被更长的列表行整行覆盖，连回显一起消失。
        判据：合并文本中最近一次「下发命令」出现位置之后紧跟的不是 \\n
        （也不是 \\r\\n），就在命令后补一个 \\n，让回显独立成行。
        """
        命令 = (self._V最近命令 or '').strip()
        if not 命令:
            命令 = (self._V原文命令 or '').strip()
        if not 命令:
            return 合并文本
        idx = 合并文本.rfind(命令)
        if idx < 0 and self._V原文命令:
            idx = 合并文本.rfind(self._V原文命令.strip())
        if idx < 0:
            return 合并文本
        结束 = idx + len(命令)
        if 结束 >= len(合并文本):
            return 合并文本  # 回显可能还没到齐，等下一包
        if 合并文本[结束] == '\n':
            return 合并文本
        if 合并文本[结束] == '\r':
            # \r\n 本就是正常断行；\r 在缓冲尾说明 \n 还在下一包，先等
            if 结束 + 1 >= len(合并文本) or 合并文本[结束 + 1] == '\n':
                return 合并文本
        return 合并文本[:结束] + '\n' + 合并文本[结束:]

    def _F渲染一行(self, cursor, 行, 是尾巴=False) -> int:
        """渲染一行到光标处，返回实际插入的字符数；返回 -1 表示已入平铺缓冲、未写文档。

        不在 ls 美化窗口、空行、提示符行均原样写入；提示符行同时闭合美化窗口
        （列模式先把缓冲的条目平铺落盘）。列模式下列表行只入缓冲不立即写，
        等整块列表收全后按视口列宽重排，避免逐行重拼导致的列错位。
        """
        起始位置 = cursor.position()
        if self._V美化窗口 is None:
            cursor.insertText(行)
            return cursor.position() - 起始位置
        if _V提示符行RE.match(行.strip()):
            if self._V美化窗口 == '列':
                self._F平铺列表(cursor)
            self._V美化窗口 = None
            # 平铺内容已落盘、不属于尾巴残留：残留长度只统计本行提示符，
            # 否则下一包按偏大的残留长度 removeSelectedText 会吞掉整段列表乃至更早历史。
            行起始 = cursor.position()
            cursor.insertText(行)
            return cursor.position() - 行起始
        # 命令回显行（提示符后跟命令本身）：原样写入，保留美化窗口等待列表输出。
        # 命令已原样透传（不再本地补 -F），回显即用户输入原文，无需再替换。
        if self._F是否回显行(行):
            # 新一条命令回显到达，说明上一条 ls 的列表块已结束：先把缓冲里没落盘的
            # 条目平铺落盘，否则它们会被压到下一条提示符之后才排出（错位到命令后面），
            # 或在美化窗口退出时被丢弃（实测 ls 后 cd /，上一条 ls 结果直接消失）。
            if self._V美化窗口 == '列' and self._V列条目缓冲:
                self._F平铺列表(cursor)
            行起始 = cursor.position()
            cursor.insertText(行)
            return cursor.position() - 行起始
        if not 行.strip():
            # ls 美化窗口内的纯空白行（PTY 行编辑重绘残留 / 命令后额外空行）
            # 没有信息价值，直接折叠：返回 -1 不入文档、也不补换行；
            # 非 ls 命令输出的空行仍原样保留。
            if self._V美化窗口 is not None:
                return -1
            cursor.insertText(行)
            return cursor.position() - 起始位置
        if self._V美化窗口 == '长':
            self._F写长格式行(cursor, 行)
            return cursor.position() - 起始位置
        新增条数 = self._F缓冲列条目(行)
        if 新增条数:
            # 尾巴行会随后续数据重解析：记录本次贡献条数，下包到来时先撤销
            self._V列缓冲尾巴条数 = 新增条数 if 是尾巴 else 0
            return -1
        if 是尾巴:
            self._V列缓冲尾巴条数 = 0
        cursor.insertText(行)
        return cursor.position() - 起始位置

    def _F缓冲列条目(self, 行) -> int:
        """把一行 -F 多列输出解析成条目追加到平铺缓冲，返回新增条数；非列表行返回 0。

        旧实现逐个行按 2 空格重拼条目，丢掉了 ls 的列宽对齐，图标注入后行宽
        不可控还会触发折行，看起来「自动分成几列、向左乱对齐」。现在整块列表
        先入缓冲，提示符到达时交给 _F平铺列表 按视口列宽统一重排。
        """
        去首 = 行.strip()
        # 错误/提示行（如 "ls: /path: No such file or directory"）不是列表条目
        if not 去首 or re.match(r'^\S+:', 去首):
            return 0
        新条目 = []
        for 片段 in re.split(r' {2,}|\t+', 去首):
            片段 = 片段.strip()
            if not 片段:
                continue
            # 命令选项/含 shell 元字符/内部带空格的片段不是文件条目；
            # 出现这类片段说明本行是命令或回显残留，整行按非列表行处理
            if 片段.startswith('-') or re.search(r'[\$#|;>]', 片段) or ' ' in 片段:
                return 0
            if 片段[-1] in _V_F后缀标记:
                新条目.append((片段[-1], 片段[:-1]))
            else:
                新条目.append(('', 片段))
        if not 新条目:
            return 0
        self._V列条目缓冲.extend(新条目)
        return len(新条目)

    def _F平铺列表(self, cursor):
        """把缓冲的 ls 条目按视口列宽以列主序（先纵后横，同 GNU ls）平铺输出。

        列数取「放得下的最大列数」：列宽 = 该列最长条目的显示宽度
        （图标 + 空格 + 名称，中文按 2 列宽），列间距 2 空格，总宽不超视口列数，
        因此不会出现半截折行，同名条目也不会因占位不同而错位。
        """
        条目 = self._V列条目缓冲
        self._V列条目缓冲 = []
        self._V列缓冲尾巴条数 = 0
        if not 条目:
            return
        V视口列, _ = self._F估算行列()

        def 条目宽(标记, 名称):
            类别 = self._F分类条目(名称, 标记)
            图标 = _V_LS类别配色.get(类别, _V_LS类别配色['其他'])[0]
            return (sum(self._字符显示宽度(c) for c in 图标) + 1
                    + sum(self._字符显示宽度(c) for c in 名称))

        宽表 = [条目宽(m, n) for m, n in 条目]
        总数 = len(条目)
        列数, 行数, 列宽 = 1, 总数, [max(宽表)]
        for 候选列数 in range(min(总数, max(1, V视口列 // 8)), 1, -1):
            候选行数 = (总数 + 候选列数 - 1) // 候选列数
            候选列宽 = []
            for c in range(候选列数):
                w = 0
                for r in range(候选行数):
                    i = c * 候选行数 + r
                    if i < 总数:
                        w = max(w, 宽表[i])
                候选列宽.append(w)
            if sum(候选列宽) + 2 * (候选列数 - 1) <= V视口列:
                列数, 行数, 列宽 = 候选列数, 候选行数, 候选列宽
                break
        for r in range(行数):
            for c in range(列数):
                i = c * 行数 + r
                if i >= 总数:
                    continue
                标记, 名称 = 条目[i]
                类别 = self._F分类条目(名称, 标记)
                图标 = _V_LS类别配色.get(类别, _V_LS类别配色['其他'])[0]
                self._F插入段(cursor, f'{图标} ', 类别)
                self._F插入段(cursor, 名称, 类别)
                # 同行右侧还有条目才补对齐空格，末列不补，避免行尾拖白
                if (c + 1) * 行数 + r < 总数:
                    cursor.insertText(' ' * (列宽[c] - 宽表[i] + 2))
            cursor.insertText('\n')

    def _F写长格式行(self, cursor, 行):
        """渲染 ls -l 长格式行：权限/日期等前缀原样，仅条目名着色加图标。"""
        m = _V长格式权限RE.match(行)
        if not m:
            cursor.insertText(行)
            return
        权限 = m.group(1)
        首字符 = 权限[0]
        可执行位 = (权限[3] in 'xX' or 权限[6] in 'xX' or 权限[9] in 'xX')
        剩余 = 行[m.end():]
        if not 剩余.strip():
            cursor.insertText(行)
            return
        if ' -> ' in 剩余:
            左, 目标 = 剩余.rsplit(' -> ', 1)
            名称 = 左.rsplit(None, 1)[-1]
            前缀 = 行[:m.end()] + 左[:len(左) - len(名称)]
        else:
            名称 = 剩余.rsplit(None, 1)[-1]
            目标 = ''
            前缀 = 行[:m.end()] + 剩余[:len(剩余) - len(名称)]
        类别 = self._F分类条目(名称, '', 权限首字符=首字符, 可执行位=可执行位)
        图标, _, _ = _V_LS类别配色.get(类别, _V_LS类别配色['其他'])
        cursor.insertText(前缀)
        self._F插入段(cursor, f'{图标} ', 类别)
        self._F插入段(cursor, 名称, 类别)
        if 目标:
            self._F插入段(cursor, ' -> ', None)
            self._F插入段(cursor, 目标, '链接')

    def _刷新残余(self):
        """把视图滚到最新内容。

        旧实现会把字节残余回灌 _追加输出，但 ≤8 字节的残余会被再次扣留，
        等于无效刷新（实测 hi\\n 刷新后仍在缓冲里）。现在短输出和尾巴行都已
        实时渲染，这里只需保证光标/滚动条跟上。
        """
        V当前光标 = self.output.textCursor()
        if V当前光标.hasSelection():
            return
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
        self._V美化窗口 = None
        self._V残留渲染长度 = 0
        self._V最近命令 = ''
        self._V原文命令 = ''
        self._V列条目缓冲 = []
        self._V列缓冲尾巴条数 = 0
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
            # 首次进入历史：暂存当前半截输入，供 ↓ 到末尾时恢复
            self._历史草稿 = self.input_edit.text()
            self._历史索引 = len(self._命令历史) - 1
        elif self._历史索引 > 0:
            self._历史索引 -= 1
        # setText 会触发 textChanged → 面板刷新：翻历史不应弹补全面板，
        # 否则下次 ↑/↓ 被 eventFilter 当成候选移动，历史翻不动。
        # 仅在文本确实会变化时置标志：相同文本不发 textChanged，标志若残留
        # 会吞掉下一次真实按键的一次面板刷新。
        V目标 = self._命令历史[self._历史索引]
        if self.input_edit.text() != V目标:
            self._忽略一次面板刷新 = True
        self.input_edit.setText(V目标)

    def _历史向下(self):
        if not self._命令历史 or self._历史索引 < 0:
            return
        if self._历史索引 < len(self._命令历史) - 1:
            self._历史索引 += 1
            V目标 = self._命令历史[self._历史索引]
            if self.input_edit.text() != V目标:
                self._忽略一次面板刷新 = True
            self.input_edit.setText(V目标)
        else:
            self._历史索引 = -1
            # 回到草稿行：有暂存草稿则恢复，否则清空
            V目标 = self._历史草稿
            if self.input_edit.text() != V目标:
                self._忽略一次面板刷新 = True
            if V目标:
                self.input_edit.setText(V目标)
            else:
                self.input_edit.clear()
            self._历史草稿 = ''

    def _F刷新补全候选(self):
        """重建本地补全候选：历史命令 + 自定义命令 + 内置命令库（去重保序）。"""
        V候选 = []
        V已见 = set()

        def _加入(V文本):
            V文本 = (V文本 or '').strip()
            if not V文本:
                return
            V键 = V文本.lower()
            if V键 in V已见:
                return
            V已见.add(V键)
            V候选.append(V文本)

        # 历史命令（最近使用优先，倒序）
        for V命令 in reversed(self._命令历史):
            _加入(V命令)
        # 自定义命令
        for V命令 in self._自定义命令列表:
            _加入(V命令.get('command', ''))
        # 内置命令库（过滤含 <占位符> 的条目，避免补全出不可直接执行的模板）
        try:
            from 对话框.ADB命令集合对话框 import ADB命令集
            for V条目 in ADB命令集:
                V命令 = V条目[1] if len(V条目) > 1 else ''
                if '<' in V命令 or '>' in V命令:
                    continue
                _加入(V命令)
        except Exception:
            pass
        self._命令候选列表 = V候选
        if self._补全模式 == '命令':
            self._F面板刷新()

    def _F补全选中(self, V文本):
        """选中候选 → 回填输入框、隐藏面板并保持焦点。"""
        if not V文本:
            return
        if self._补全模式 == '路径':
            # 路径模式：回填触发 textChanged → 防抖查询下一级，实现连续补全
            self._F回填路径段(V文本)
        else:
            # 命令模式：接受后抑制一次自动刷新，避免面板立刻弹出自己的刚选命令。
            # 文本相同则不发 textChanged，不置标志，避免残留吞掉下一次刷新。
            if self.input_edit.text() != V文本:
                self._忽略一次面板刷新 = True
            self.input_edit.setText(V文本)
            self.input_edit.setCursorPosition(len(V文本))
            self._F面板隐藏()
        self.input_edit.setFocus()

    # ── 阶段2：设备路径补全 ──

    def _F解析路径参数(self):
        """解析光标处是否处于路径参数位。

        返回 (是否路径位, 目录前缀, 当前完整词)；非路径位返回 (False, '', '')。
        词按光标位置截取：行尾空格时为空词（等价 shell 中 <cmd> <Tab> 列当前目录），
        并识别 '.'/'..' 作为目录前缀。
        """
        text = self.input_edit.text()
        pos = self.input_edit.cursorPosition()
        left = text[:pos]
        if ' ' not in left:
            return False, '', ''
        词列表 = left.split()
        if not 词列表:
            return False, '', ''
        命令 = 词列表[0].strip().lower()
        if 命令 not in _V路径命令集:
            return False, '', ''
        # 按光标取尾部词（旧实现用 split()[-1]，行尾空格时会误取上一个已完成参数）
        word = re.search(r'\S*$', left).group(0)
        if word in ('.', '..'):
            目录 = word + '/'
        elif '/' in word:
            目录 = word[:word.rfind('/') + 1]
        else:
            目录 = ''
        return True, 目录, word

    def _F归一化路径(self, 基准, 相对):
        """把相对路径拼到基准目录并归一化 . / ..（Unix 风格）。"""
        片段 = (基准.rstrip('/') + '/' + 相对).split('/')
        栈 = []
        for 段 in 片段:
            if 段 in ('', '.'):
                continue
            if 段 == '..':
                if 栈:
                    栈.pop()
                continue
            栈.append(段)
        return '/' + '/'.join(栈)

    def _F触发路径补全(self):
        """在路径参数位发起异步设备目录查询；返回是否命中路径位。"""
        是否路径位, 目录, word = self._F解析路径参数()
        if not 是否路径位:
            return False
        serial = self._当前终端序列号
        if not serial or not self._adb:
            return False
        目标目录 = 目录 if 目录.startswith('/') else self._F归一化路径(self._会话cwd, 目录)
        代际 = self._路径补全代际 + 1
        self._路径补全代际 = 代际
        self._当前路径目录 = 目录
        self._当前路径词 = word
        # 记录回填快照：命令前缀（含空格）与光标后后缀，避免选中时被 completer 中间替换覆盖。
        # word 恒为 V左 的尾部词（行尾空格时为空词），前缀直接按长度截取。
        V文本 = self.input_edit.text()
        V光标 = self.input_edit.cursorPosition()
        V左 = V文本[:V光标]
        self._V回填前缀 = V左[:len(V左) - len(word)]
        self._V回填后缀 = V文本[V光标:]
        import threading
        threading.Thread(
            target=self._F后台ls,
            args=(代际, serial, 目标目录, 目录), daemon=True).start()
        return True

    def _F后台ls(self, 代际, serial, 目标目录, 目录):
        """后台线程：ls 目标目录取条目；结果经信号回主线程。"""
        条目 = []
        try:
            # 目录名单引号转义（' → '\''），避免目录名含 ' 破坏 shell 引号配对
            V转义目录 = 目标目录.replace("'", "'\\''")
            out = self._adb.执行shell(serial, f"ls -1p '{V转义目录}'", timeout=5)
            if isinstance(out, bytes):
                out = out.decode('utf-8', 'replace')
            for 行 in (out or '').splitlines():
                行 = 行.strip()
                if not 行:
                    continue
                是目录 = 行.endswith('/')
                名称 = 行.rstrip('/')
                if not 名称:
                    continue
                条目.append(名称 + ('/' if 是目录 else ''))
        except Exception:
            条目 = []
        self._信号桥.路径候选.emit(代际, 目录, 条目)

    def _F路径候选就绪(self, 代际, 目录, 条目):
        """主线程：路径查询结果到达；过期代际丢弃。空结果复位模式，避免旧目录候选残留。"""
        if 代际 != self._路径补全代际:
            return
        if not 条目:
            if self._补全模式 != '命令':
                self._补全模式 = '命令'
            self._F面板刷新()
            return
        self._补全模式 = '路径'
        self._路径候选全量 = [目录 + e for e in 条目]
        self._F面板刷新()

    # ── 候选面板（内嵌补全，替代 QCompleter 浮层弹窗）──

    def _F面板刷新(self, 强制: bool = False):
        """按当前补全模式与前缀刷新候选面板：过滤、显隐、高度一次完成。"""
        V输入框 = getattr(self, 'input_edit', None)
        if self._候选面板 is None or V输入框 is None:
            return
        if self._补全模式 == '路径':
            全量 = self._路径候选全量
            前缀 = self._当前路径词
        else:
            全量 = self._命令候选列表
            前缀 = V输入框.text()[:V输入框.cursorPosition()]
        低 = 前缀.lower()
        候选 = [c for c in 全量 if c.lower().startswith(低)]
        # 命令模式输入不足 2 字符不弹（Tab 强制除外），降低打扰
        if (self._补全模式 == '命令' and not 强制
                and len(V输入框.text().strip()) < 2):
            候选 = []
        self._补全模型.setStringList(候选)
        if not 候选:
            self._F面板隐藏()
            return
        V行高 = self._候选面板.fontMetrics().height() + 10
        V行数 = min(len(候选), 6)
        self._候选面板.setFixedHeight(V行高 * V行数 + 8)
        self._候选面板.setVisible(True)
        if not self._候选面板.currentIndex().isValid():
            self._候选面板.setCurrentIndex(self._补全模型.index(0, 0))

    def _F面板隐藏(self):
        """隐藏候选面板并回收高度。"""
        if self._候选面板 is None:
            return
        self._候选面板.setVisible(False)
        self._候选面板.setFixedHeight(0)

    def _F面板接受当前(self) -> bool:
        """接受候选面板当前项（无选中项时取第一条），返回是否已接受（或已处理 Tab）。"""
        if self._候选面板 is None or not self._候选面板.isVisible():
            return False
        if self._补全模型.rowCount() <= 0:
            return False
        if (self._补全模式 == '路径' and not self._当前路径词
                and self._补全模型.rowCount() > 1):
            # 空词位（行尾空格）+ 多处候选：只把列表留在面板里，不回填。
            # 否则每按一次 Tab 都把首条候选再插一遍（实测 'ls a a a'）
            return True
        索引 = self._候选面板.currentIndex()
        if not 索引.isValid():
            索引 = self._补全模型.index(0, 0)
        V候选 = 索引.data(Qt.ItemDataRole.DisplayRole)
        if not V候选:
            return False
        self._F补全选中(V候选)
        return True

    def _F面板移动选择(self, 步长: int):
        """↑/↓ 在候选间循环移动。"""
        总数 = self._补全模型.rowCount()
        if 总数 <= 0:
            return
        当前 = self._候选面板.currentIndex().row()
        if 当前 < 0:
            新行 = 0 if 步长 > 0 else 总数 - 1
        else:
            新行 = (当前 + 步长) % 总数
        self._候选面板.setCurrentIndex(self._补全模型.index(新行, 0))

    def _F面板点击(self, 索引):
        """鼠标单击候选 → 直接接受。"""
        V候选 = 索引.data(Qt.ItemDataRole.DisplayRole)
        if V候选:
            self._F补全选中(V候选)

    def _F回填路径段(self, V路径):
        """把选中的路径段替换到输入框当前词位置，保留命令前缀与后缀。

        优先用触发补全时记录的前缀/后缀快照回填；快照失效时再按当前文本反推兜底。
        """
        前缀 = self._V回填前缀
        后缀 = self._V回填后缀
        if not 前缀:
            text = self.input_edit.text()
            pos = self.input_edit.cursorPosition()
            left = text[:pos]
            词 = self._当前路径词 or ''
            if left.endswith(词):
                前缀 = left[:len(left) - len(词)]
            else:
                前缀 = left
            后缀 = text[pos:]
        self._F记调试(f'回填路径: 快照前缀={self._V回填前缀!r} 后缀={self._V回填后缀!r} '
                      f'反推前缀={前缀!r} 当前文本={self.input_edit.text()!r} '
                      f'词={self._当前路径词!r} 候选={V路径!r}')
        new_text = 前缀 + V路径 + 后缀
        # shell 惯例：补出文件（非目录）后补一个空格；目录不加，方便继续补下一级
        V补空格 = (not 后缀 and V路径 and not V路径.endswith('/'))
        if V补空格:
            new_text += ' '
        self.input_edit.setText(new_text)
        V新光标 = len(new_text) if V补空格 else len(前缀) + len(V路径)
        self.input_edit.setCursorPosition(V新光标)
        self._F面板隐藏()
        self._F记调试(f'回填后: new={new_text!r} 实际={self.input_edit.text()!r}')

    def _F输入文本变化(self):
        """输入变化：路径参数位防抖后自动查设备目录；离开路径位恢复命令候选。"""
        if self._忽略一次面板刷新:
            self._忽略一次面板刷新 = False
            return
        是否路径位, _, word = self._F解析路径参数()
        if 是否路径位:
            self._当前路径词 = word
            # 停顿 300ms 再发起路径查询，连续按键只保留最后一次（代际号丢弃过期结果）
            self._路径防抖定时器.start(300)
        else:
            self._路径防抖定时器.stop()
            if self._补全模式 != '命令':
                self._补全模式 = '命令'
        self._F面板刷新()

    # ── 窗口生命周期 ──

    def resizeEvent(self, event):
        """窗口尺寸变化 → 防抖后同步真 PTY 会话的终端行列数。"""
        super().resizeEvent(event)
        self._尺寸防抖定时器.start(150)

    def _F视图在底部(self) -> bool:
        """垂直滚动条是否已停在内容底部（留 2 行容差）。"""
        vbar = self.output.verticalScrollBar()
        return vbar.value() >= vbar.maximum() - 2

    def _F估算行列(self):
        """按输出区字体度量与视口尺寸估算终端行列数（列宽预留滚动条/内边距开销）。"""
        V控件 = self.output
        V指标 = V控件.fontMetrics()
        V字符宽 = V指标.horizontalAdvance('M') or 8
        V行高 = V指标.height() or 16
        V宽 = V控件.viewport().width() or 800
        V高 = V控件.viewport().height() or 240
        V列 = max(20, min(300, (V宽 - 16) // max(V字符宽, 1)))
        V行 = max(5, min(120, V高 // max(V行高, 1)))
        return V列, V行

    def _F同步终端尺寸(self):
        """按输出区视口实测行列数，同步到支持尺寸接口的真 PTY 会话。"""
        if not self._shell or self._shell.已关闭:
            return
        if getattr(self._shell, '是行模式', False):
            return
        if not hasattr(self._shell, '设置尺寸'):
            return
        V列, V行 = self._F估算行列()
        self._shell.设置尺寸(V列, V行)

    def eventFilter(self, obj, event):
        """输入框的事件过滤器：协调命令历史、候选面板与回车发送；
        输出区视口 resize 经防抖后同步 PTY 尺寸。"""
        if obj is self.output.viewport():
            if event.type() == QEvent.Type.Resize:
                self._尺寸防抖定时器.start(150)
            return super().eventFilter(obj, event)
        if obj is self.input_edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            V面板可见 = bool(self._候选面板 is not None and self._候选面板.isVisible())
            # Esc：关闭候选面板
            if key == Qt.Key.Key_Escape and V面板可见:
                self._F面板隐藏()
                return True
            # 回车 = 发送命令（唯一职责）：面板只收起、绝不回填。
            # 旧实现在路径模式下面板可见时先接受候选再 return True，于是 Tab
            # 补全过的路径被 Enter 又追加一遍（实测 'ls a a a'），命令还发不出去。
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if V面板可见:
                    self._F面板隐藏()
                return super().eventFilter(obj, event)
            # Tab：面板有候选直接接受；否则路径位发异步查询、命令位强制出面板。
            # 一律吞掉 Tab，避免 Qt 默认行为把焦点切到下一个控件；
            # 右方向键不参与补全，恢复光标移动能力
            if key == Qt.Key.Key_Tab:
                if self._F面板接受当前():
                    return True
                if self._F触发路径补全():
                    return True
                self._F面板刷新(强制=True)
                return True
            # 上下方向键：面板可见时在候选间循环移动；否则翻历史
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                if V面板可见:
                    self._F面板移动选择(1 if key == Qt.Key.Key_Down else -1)
                    return True
                if key == Qt.Key.Key_Up:
                    self._历史向上()
                else:
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
        """从配置文件加载自定义命令列表。

        区分「文件不存在」（首次使用，默认空）与「读取异常」（损坏/权限异常）：
        后者置 _配置读取异常，保存前先备份原文件，避免空列表无声覆盖丢失原配置。
        """
        import os, json
        from 工具.android调试工具.ADB工具 import _config_path
        path = _config_path(self._自定义命令配置文件)
        self._配置读取异常 = False
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            self._配置读取异常 = True
            return []

    def _保存自定义命令(self):
        """保存自定义命令列表到配置文件；读取异常时先备份原文件再覆盖。"""
        import os, shutil
        from 工具.android调试工具.ADB工具 import 保存json配置, _config_path
        path = _config_path(self._自定义命令配置文件)
        if getattr(self, '_配置读取异常', False) and os.path.exists(path):
            try:
                shutil.copy2(path, path + '.bak')
            except Exception:
                pass
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
        # 自定义命令变更后同步到补全候选
        self._F刷新补全候选()

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


class _自定义命令配置对话框(自绘外壳对话框):
    """自定义快捷命令配置对话框：增删改查。"""

    def __init__(self, commands, parent=None):
        super().__init__(parent, 标题='自定义快捷命令配置', 最小尺寸=(560, 460))
        # 关闭即释放：旧实现每次开关都 new 一个 QDialog 且不释放（轻微内存泄漏）
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._commands = [c.copy() for c in commands]  # 深拷贝，取消时不影响原列表
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


class _命令编辑对话框(自绘外壳对话框):
    """编辑单个命令的对话框：名称 + 内容同时编辑。"""

    def __init__(self, name='', command='', parent=None):
        super().__init__(parent, 标题='编辑命令', 最小尺寸=(440, 260))
        # 关闭即释放：避免每次打开编辑框都残留一个未释放的 QDialog
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 最终值缓存在 Python 字段：WA_DeleteOnClose 关闭即销毁 C++ 控件，
        # 获取值若再读控件会抛 "QLineEdit already deleted"，故取值读字段
        self._名称 = name.strip()
        self._内容 = command.strip()
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
        self.btn_ok.clicked.connect(self._F提交)
        btn_row.addWidget(self.btn_ok)
        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

    def _F提交(self):
        """确定：先把控件值缓存到字段，再关闭对话框。"""
        self._名称 = self.name_edit.text().strip()
        self._内容 = self.command_edit.toPlainText().strip()
        self.accept()

    def 获取值(self):
        """返回 (名称, 内容)。读 Python 字段，不触碰可能已销毁的控件。"""
        return self._名称, self._内容
