# -*- coding: utf-8 -*-
"""
文件管理器右键「计算哈希」独立入口
=================================
由 Windows 资源管理器右键菜单调用：
  pythonw 哈希上下文菜单.py "%1"
接收任意数量的文件路径，用 compute_hashes_batch 计算 MD5/SHA1/SHA256，
弹窗展示每个文件的哈希值（带复制按钮 + 一键复制全部）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 加上项目根目录和工具目录，保证独立运行时能找到所有模块
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
for _sub in ('工具', '项目UI'):
    _p = os.path.join(_project_root, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QScrollArea, QWidget, QGroupBox, QMessageBox,
    QCheckBox,
)

from 项目UI import png_rc  # noqa: F401

from 项目UI.界面样式 import ACCENT, FONT_FAMILY, STYLE_SHEET, get_stylesheet, get_current_theme_id, THEMES
from 项目UI.弹窗样式 import add_green_glow, highlight_card_style, _create_popup_card
from 哈希校验对话框 import compute_hashes_batch, ALGO_ORDER


class 哈希上下文菜单(QDialog):
    def __init__(self, results, algo_keys=None, parent=None):
        super().__init__(parent)
        self._algo_keys = list(algo_keys) if algo_keys else ['MD5', 'SHA1', 'SHA256']
        self._results_raw = results  # 保存原始小写哈希值
        if results:
            first_name = os.path.basename(results[0][0])
            title = f"哈希计算结果 - {first_name}"
            if len(results) > 1:
                title += f" 等 {len(results)} 个文件"
        else:
            title = "哈希计算结果"
        self.setWindowTitle(title)
        self._theme_id = get_current_theme_id(self)
        self._accent = THEMES[self._theme_id]['accent']
        self.setStyleSheet(get_stylesheet(self._theme_id))
        self.setMinimumSize(640, 480)
        self.setWindowIcon(QIcon(':/Super_ADB.png'))

        # 大小写偏好持久化（默认勾选=大写）
        self._settings = QSettings('Super_ADB', 'Md5Tool')
        self._upper_case = self._settings.value('upper_case', True, type=bool)

        # 内层亮边卡片（与 TCPDump/PCAP 弹窗同款 4px 主题色边框）
        self.card, _ = _create_popup_card(self, self._theme_id)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        root.addWidget(QLabel("右键菜单「计算哈希」结果："))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        v = QVBoxLayout(container)
        v.setSpacing(10)

        for path, res in results:
            box = QGroupBox(os.path.basename(path))
            bv = QVBoxLayout(box)
            box.setToolTip(path)
            if 'error' in res:
                err = QLabel(f"计算失败：{res['error']}")
                err.setStyleSheet("color: #e57373;")
                bv.addWidget(err)
            else:
                for key in self._algo_keys:
                    val = res.get(key)
                    if not val:
                        continue
                    row = QHBoxLayout()
                    tag = QLabel(key)
                    tag.setFixedWidth(64)
                    tag.setStyleSheet(f"color: {self._accent}; font-weight: bold;")
                    row.addWidget(tag)
                    val_lbl = QLabel(self._fmt_case(val))
                    val_lbl.setFont(QFont(FONT_FAMILY, 10))
                    val_lbl.setWordWrap(True)
                    val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    val_lbl.setProperty('raw_value', val)  # 保存原始小写值
                    row.addWidget(val_lbl, 1)
                    btn = QPushButton("复制")
                    btn.setFixedWidth(60)
                    btn.setFixedHeight(24)
                    btn.clicked.connect(
                        lambda checked, v=val: self._copy(v, btn))
                    row.addWidget(btn)
                    bv.addLayout(row)
            v.addWidget(box)

        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        btn_all = QPushButton("复制全部")
        btn_all.setFixedWidth(100)
        btn_all.clicked.connect(lambda: self._copy_all(results))
        bottom.addWidget(btn_all)
        # 大小写勾选框（默认勾选=大写）
        self.chk_upper = QCheckBox("大写")
        self.chk_upper.setChecked(self._upper_case)
        self.chk_upper.setToolTip("勾选时哈希值字母显示为大写")
        self.chk_upper.toggled.connect(self._on_case_toggled)
        bottom.addWidget(self.chk_upper)
        bottom.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        root.addLayout(bottom)

    def _fmt_case(self, text):
        """按当前大小写设置格式化文本。"""
        return text.upper() if self._upper_case else text

    def _on_case_toggled(self, checked):
        """切换大小写时，实时更新所有哈希标签显示。"""
        self._upper_case = checked
        self._settings.setValue('upper_case', checked)
        # 遍历所有哈希值标签，更新显示
        for lbl in self.findChildren(QLabel):
            raw = lbl.property('raw_value')
            if raw and isinstance(raw, str):
                lbl.setText(self._fmt_case(raw))

    def apply_theme(self, theme_id):
        """运行时切换主题。"""
        if theme_id not in THEMES:
            theme_id = 'dark_cyan'
        self._theme_id = theme_id
        self._accent = THEMES[theme_id]['accent']
        self.setStyleSheet(get_stylesheet(theme_id))
        self.card.setStyleSheet(highlight_card_style(theme_id))
        add_green_glow(self.card, accent=QColor(self._accent))
        self.update()

    def _copy(self, text, btn):
        QApplication.clipboard().setText(self._fmt_case(text))
        old = btn.text()
        btn.setText("已复制")
        btn.setEnabled(False)
        QApplication.processEvents()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(800, lambda: (btn.setText(old), btn.setEnabled(True)))

    def _copy_all(self, results):
        lines = []
        for path, res in results:
            lines.append(os.path.basename(path))
            if 'error' in res:
                lines.append(f"  错误: {res['error']}")
                continue
            for key in self._algo_keys:
                if res.get(key):
                    lines.append(f"  {key}: {self._fmt_case(res[key])}")
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, "已复制", "所有哈希已复制到剪贴板。")


def main():
    app = QApplication(sys.argv)
    # 与 Md5Tool 弹窗共用同一勾选配置，右键结果按用户勾选的算法展示
    settings = QSettings('Super_ADB', 'Md5Tool')
    saved = settings.value('algos', 'MD5,SHA1,SHA256')
    algo_keys = [a for a in str(saved).split(',') if a in ALGO_ORDER]
    if not algo_keys:
        algo_keys = ['MD5', 'SHA1', 'SHA256']

    paths = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if not paths:
        return
    results = compute_hashes_batch(paths, algo_keys=algo_keys)
    哈希上下文菜单(results, algo_keys=algo_keys).exec()


if __name__ == '__main__':
    main()
