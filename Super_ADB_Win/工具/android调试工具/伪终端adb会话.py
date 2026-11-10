# -*- coding: utf-8 -*-
"""
Win 非自研模式：基于 pywinpty 的伪终端 adb shell 会话。

与自研 ``交互式Shell`` / ``_AdbShell行会话`` 对外契约对齐：
  启动() / 发送输入(data) / 关闭() / 已关闭 / on_output(bytes) / on_close()

通过伪终端拉起持久的 ``adb -s <serial> shell``，adb 检测到 stdin 为终端后
在设备端分配真 PTY，获得保持目录/变量、设备端回显、行编辑等交互能力。
pywinpty 不可用时由上层回退到行模式会话。
"""

import threading


class _C伪终端Adb会话:
    """pywinpty 伪终端承载的交互式 adb shell 会话（Win 专属）。"""

    def __init__(self, adb_helper, serial, on_output, on_close):
        self.Vadb路径 = getattr(adb_helper, 'adb_path', None) or 'adb'
        self.V序列号 = serial
        self.on_output = on_output
        self.on_close = on_close
        self.V伪终端 = None
        self.V停止事件 = threading.Event()
        self.V发送锁 = threading.Lock()
        self._V输出线程 = None
        self.V已关闭 = False
        # 真 PTY 标记：区别于无 PTY 的行模式会话（供上层决定尺寸/回显逻辑）
        self.是行模式 = False

    # ── 对外契约 ──

    def 启动(self, cols: int = 200, rows: int = 25):
        """拉起伪终端与 adb shell 子进程，启动后台读取线程。

        pywinpty 导入或 spawn 失败时抛异常，由上层捕获并回退行模式。
        """
        # 延迟导入：未安装 pywinpty 时不影响主程序与其他功能
        from winpty import PtyProcess
        Vargv = [self.Vadb路径, '-s', self.V序列号, 'shell']
        self.V伪终端 = PtyProcess.spawn(Vargv, dimensions=(rows, cols))
        self._V输出线程 = threading.Thread(
            target=self._F读取循环, daemon=True)
        self._V输出线程.start()

    def 发送输入(self, data):
        """向伪终端写入输入；str 按 UTF-8 处理，bytes 先解码再转交。"""
        if self.V已关闭 or self.V伪终端 is None:
            return
        if isinstance(data, bytes):
            V文本 = data.decode('utf-8', 'replace')
        else:
            V文本 = data
        if not V文本:
            return
        try:
            with self.V发送锁:
                self.V伪终端.write(V文本)
        except Exception:
            pass  # 子进程已退出，关闭流程兜底

    def 设置尺寸(self, cols: int, rows: int):
        """同步伪终端窗口尺寸（列, 行）。"""
        try:
            if self.V伪终端 is not None:
                self.V伪终端.setwinsize(rows, cols)
        except Exception:
            pass  # 个别后端尺寸调整失败不阻断会话

    def 关闭(self):
        """终止伪终端、回收读取线程，并触发 on_close。"""
        if self.V已关闭:
            return
        self.V已关闭 = True
        self.V停止事件.set()
        self._F清理资源()
        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass

    @property
    def 已关闭(self):
        return self.V已关闭

    # ── 内部 ──

    def _F读取循环(self):
        """后台线程：持续读取伪终端输出并回调上层。"""
        while not self.V停止事件.is_set():
            if self.V伪终端 is None or not self.V伪终端.isalive():
                break
            try:
                V块 = self.V伪终端.read(8192)
            except EOFError:
                break
            except Exception:
                break
            if not V块:
                continue
            if isinstance(V块, str):
                V块 = V块.encode('utf-8', 'replace')
            try:
                self.on_output(V块)
            except Exception:
                pass
        self.关闭()

    def _F清理资源(self):
        """终止伪终端并回收读取线程，避免子进程/句柄残留。"""
        try:
            if self.V伪终端 is not None:
                self.V伪终端.terminate()
        except Exception:
            pass
        # 读取线程内部触发关闭时，当前线程就是输出线程自身，不能 join 自己
        # （Thread.join 连接本线程会抛 RuntimeError: cannot join current thread）
        if self._V输出线程 and self._V输出线程.is_alive():
            if threading.current_thread() is not self._V输出线程:
                self._V输出线程.join(timeout=2.0)
        self.V伪终端 = None
