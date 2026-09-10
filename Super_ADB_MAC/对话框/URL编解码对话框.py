# -*- coding: utf-8 -*-
"""
URL 编解码弹窗
==============
点击主界面「便捷工具 → 编码工具 → URL编解码」按钮弹出的独立窗口：
- URL 编码：文本 → RFC3986 百分号编码（UTF-8，空格 → %20，不使用 + ）
- URL 解码：百分号编码 → 原文（容忍非法转义序列，原样保留）
- 输入 / 结果均支持多行；结果可一键复制 / 回填输入继续处理

命名约定：本项目新代码按 C类名 / F方法名 / 私有 _C类名 / _F方法名 命名，
         名称使用中文、前面加字母前缀。本类即按该约定编写
         （__init__ / apply_theme 为 Qt 与主题系统接口，保留原名）。
"""

import sys

from urllib.parse import quote, unquote

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QColor
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox,
)

from 项目UI import png_rc  # noqa: F401
from 项目UI.界面样式 import FONT_FAMILY, get_stylesheet, get_current_theme_id, THEMES
from 项目UI.弹窗样式 import add_green_glow, highlight_card_style, _create_popup_card


class CURL编解码对话框(QDialog):
    """URL 编码 / 解码工具弹窗（与其他弹窗同款高亮卡片样式）。

    C 前缀类名、F 前缀公开方法、_F 前缀私有方法（项目新代码命名约定：
    中文名称前面加字母前缀）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("URL 编解码")
        self.setWindowIcon(QIcon(":/Super_ADB.png"))
        self.setMinimumWidth(560)
        self._theme_id = get_current_theme_id(self)
        self.setStyleSheet(get_stylesheet(self._theme_id))
        # 内层亮边卡片（与时间戳 / TCPDump / PCAP 弹窗同款 4px 主题色边框）
        self.card, _ = _create_popup_card(self, self._theme_id)
        self._F构建界面()
        self.F清空()

    # —— 主题系统接口：主窗口 主入口_主题系统._传播主题到弹窗 鸭子类型调用 ——
    def apply_theme(self, theme_id):
        """运行时切换主题：更新全局 QSS + 外发光。"""
        if theme_id not in THEMES or theme_id == self._theme_id:
            return
        self._theme_id = theme_id
        self.setStyleSheet(get_stylesheet(theme_id))
        self.card.setStyleSheet(highlight_card_style(theme_id))
        add_green_glow(self.card, accent=QColor(THEMES[theme_id]['accent']))
        self.update()

    # —— 公开能力 ——
    def F编码(self):
        """URL 编码：UTF-8 百分号编码，除未保留字符外全部转义（空格 → %20）。"""
        text = self._input.toPlainText()
        if not text:
            self._result.setPlainText("")
            return
        try:
            encoded = quote(text, safe='')
        except Exception as e:  # noqa: BLE001 - 工具类弹窗，任何异常都给用户可见提示
            self._result.setPlainText(f"编码失败: {e!r}")
            return
        self._result.setPlainText(encoded)

    def F解码(self):
        """URL 解码：还原百分号编码（容忍非法转义序列，原样保留）。"""
        text = self._input.toPlainText()
        if not text:
            self._result.setPlainText("")
            return
        self._result.setPlainText(unquote(text))

    def F清空(self):
        """清空输入与结果。"""
        self._input.clear()
        self._result.clear()

    def F回填(self):
        """把结果回填到输入框，便于连续处理（编码 → 解码 → 再编码…）。"""
        out = self._result.toPlainText()
        if out:
            self._input.setPlainText(out)

    def F复制(self):
        """复制结果到剪贴板。"""
        text = self._result.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    # —— 私有构建 ——
    def _F构建界面(self):
        root = QVBoxLayout(self.card)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # ── 输入 ──
        g_in = QGroupBox("输入")
        v_in = QVBoxLayout(g_in)
        v_in.setSpacing(8)
        self._input = QTextEdit()
        self._input.setAcceptRichText(False)
        self._input.setPlaceholderText("粘贴要处理的文本（支持多行）…")
        self._input.setFont(QFont(FONT_FAMILY, 10))
        self._input.setMinimumHeight(120)
        v_in.addWidget(self._input)
        root.addWidget(g_in)

        # ── 方向按钮 ──
        h_btns = QHBoxLayout()
        btn_encode = QPushButton("URL 编码")
        btn_encode.clicked.connect(self.F编码)
        btn_decode = QPushButton("URL 解码")
        btn_decode.clicked.connect(self.F解码)
        btn_swap = QPushButton("结果回填")
        btn_swap.clicked.connect(self.F回填)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.F清空)
        for b in (btn_encode, btn_decode, btn_swap, btn_clear):
            b.setFixedWidth(96)
            h_btns.addWidget(b)
        h_btns.addStretch(1)
        root.addLayout(h_btns)

        # ── 结果 ──
        g_out = QGroupBox("结果")
        v_out = QVBoxLayout(g_out)
        v_out.setSpacing(8)
        self._result = QTextEdit()
        self._result.setReadOnly(True)
        self._result.setFont(QFont(FONT_FAMILY, 10))
        self._result.setMinimumHeight(120)
        v_out.addWidget(self._result)

        h_out = QHBoxLayout()
        hint = QLabel("UTF-8 百分号编码；空格 → %20，不使用 + ")
        hint.setStyleSheet(f'font: 9pt "{FONT_FAMILY}"; color: #999999;')
        btn_copy = QPushButton("复制结果")
        btn_copy.clicked.connect(self.F复制)
        h_out.addWidget(hint)
        h_out.addStretch(1)
        h_out.addWidget(btn_copy)
        v_out.addLayout(h_out)
        root.addWidget(g_out)


# ── 兼容旧引用 ──
# 主入口（主入口_弹窗打开.打开URL编解码）目前仍按旧英文名 CUrlCodecDialog 导入，
# 此处仅作向后兼容别名；新代码一律使用 CURL编解码对话框。
CUrlCodecDialog = CURL编解码对话框


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dlg = CURL编解码对话框()
    dlg.show()
    sys.exit(app.exec())
