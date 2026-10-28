# -*- coding: utf-8 -*-
"""
Apifox 共享文档接口提取弹窗
==========================
点击主界面「便捷工具 → Apifox共享提取」按钮弹出的独立窗口：

- 输入 Apifox 共享文档链接（s.apifox.cn/xxx），点击「提取」后台执行
  工具/便捷工具/Apifox接口提取.py 的完整流程（解析文档 ID → 拉接口树 →
  并发抓取详情 → 写入 Excel）；
- 日志逐行实时滚动显示，方便观察进度与失败项；
- 提取成功后提供「打开输出文件夹」与「打开 Excel」快捷入口；
- Excel 统一保存到 桌面/Super_ADB 文件夹（自动创建，处理 OneDrive 重定向）。

命名遵循项目中文规范：类 C 前缀、方法 F 前缀、变量 V 前缀。
"""
import os
import re
import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from 项目UI.对话框基类 import 对话框基类
from 项目UI.界面样式 import THEMES, FONT_FAMILY
from 项目UI.弹窗样式 import _create_popup_card, highlight_card_style

# 共享链接里的 UUID 文档 ID（与 Apifox接口提取.py 同一规则）
_DOC_ID_RE = re.compile(
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
)


class Apifox提取线程(QThread):
    """后台线程：执行 Apifox 提取全流程，逐行回传日志。"""

    日志 = Signal(str)          # 逐行日志
    完成 = Signal(str)          # 输出 Excel 文件路径
    失败 = Signal(str)          # 错误信息

    def __init__(self, doc_url, parent=None):
        super().__init__(parent)
        self._url = doc_url

    def run(self):
        try:
            # 惰性导入：requests / openpyxl 较重，放到真正开始提取时再加载
            from 工具.便捷工具.Apifox接口提取 import run_extract
            output = run_extract(self._url, log_func=self.日志.emit)
            self.完成.emit(output)
        except Exception as e:
            self.失败.emit(str(e))


