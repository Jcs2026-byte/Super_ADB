# -*- coding: utf-8 -*-
"""
对话框 / Ios调试模块 / 公共任务.py
==================================
跨线程执行工具函数的轻量桥：
后台线程跑函数 → 结果（或异常对象）通过 Qt 信号回到创建它的线程（主线程）执行槽。

用法：
    _b桥 = c任务桥(self)                 # 父对象对话框，确保生命周期
    _b桥._b完成信号.connect(self.f某某完成)  # 槽在主线程执行
    _b桥.f执行(_b函数, _b参数1, _b参数2=…)
    # 槽里收到：正常→函数返回值；异常→异常对象（判断 isinstance(Exception)）
"""
import threading

from PySide6.QtCore import QObject, Signal


class c任务桥(QObject):
    """在后台线程执行函数，并把结果/异常信号化回主线程（新建代码 c/f/b 前缀命名）。"""

    _b完成信号 = Signal(object)

    def __init__(self, _b宿主=None):
        super().__init__(_b宿主)

    def f执行(self, _b函数, *_b参数, **_b关键字):
        """启动后台线程执行 _b函数。结果或异常经 _b完成信号 发出。"""
        _b线程 = threading.Thread(
            target=self._f跑, args=(_b函数, _b参数, _b关键字), daemon=True)
        _b线程.start()

    def _f跑(self, _b函数, _b参数, _b关键字):
        try:
            _b结果 = _b函数(*_b参数, **_b关键字)
        except Exception as _b异常:  # noqa: BLE001 —— 跨线程必须捕获一切异常转发
            _b结果 = _b异常
        self._b完成信号.emit(_b结果)
