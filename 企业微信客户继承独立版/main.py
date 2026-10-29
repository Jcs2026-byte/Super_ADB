# -*- coding: utf-8 -*-
r"""
企业微信客户继承 · 独立版
=========================
零依赖单文件工具，可单独打包成 exe 在 Win7/Win10 上运行。
- 填 URL / 请求头 / 请求体模板；
- 批量客户列表每行 customer_id,origin_owner_vid；
- 自动拆小批 + 线程池并发发送；
- 某批返回「参数不合法」时自动对半拆分重试到单条；
- 实时日志显示每批结果。

打包（Win7 兼容）：
    py -3.8 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    pyinstaller --noconfirm --clean --onefile --windowed --name 企业微信客户继承 main.py
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------- Win7 兼容补丁：必须在 import PySide6 之前 ----------
# os.add_dll_directory() 依赖 Windows 8+ 的 AddDllDirectory API，
# PySide6 的 __init__.py 会调用它，在 Win7 (NT 6.1) 上抛 OSError WinError 127。
# 这里在 Win7 上把它 patch 成 no-op；PyInstaller onedir 模式下 DLL 都在
# _internal/ 目录，系统 DLL 搜索路径已覆盖，不需要这个 API。
if sys.platform == "win32":
    try:
        if sys.getwindowsversion().major < 6 or (
            sys.getwindowsversion().major == 6 and sys.getwindowsversion().minor < 2
        ):
            class _V空句柄:
                def close(self):
                    pass
            def _V_noop_add_dll_dir(path):
                return _V空句柄()
            os.add_dll_directory = _V_noop_add_dll_dir  # type: ignore[assignment]
    except Exception:
        pass

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from fetch import post as http_post


# ---------- 深色主题配色（与主项目暗色风格一致） ----------
_V_主题 = {
    "bg": "#1e1f26",
    "bg_input": "#2a2c36",
    "fg": "#dfe1e6",
    "fg_disabled": "#8a8d99",
    "accent": "#4aa3ff",
    "border": "#3a3d4a",
}

_V_默认请求体 = json.dumps({
    "to_succeed_vid": "1688856415913869",
    "customer_req": {
        "customer_list": [
            {"customer_id": "1688856592901944", "origin_owner_vid": "1688858077832921"}
        ],
        "succeed_wording": "您好，您的服务已升级，后续将由我的同事#{name}#接替我的工作，继续为您服务。",
        "oper_type": 1,
        "confirm_oper": False,
    },
}, ensure_ascii=False, indent=2)

_V_默认请求头 = json.dumps({"Content-Type": "application/json"}, ensure_ascii=False, indent=2)


class C请求线程(QThread):
    """后台线程：拆批 + 线程池并发发送，自动降级重试。"""

    日志 = Signal(str)
    全部完成 = Signal(int, int, int)   # 总批, 成功批, 失败批
    致命错误 = Signal(str)

    def __init__(self, url, headers_obj, body_template, 客户列表,
                 批次大小=20, 并发数=5, 超时秒=20, parent=None):
        super().__init__(parent)
        self._url = url
        self._headers = headers_obj
        self._body_template = body_template
        self._客户列表 = 客户列表
        self._批次大小 = max(1, int(批次大小))
        self._并发数 = max(1, int(并发数))
        self._超时秒 = max(5, int(超时秒))
        self._停止 = False

    def stop(self):
        self._停止 = True

    def _F构造批次体(self, 切片):
        body = json.loads(json.dumps(self._body_template, ensure_ascii=False))
        body["customer_req"]["customer_list"] = 切片
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _F发一批(self, 序号, 切片):
        """返回 (序号, 条数, data_dict, is_err, err_msg)。"""
        if self._停止:
            return 序号, len(切片), {}, True, "已中止"
        try:
            resp = http_post(
                self._url, headers=self._headers,
                data=self._F构造批次体(切片), timeout=self._超时秒,
                check_status=False,
            )
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text[:500]}
            data["_http_status"] = resp.status
        except Exception as e:
            return 序号, len(切片), {}, True, str(e)

        # 量大报错 → 自动对半拆分重试到单条
        errcode = data.get("errcode")
        errmsg = str(data.get("errmsg") or data.get("humanMessage") or "")
        if (errcode not in (0, "0") and len(切片) > 1 and (
                errcode in (40058, "40058")
                or "参数不合法" in errmsg
                or "too many" in errmsg.lower())):
            self.日志.emit(
                f"[第 {序号} 批] {len(切片)} 条返回 errcode={errcode}，自动对半拆分重试...")
            mid = len(切片) // 2
            结果 = {"_http_status": resp.status_code, "_split_retries": []}
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
            f"并发 {self._并发数} 线程。\n")

        成功批数 = 0
        失败批数 = 0
        批次切片 = [
            (i + 1, self._客户列表[i * self._批次大小:(i + 1) * self._批次大小])
            for i in range(批次总数)
        ]

        with ThreadPoolExecutor(max_workers=self._并发数) as ex:
            future_map = {ex.submit(self._F发一批, n, s): (n, len(s)) for n, s in 批次切片}
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

        self.全部完成.emit(批次总数, 成功批数, 失败批数)


class C主窗口(QWidget):
    def __init__(self):
        super().__init__()
        self._worker = None
        self.setWindowTitle("企业微信客户继承")
        self.setMinimumSize(780, 720)
        self.setStyleSheet(self._F全局样式())

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        tip = QLabel(
            "填 URL、请求头、请求体（从浏览器 F12 复制）。"
            "工具自动把请求体里的 customer_list 拆成小批多线程并发发送，"
            "某批返回「参数不合法」时自动对半拆分重试。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {_V_主题['fg_disabled']}; font-size: 9pt;")
        root.addWidget(tip)

        # URL
        url_row = QHBoxLayout()
        url_lbl = QLabel("请求 URL:")
        url_lbl.setStyleSheet(f"color: {_V_主题['accent']}; font-weight: bold;")
        url_row.addWidget(url_lbl)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/customer_transfer/batch?access_token=xxx")
        self.url_edit.setClearButtonEnabled(True)
        url_row.addWidget(self.url_edit, 1)
        root.addLayout(url_row)

        # 请求头
        root.addWidget(self._F小标题("请求头 (JSON)"))
        self.headers_edit = QPlainTextEdit()
        self.headers_edit.setPlainText(_V_默认请求头)
        self.headers_edit.setMaximumHeight(90)
        self.headers_edit.setFont(QFont("Consolas", 9))
        self.headers_edit.setStyleSheet(self._F输入样式())
        root.addWidget(self.headers_edit)

        # 请求体模板
        root.addWidget(self._F小标题("请求体模板 (JSON，customer_list 会被批量区自动替换并拆批)"))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlainText(_V_默认请求体)
        self.body_edit.setMaximumHeight(220)
        self.body_edit.setFont(QFont("Consolas", 9))
        self.body_edit.setStyleSheet(self._F输入样式())
        root.addWidget(self.body_edit)

        # 参数行：每批条数 / 并发线程 / 发送 / 停止
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
        opt_row.addStretch()
        self.btn_send = QPushButton("开始发送")
        self.btn_send.setFixedWidth(110)
        self.btn_send.setFixedHeight(30)
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.clicked.connect(self._F开始发送)
        opt_row.addWidget(self.btn_send)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setFixedWidth(80)
        self.btn_stop.setFixedHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._F停止发送)
        opt_row.addWidget(self.btn_stop)
        root.addLayout(opt_row)

        # 日志
        root.addWidget(self._F小标题("响应日志"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(20000)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setStyleSheet(self._F输入样式())
        root.addWidget(self.log_view, 1)

    # ---------- 样式辅助 ----------
    def _F全局样式(self):
        return f"""
            QWidget {{ background: {_V_主题['bg']}; color: {_V_主题['fg']}; font-size: 9pt; }}
            QLineEdit, QSpinBox {{
                background: {_V_主题['bg_input']}; border: 1px solid {_V_主题['border']};
                border-radius: 4px; padding: 4px 6px;
            }}
            QPushButton {{
                background: {_V_主题['bg_input']}; border: 1px solid {_V_主题['accent']};
                border-radius: 4px; padding: 4px 12px;
            }}
            QPushButton:hover {{ background: #35405a; }}
            QPushButton:disabled {{ color: {_V_主题['fg_disabled']}; border-color: {_V_主题['border']}; }}
        """

    def _F输入样式(self):
        return (f"QPlainTextEdit {{ background: {_V_主题['bg_input']}; color: {_V_主题['fg']};"
                f" border: 1px solid {_V_主题['accent']}; border-radius: 6px; }}")

    def _F小标题(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_V_主题['accent']}; font-size: 9pt; font-weight: bold;")
        return lbl

    # ---------- 业务 ----------
    def _F日志(self, text):
        self.log_view.appendPlainText(text)

    def _F开始发送(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "缺少 URL", "请填写请求 URL。")
            return
        try:
            headers = json.loads(self.headers_edit.toPlainText() or "{}")
            if not isinstance(headers, dict):
                raise ValueError("请求头必须是 JSON 对象")
        except Exception as e:
            QMessageBox.warning(self, "请求头 JSON 错误", str(e))
            return
        # 前置校验：HTTP 请求头只允许 ASCII (latin-1)，含中文直接拦
        for _hk, _hv in headers.items():
            try:
                str(_hv).encode("latin-1")
            except UnicodeEncodeError:
                QMessageBox.warning(
                    self, "请求头含非 ASCII 字符",
                    f'请求头 "{_hk}" 的值包含中文/特殊字符，HTTP 请求头只允许英文。\n'
                    f"请从浏览器 F12 → Network → 对应请求 → Request Headers 里\n"
                    f"复制真实的 {_hk} 值粘贴过来。")
                return
        try:
            body = json.loads(self.body_edit.toPlainText())
            if not isinstance(body, dict) or "customer_req" not in body:
                raise ValueError("请求体必须是包含 customer_req 的 JSON 对象")
        except Exception as e:
            QMessageBox.warning(self, "请求体 JSON 错误", str(e))
            return
        # 直接从请求体模板里取 customer_list 作为待拆分客户
        customers = body.get("customer_req", {}).get("customer_list", [])
        customers = [
            {"customer_id": c.get("customer_id", ""),
             "origin_owner_vid": c.get("origin_owner_vid", "")}
            for c in customers if isinstance(c, dict)
        ]
        if not customers:
            QMessageBox.warning(self, "无客户", "请求体模板的 customer_req.customer_list 里至少要有一条客户。")
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在发送", "已有任务在执行中。")
            return

        self.log_view.clear()
        self.btn_send.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._worker = C请求线程(
            url=url, headers_obj=headers, body_template=body,
            客户列表=customers, 批次大小=self.batch_spin.value(),
            并发数=self.concurrency_spin.value(), parent=self,
        )
        self._worker.日志.connect(self._F日志)
        self._worker.全部完成.connect(self._F发送完成)
        self._worker.finished.connect(self._F线程结束)
        self._worker.start()

    def _F停止发送(self):
        if self._worker:
            self._worker.stop()
            self.btn_stop.setEnabled(False)
            self._F日志("收到停止指令...")

    def _F发送完成(self, total, ok, fail):
        self._F日志(f"\n==== 全部结束：共 {total} 批，成功 {ok} 批，失败 {fail} 批 ====")

    def _F线程结束(self):
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("企业微信客户继承")
    win = C主窗口()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
