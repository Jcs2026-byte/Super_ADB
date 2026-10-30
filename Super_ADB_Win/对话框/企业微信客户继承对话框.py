# -*- coding: utf-8 -*-
"""
企业微信客户继承弹窗
====================
点击主界面「便捷工具 → 企业微信客户继承」按钮弹出的独立窗口。

业务背景
--------
企业微信「客户继承 / 转接」接口：
- 单次请求 customer_list 过大时会返回「参数不合法」；
- 本弹窗直接从用户粘贴的请求体里读 customer_list，自动拆小批、
  线程池并发发送；某批失败时自动对半拆分重试到单条。

界面组成
--------
- URL、请求头 (JSON)、请求体 (JSON)：直接从浏览器 F12 复制粘贴；
- 每批条数 + 并发线程；
- 响应日志。
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from 项目UI.对话框基类 import 对话框基类
from 项目UI.界面样式 import THEMES, FONT_FAMILY
from 项目UI.弹窗样式 import _create_popup_card, highlight_card_style


_V_默认请求头 = json.dumps({"Content-Type": "application/json"}, ensure_ascii=False, indent=2)


class C企业微信请求线程(QThread):
    """后台线程：把 customer_list 拆成小批，用线程池并发发送。"""

    日志 = Signal(str)
    全部完成 = Signal(int, int, int)
    失败 = Signal(str)

    def __init__(self, url, headers_obj, body_template, 客户列表,
                 批次大小=20, 并发数=5, 超时秒=20, 批间延迟ms=0, parent=None):
        super().__init__(parent)
        self._url = url
        self._headers = headers_obj
        self._body_template = body_template
        self._客户列表 = 客户列表
        self._批次大小 = max(1, int(批次大小))
        self._并发数 = max(1, int(并发数))
        self._超时秒 = max(5, int(超时秒))
        self._批间延迟秒 = max(0, int(批间延迟ms)) / 1000.0
        self._停止 = False

    def stop(self):
        self._停止 = True

    def _F构造批次体(self, 切片):
        body = json.loads(json.dumps(self._body_template, ensure_ascii=False))
        body["customer_req"]["customer_list"] = 切片
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _F发一批(self, 序号, 切片):
        """发送单个批次，返回 (序号, 条数, data, is_err, err_msg)。"""
        if self._停止:
            return 序号, len(切片), {}, True, "已中止"
        try:
            from 工具.便捷工具 import fetch
            resp = fetch.post(
                self._url, headers=self._headers,
                data=self._F构造批次体(切片),
                timeout=self._超时秒, check_status=False,
            )
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text[:500]}
            data["_http_status"] = resp.status
        except Exception as e:
            return 序号, len(切片), {}, True, str(e)

        # 量大报错 → 自动对半拆分重试
        errcode = data.get("errcode")
        errmsg = str(data.get("errmsg") or data.get("humanMessage") or "")
        if errcode not in (0, "0") and len(切片) > 1 and (
            errcode in (40058, "40058")
            or "参数不合法" in errmsg
            or "too many" in errmsg.lower()
        ):
            self.日志.emit(
                f"[第 {序号} 批] {len(切片)} 条返回 errcode={errcode}，自动对半拆分重试...")
            mid = len(切片) // 2
            结果 = {"_http_status": resp.status, "_split_retries": []}
            for sub in (切片[:mid], 切片[mid:]):
                if not sub or self._停止:
                    continue
                _, _, sub_data, sub_err, sub_msg = self._F发一批(序号, sub)
                结果["_split_retries"].append(sub_data if not sub_err else {"error": sub_msg})
            return 序号, len(切片), 结果, False, ""
        return 序号, len(切片), data, False, ""

    def run(self):
        总条数 = len(self._客户列表)
        批次总数 = (总条数 + self._批次大小 - 1) // self._批次大小
        self.日志.emit(
            f"共 {总条数} 条客户，拆成 {批次总数} 批（每批 {self._批次大小} 条），"
            f"并发 {self._并发数} 线程"
            f"{'，波间延迟 ' + str(int(self._批间延迟秒 * 1000)) + 'ms' if self._批间延迟秒 > 0 else ''}。\n")

        成功批数 = 0
        失败批数 = 0
        批次切片 = [
            (i + 1, self._客户列表[i * self._批次大小:(i + 1) * self._批次大小])
            for i in range(批次总数)
        ]

        # 波浪式提交：每波最多并发数个批次，波间 sleep 延迟，避免触发腾讯接口高频限制
        波次 = 0
        for 起始 in range(0, len(批次切片), self._并发数):
            if self._停止:
                break
            波次 += 1
            本波 = 批次切片[起始:起始 + self._并发数]
            with ThreadPoolExecutor(max_workers=len(本波)) as ex:
                future_map = {ex.submit(self._F发一批, n, s): (n, len(s)) for n, s in 本波}
                for fut in as_completed(future_map):
                    序号, 条数, data, is_err, err_msg = fut.result()
                    if self._停止 and is_err and err_msg == "已中止":
                        self.日志.emit(f"[第 {序号} 批] 已跳过（用户中止）")
                        continue
                    if is_err:
                        失败批数 += 1
                        self.日志.emit(f"[第 {序号}/{批次总数} 批] HTTP 异常：{err_msg}")
                    else:
                        errcode = data.get("errcode")
                        errmsg = data.get("errmsg") or data.get("humanMessage") or ""
                        http_status = data.get("_http_status", "?")
                        if errcode in (0, "0"):
                            成功批数 += 1
                            self.日志.emit(f"[第 {序号}/{批次总数} 批] HTTP {http_status} ✓ 成功（{条数} 条）")
                        else:
                            失败批数 += 1
                            self.日志.emit(
                                f"[第 {序号}/{批次总数} 批] HTTP {http_status} ✗ errcode={errcode} {errmsg}")
            # 波间延迟（最后一波后不需要等）
            if self._批间延迟秒 > 0 and 起始 + self._并发数 < len(批次切片) and not self._停止:
                self.日志.emit(f"  ── 第 {波次} 波完成，等待 {int(self._批间延迟秒 * 1000)}ms 后继续 ──\n")
                # 分段 sleep 以便及时响应停止
                等待截止 = time.monotonic() + self._批间延迟秒
                while time.monotonic() < 等待截止:
                    if self._停止:
                        break
                    time.sleep(min(0.2, 等待截止 - time.monotonic()))

        self.全部完成.emit(批次总数, 成功批数, 失败批数)


class C企业微信客户继承对话框(对话框基类):
    """企业微信客户继承弹窗。"""

    def __init__(self, parent=None):
        super().__init__(parent, 标题="企业微信客户继承", 最小尺寸=(780, 720), 发光=False)
        self._主题id = self._主题id
        self._accent = THEMES[self._主题id]['accent']
        self._worker = None

        self.card, _ = _create_popup_card(self, self._主题id)
        root = QVBoxLayout(self.card)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        tip = QLabel(
            "填 URL、请求头、请求体（从浏览器 F12 复制）。"
            "工具自动把请求体里的 customer_list 拆成小批多线程并发发送，"
            "某批返回「参数不合法」时自动对半拆分重试。")
        tip.setWordWrap(True)
        tip.setStyleSheet(
            f"color: {THEMES[self._主题id]['text_disabled']}; font-size: 9pt;")
        root.addWidget(tip)

        # URL
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        url_lbl = QLabel("请求 URL:")
        url_lbl.setStyleSheet(f"color: {self._accent}; font-weight: bold;")
        url_row.addWidget(url_lbl)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://work.weixin.qq.com/work_admin/...")
        self.url_edit.setClearButtonEnabled(True)
        url_row.addWidget(self.url_edit, 1)
        root.addLayout(url_row)

        # 请求头
        hdr_lbl = QLabel("请求头 (JSON)：从浏览器 F12 完整复制，含 Cookie")
        hdr_lbl.setStyleSheet(f"color: {self._accent}; font-size: 9pt; font-weight: bold;")
        root.addWidget(hdr_lbl)
        self.headers_edit = QPlainTextEdit()
        self.headers_edit.setPlainText(_V_默认请求头)
        self.headers_edit.setMaximumHeight(90)
        self.headers_edit.setFont(QFont(FONT_FAMILY, 9))
        self.headers_edit.setStyleSheet(self._日志样式())
        root.addWidget(self.headers_edit)

        # 请求体
        body_lbl = QLabel("请求体 (JSON)：从浏览器 F12 完整复制，customer_list 会自动拆批")
        body_lbl.setStyleSheet(f"color: {self._accent}; font-size: 9pt; font-weight: bold;")
        root.addWidget(body_lbl)
        self.body_edit = QPlainTextEdit()
        self.body_edit.setMaximumHeight(260)
        self.body_edit.setFont(QFont(FONT_FAMILY, 9))
        self.body_edit.setStyleSheet(self._日志样式())
        root.addWidget(self.body_edit)

        # 参数行
        opt_row = QHBoxLayout()
        opt_row.setSpacing(12)
        opt_row.addWidget(QLabel("每批条数:"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 500)
        self.batch_spin.setValue(20)
        opt_row.addWidget(self.batch_spin)
        opt_row.addWidget(QLabel("并发线程:"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 20)
        self.concurrency_spin.setValue(5)
        opt_row.addWidget(self.concurrency_spin)
        opt_row.addWidget(QLabel("批间延迟:"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 60000)
        self.delay_spin.setValue(500)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setToolTip("每波并发批次之间的等待时间，0=不等待。"
                                   "腾讯接口有高频限制，建议 300-1000ms")
        opt_row.addWidget(self.delay_spin)
        opt_row.addStretch()
        self.btn_send = QPushButton("开始发送")
        self.btn_send.setFixedWidth(110)
        self.btn_send.setFixedHeight(30)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self._开始发送)
        opt_row.addWidget(self.btn_send)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setFixedWidth(80)
        self.btn_stop.setFixedHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._停止发送)
        opt_row.addWidget(self.btn_stop)
        root.addLayout(opt_row)

        # 日志
        log_lbl = QLabel("响应日志")
        log_lbl.setStyleSheet(f"color: {self._accent}; font-size: 9pt; font-weight: bold;")
        root.addWidget(log_lbl)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(20000)
        self.log_view.setFont(QFont(FONT_FAMILY, 9))
        self.log_view.setStyleSheet(self._日志样式())
        root.addWidget(self.log_view, 1)

    def _日志样式(self):
        bg = THEMES[self._主题id]['bg_input']
        fg = THEMES[self._主题id].get('text_primary', '#dddddd')
        return (
            f"QPlainTextEdit {{ background: {bg}; color: {fg};"
            f" border: 1px solid {self._accent}; border-radius: 6px;"
            " font-size: 9pt; }}"
        )

    def _日志(self, text):
        self.log_view.appendPlainText(text)

    def _开始发送(self):
        V_url = self.url_edit.text().strip()
        if not V_url:
            QMessageBox.warning(self, "缺少 URL", "请填写请求 URL。")
            return
        try:
            V_headers = json.loads(self.headers_edit.toPlainText() or "{}")
            if not isinstance(V_headers, dict):
                raise ValueError("请求头必须是 JSON 对象")
        except Exception as e:
            QMessageBox.warning(self, "请求头 JSON 错误", str(e))
            return
        # 请求头只允许 ASCII（latin-1），中文直接拦
        for _hk, _hv in V_headers.items():
            try:
                str(_hv).encode("latin-1")
            except UnicodeEncodeError:
                QMessageBox.warning(
                    self, "请求头含非 ASCII 字符",
                    f'请求头 "{_hk}" 的值含中文/特殊字符，HTTP 头只允许英文。\n'
                    "请从浏览器 F12 → Network → 对应请求 → Request Headers 里复制真实值。")
                return
        try:
            V_body = json.loads(self.body_edit.toPlainText())
            if not isinstance(V_body, dict):
                raise ValueError("请求体必须是 JSON 对象")
            if "customer_req" not in V_body or not isinstance(V_body["customer_req"], dict):
                raise ValueError("请求体必须包含 customer_req 对象")
        except Exception as e:
            QMessageBox.warning(self, "请求体 JSON 错误", str(e))
            return
        # 直接从请求体里取 customer_list
        V_原始列表 = V_body.get("customer_req", {}).get("customer_list", [])
        V_客户列表 = [
            {"customer_id": c.get("customer_id", ""),
             "origin_owner_vid": c.get("origin_owner_vid", "")}
            for c in V_原始列表 if isinstance(c, dict)
        ]
        if not V_客户列表:
            QMessageBox.warning(self, "无客户", "请求体 customer_req.customer_list 里至少要有一条客户。")
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在发送", "已有任务在执行中。")
            return

        self.log_view.clear()
        self.btn_send.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._worker = C企业微信请求线程(
            url=V_url, headers_obj=V_headers, body_template=V_body,
            客户列表=V_客户列表, 批次大小=self.batch_spin.value(),
            并发数=self.concurrency_spin.value(),
            批间延迟ms=self.delay_spin.value(), parent=self,
        )
        self._worker.日志.connect(self._日志)
        self._worker.全部完成.connect(self._发送完成)
        self._worker.失败.connect(self._发送失败)
        self._worker.finished.connect(self._线程结束)
        self._worker.start()

    def _停止发送(self):
        if self._worker is not None:
            self._worker.stop()
            self.btn_stop.setEnabled(False)
            self._日志("收到停止指令...")

    def _发送完成(self, 批次总数, 成功批数, 失败批数):
        self._日志(f"\n==== 全部结束：共 {批次总数} 批，成功 {成功批数} 批，失败 {失败批数} 批 ====")

    def _发送失败(self, err):
        self._日志(f"\n[致命错误] {err}")

    def _线程结束(self):
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def apply_theme(self, theme_id):
        if theme_id not in THEMES or theme_id == self._主题id:
            return
        super().apply_theme(theme_id)
        self._主题id = theme_id
        self._accent = THEMES[theme_id]['accent']
        self.card.setStyleSheet(highlight_card_style(theme_id))
        for V_w in (self.headers_edit, self.body_edit, self.log_view):
            V_w.setStyleSheet(self._日志样式())