class Apifox提取对话框(对话框基类):
    """Apifox 共享文档提取弹窗。"""

    def __init__(self, parent=None):
        super().__init__(parent, 标题="Apifox 共享提取", 最小尺寸=(660, 480), 发光=False)
        self._theme_id = self._主题id  # 兼容旧代码引用
        self._accent = THEMES[self._主题id]['accent']
        self._worker = None           # 当前执行中的提取线程
        self._输出文件 = None          # 最近一次成功导出的 Excel 路径

        # 内层亮边卡片（与其他弹窗同款主题色边框）
        self.card, _ = _create_popup_card(self, self._theme_id)
        root = QVBoxLayout(self.card)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # 说明文字
        tip = QLabel(
            "输入 Apifox 共享文档链接（s.apifox.cn/xxx），点击「提取」"
            "将全部接口导出为 Excel，保存到 桌面/Super_ADB 文件夹。")
        tip.setWordWrap(True)
        tip.setStyleSheet(
            f"color: {THEMES[self._theme_id]['text_disabled']}; font-size: 9pt;")
        root.addWidget(tip)

        # 共享地址输入行
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel("共享地址:")
        lbl.setStyleSheet(f"color: {self._accent}; font-weight: bold;")
        row.addWidget(lbl)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://s.apifox.cn/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        self.url_edit.setClearButtonEnabled(True)
        self._预填默认链接()
        row.addWidget(self.url_edit, 1)

        self.btn_extract = QPushButton("提取")
        self.btn_extract.setFixedWidth(96)
        self.btn_extract.setFixedHeight(32)
        self.btn_extract.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_extract.clicked.connect(self._开始提取)
        row.addWidget(self.btn_extract)
        root.addLayout(row)

        # 日志区
        log_label = QLabel("执行日志")
        log_label.setStyleSheet(f"color: {self._accent}; font-size: 9pt; font-weight: bold;")
        root.addWidget(log_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(8000)
        self.log_view.setFont(QFont(FONT_FAMILY, 9))
        self.log_view.setStyleSheet(self._日志样式())
        root.addWidget(self.log_view, 1)

        # 底部操作栏
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.btn_open_dir = QPushButton("打开输出文件夹")
        self.btn_open_dir.setFixedWidth(130)
        self.btn_open_dir.setEnabled(False)
        self.btn_open_dir.clicked.connect(self._打开输出文件夹)
        bottom.addWidget(self.btn_open_dir)
        self.btn_open_file = QPushButton("打开 Excel")
        self.btn_open_file.setFixedWidth(110)
        self.btn_open_file.setEnabled(False)
        self.btn_open_file.clicked.connect(self._打开Excel)
        bottom.addWidget(self.btn_open_file)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    # 初始化辅助
    # ------------------------------------------------------------------
    def _预填默认链接(self):
        """从提取脚本读取内置默认链接，预填到输入框。"""
        try:
            from 工具.便捷工具.Apifox接口提取 import DEFAULT_DOC_URL
            if DEFAULT_DOC_URL:
                self.url_edit.setText(DEFAULT_DOC_URL.strip())
        except Exception:
            pass

    def _日志样式(self):
        bg = THEMES[self._theme_id]['bg_input']
        fg = THEMES[self._theme_id].get('text_primary', '#dddddd')
        return (
            f"QPlainTextEdit {{ background: {bg}; color: {fg};"
            f" border: 1px solid {self._accent}; border-radius: 6px;"
            " font-size: 9pt; }}"
        )

    def _日志(self, text):
        self.log_view.appendPlainText(text)

    # ------------------------------------------------------------------
    # 提取流程
    # ------------------------------------------------------------------
    def _开始提取(self):
        """校验链接并启动后台提取线程。"""
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "缺少地址", "请先输入 Apifox 共享文档链接。")
            self.url_edit.setFocus()
            return
        if not _DOC_ID_RE.search(url):
            QMessageBox.warning(
                self, "链接无效",
                "链接中未找到文档 ID（UUID）。\n"
                "请粘贴完整的 Apifox 共享链接，例如：\n"
                "https://s.apifox.cn/c7c78ea0-4189-4301-892e-caa2c6416d84")
            self.url_edit.setFocus()
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在提取", "已有提取任务在执行中，请稍候。")
            return

        self._输出文件 = None
        self.btn_open_dir.setEnabled(False)
        self.btn_open_file.setEnabled(False)
        self.btn_extract.setEnabled(False)
        self.btn_extract.setText("提取中…")
        self.log_view.clear()
        self._日志(f"开始提取：{url}\n")

        self._worker = Apifox提取线程(url, self)
        self._worker.日志.connect(self._日志)
        self._worker.完成.connect(self._提取完成)
        self._worker.失败.connect(self._提取失败)
        self._worker.finished.connect(self._线程结束)
        self._worker.start()

    def _提取完成(self, output_path):
        self._输出文件 = output_path
        self._日志("\n[完成] 提取成功。")
        self.btn_open_dir.setEnabled(True)
        self.btn_open_file.setEnabled(True)

    def _提取失败(self, err):
        self._日志(f"\n[失败] {err}")

    def _线程结束(self):
        """线程结束后恢复按钮，并释放引用（延迟到 C++ 对象销毁）。"""
        self.btn_extract.setEnabled(True)
        self.btn_extract.setText("提取")

    # ------------------------------------------------------------------
    # 打开产物
    # ------------------------------------------------------------------
    def _打开输出文件夹(self):
        if not self._输出文件:
            return
        folder = os.path.dirname(self._输出文件)
        self._打开路径(folder)

    def _打开Excel(self):
        if self._输出文件 and os.path.isfile(self._输出文件):
            self._打开路径(self._输出文件)

    @staticmethod
    def _打开路径(path):
        """跨平台打开文件/文件夹。"""
        try:
            if sys.platform == 'win32':
                os.startfile(path)  # noqa: S606
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', path])
            else:
                import subprocess
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            QMessageBox.warning(None, "打开失败", f"无法打开：\n{path}\n\n{e}")

    # ------------------------------------------------------------------
    # 主题切换
    # ------------------------------------------------------------------
    def apply_theme(self, theme_id):
        """主窗口切换主题时刷新弹窗样式。"""
        if theme_id not in THEMES or theme_id == self._theme_id:
            return
        super().apply_theme(theme_id)
        self._theme_id = theme_id
        self._accent = THEMES[theme_id]['accent']
        self.card.setStyleSheet(highlight_card_style(theme_id))
        self.log_view.setStyleSheet(self._日志样式())
        for lbl in self.findChildren(QLabel):
            if lbl.text() == "共享地址:":
                lbl.setStyleSheet(f"color: {self._accent}; font-weight: bold;")
            elif lbl.text() == "执行日志":
                lbl.setStyleSheet(
                    f"color: {self._accent}; font-size: 9pt; font-weight: bold;")
