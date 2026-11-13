# -*- coding: utf-8 -*-
"""
证书安装对话框
==============
点击主界面「SSL」按钮弹出：
- 拖拽 PEM / CRT / CER 证书文件到拖拽区（也可点击选择文件）
- 检查设备 /system 分区读写权限（adb root + remount + 写入验证）
- 计算证书 subject hash（参考 哈希校验对话框._Pem主题哈希器：文件内容 MD5 取前 8 位）
- 重命名为 <hash>.0 并 adb push 到 /system/etc/security/cacerts/
- chmod 644 + chown root:root（系统证书规范权限）
- 根分区满盘（ext4 可用块为 0）时自动走 tmpfs 桥接兜底
- 输出框实时展示每一步执行的命令与结果

UI 与逻辑分离：本模块只依赖 adb 实例与 获取序列号 回调。
"""
import os
import shutil
import tempfile
import hashlib

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                               QPlainTextEdit, QFileDialog, QWidget)

from 项目UI.对话框基类 import 对话框基类
from 项目UI.界面样式 import THEMES
from 项目UI.弹窗样式 import 拖拽区域, add_green_glow, highlight_card_style, _create_popup_card


# ----------------------------------------------------------------------
# PEM 证书 subject hash（参考 哈希校验对话框._Pem主题哈希器）
# ----------------------------------------------------------------------
def 计算证书哈希(证书路径):
    """计算 PEM 证书的旧式 subject hash：文件内容 MD5 取前 8 位。

    与 Android 系统证书文件名 ``<hash>.0`` 对应。
    """
    md5 = hashlib.md5()
    with open(证书路径, 'rb') as f:
        while True:
            块 = f.read(64 * 1024)
            if not 块:
                break
            md5.update(块)
    return md5.hexdigest()[:8]


def _带单位转KB(文本):
    """把 ``243.3M`` / ``1024K`` / ``1.5G`` / ``512`` 转成 KB 整数；无法识别返回 None。"""
    import re
    if not 文本:
        return None
    m = re.match(r'^([\d.]+)\s*([kmgtKMGT])?$', 文本.strip())
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    单位 = (m.group(2) or '').upper()
    乘数 = {'': 1, 'K': 1, 'M': 1024, 'G': 1024 * 1024, 'T': 1024 * 1024 * 1024}
    return int(num * 乘数.get(单位, 1))


def _解析df可用KB(df输出, 挂载点='/system'):
    """从 df 输出中解析指定挂载点的可用空间（KB）。

    兼容多种 toybox/busybox/GNU df 变体：
    - GNU df -k: ``Filesystem 1K-blocks Used Available Use% Mounted on``
    - toybox df: ``Filesystem Size Used Free Blksize``（数值带 K/M/G 单位）

    返回 None 表示无法解析（调用方应跳过检查，不要误判为 0）。
    """
    行列表 = [l.strip() for l in (df输出 or '').splitlines() if l.strip()]
    # 过滤错误行 / 表头行
    有效行 = []
    for l in 行列表:
        低 = l.lower()
        if 'no such file' in 低 or 'not found' in 低 or 'usage:' in 低:
            continue
        if 低.startswith('filesystem'):
            continue
        有效行.append(l)
    if not 有效行:
        return None
    # 找包含挂载点的数据行（优先精确匹配挂载点列，否则取最后一行）
    数据行 = None
    for l in 有效行:
        if 挂载点 in l.split():
            数据行 = l
            break
    if 数据行 is None:
        数据行 = 有效行[-1]
    部分 = 数据行.split()
    if len(部分) < 4:
        return None
    # 第 4 列（index 3）在两种格式下都是可用/空闲空间
    return _带单位转KB(部分[3])


def _解析statfs可用KB(statf输出):
    """从 ``stat -f`` 输出中解析真正可分配的 KB。

    关键：ext4 的 ``Free`` 把根目录保留块（5%）也算进去，满盘时会出现
    ``Free`` 还有 969 块、但 ``Available`` 为 0。此时 root 同样分配不到块，
    写入必定 ENOSPC。df 的 Available 列在部分 toybox 上与 Free 同值，
    所以空间判定必须以 statfs 的 ``Available`` 为准。

    返回 None 表示无法解析。
    """
    import re
    块大小 = 4096
    可用块 = None
    for 行 in (statf输出 or '').splitlines():
        行 = 行.strip()
        if 行.startswith('Block Size'):
            数字 = re.findall(r'\d+', 行)
            if 数字:
                块大小 = int(数字[0])
        elif 行.startswith('Blocks'):
            数字 = re.search(r'Available:\s*(\d+)', 行)
            if 数字:
                可用块 = int(数字.group(1))
    if 可用块 is None:
        return None
    return 可用块 * 块大小 // 1024


# ----------------------------------------------------------------------
# 后台执行线程（避免卡 UI）
# ----------------------------------------------------------------------
class 证书安装线程(QThread):
    """后台执行：检查权限 / 安装证书，通过信号回传日志和结果。"""

    日志 = Signal(str)
    完成 = Signal(bool, str)  # 是否成功, 结果消息

    def __init__(self, adb, 序列号, 任务类型, 证书路径=None, 父=None):
        super().__init__(父)
        self._adb = adb
        self._序列号 = 序列号
        self._任务类型 = 任务类型  # '检查权限' or '安装证书'
        self._证书路径 = 证书路径

    def run(self):
        try:
            if self._任务类型 == '检查权限':
                self._检查权限()
            elif self._任务类型 == '安装证书':
                self._安装证书()
        except Exception as e:
            self.日志.emit(f'执行异常: {e}')
            self.完成.emit(False, str(e))

    def _检查权限(self):
        self.日志.emit('>>> 正在获取 root 权限并挂载 system 为可写...')
        报告 = self._adb.root并重新挂载(self._序列号)
        self.日志.emit(报告)
        可写 = '可在 /system 写入' in 报告
        if 可写:
            self.完成.emit(True, '系统分区已可写，可以安装证书')
        else:
            self.完成.emit(False, '系统分区仍为只读，无法安装证书')

    def _安装证书(self):
        if not self._证书路径 or not os.path.isfile(self._证书路径):
            self.完成.emit(False, '证书文件不存在')
            return
        # 1. 计算哈希
        self.日志.emit(f'>>> 计算证书 subject hash: {self._证书路径}')
        哈希值 = 计算证书哈希(self._证书路径)
        self.日志.emit(f'    hash = {哈希值}')
        # 2. 复制并重命名为 <hash>.0
        临时目录 = tempfile.gettempdir()
        临时路径 = os.path.join(临时目录, f'{哈希值}.0')
        shutil.copy(self._证书路径, 临时路径)
        self.日志.emit(f'    已重命名为: {哈希值}.0')
        # 3. 确保证书目录存在（个别设备缺 cacerts 目录会导致推送静默失败）
        self.日志.emit('>>> mkdir -p /system/etc/security/cacerts')
        try:
            mkdir_out = (self._adb.执行shell(
                self._序列号,
                'mkdir -p /system/etc/security/cacerts 2>&1 && echo MKDIR_OK',
                timeout=10) or '').strip()
            if 'MKDIR_OK' not in mkdir_out:
                self.日志.emit(f'    ✗ 创建证书目录失败: {mkdir_out or "无输出"}')
                self.完成.emit(False, '创建 /system/etc/security/cacerts 失败，请检查 root 权限')
                return
            self.日志.emit('    目录就绪')
        except Exception as e:
            self.日志.emit(f'    创建目录异常: {e}')
            self.完成.emit(False, f'创建证书目录失败: {e}')
            return

        证书目录 = '/system/etc/security/cacerts'
        远程路径 = f'{证书目录}/{哈希值}.0'
        证书大小KB = max(1, (os.path.getsize(临时路径) + 1023) // 1024)

        # 4. 目标目录空间检查（以 statfs 的 Available 为准：df 的 Available 会把
        #    ext4 保留池里的块算成“可用”，满盘时误判成还有几 MB 而放行）
        已桥接 = False
        try:
            statf_out = (self._adb.执行shell(
                self._序列号, f'stat -f {证书目录}', timeout=10) or '').strip()
            self.日志.emit('    目标目录 statfs: ' + ' | '.join(
                l.strip() for l in statf_out.splitlines() if l.strip()))
            可分配KB = _解析statfs可用KB(statf_out)
            if 可分配KB is None:
                self.日志.emit('    ⚠ 无法解析 statfs 输出，跳过空间检查')
            else:
                self.日志.emit(f'    可分配空间: {可分配KB} KB（证书需 {证书大小KB} KB）')
                if 可分配KB < 64:
                    self.日志.emit('    ⚠ 可分配块为 0 或极小：ext4 剩余块都在保留池里，'
                                   'root 也分配不到，df 显示“还剩几 MB”属于误判 → push 必然 ENOSPC')
                    已桥接 = self._临时挂载证书目录()
                    if not 已桥接:
                        self.完成.emit(False, '证书目录满盘且 tmpfs 桥接失败，详见日志')
                        return
        except Exception as e:
            self.日志.emit(f'    空间检查跳过: {e}')

        # 5. adb push（ENOSPC 时自动桥接后重试一次）
        for 第几次 in (1, 2):
            self.日志.emit(f'>>> adb push {临时路径} {远程路径}')
            try:
                结果 = self._adb.直接执行(self._序列号, ['push', 临时路径, 远程路径], timeout=30)
                self.日志.emit(f'    {结果.strip() or "推送成功"}')
                break
            except Exception as e:
                错误信息 = str(e)
                self.日志.emit(f'    ✗ 推送失败: {错误信息}')
                if 'No space left' in 错误信息 and not 已桥接 and 第几次 == 1:
                    self.日志.emit('    → 诊断: 目标分区无空闲块（ENOSPC），tmpfs 桥接后重试')
                    if self._临时挂载证书目录():
                        已桥接 = True
                        continue
                self._推送失败诊断(临时路径, 证书目录)
                self.完成.emit(False, f'推送失败: {错误信息}')
                return

        # 6. 权限：系统证书规范为 644 root:root（777 会被部分 ROM 的校验拒绝）
        self.日志.emit(f'>>> adb shell chown root:root {远程路径}; chmod 644 {远程路径}')
        try:
            权限输出 = (self._adb.执行shell(
                self._序列号,
                f'chown root:root {远程路径} 2>&1; chmod 644 {远程路径} 2>&1 && echo CHMOD_OK',
                timeout=10) or '').strip()
            if 'CHMOD_OK' not in 权限输出:
                self.日志.emit(f'    权限设置失败: {权限输出 or "无输出"}')
                self.完成.emit(False, f'chmod 失败: {权限输出 or 远程路径}')
                return
            self.日志.emit('    权限设置成功（644 root:root）')
        except Exception as e:
            self.日志.emit(f'    权限设置失败: {e}')
            self.完成.emit(False, f'chmod 失败: {e}')
            return

        # 7. 验证（硬性关卡：文件必须存在，且远端大小与本地一致）
        self.日志.emit(f'>>> 验证: adb shell ls -l {远程路径}')
        try:
            验证 = (self._adb.执行shell(
                self._序列号, f'ls -l {远程路径}', timeout=10) or '').strip()
        except Exception as e:
            验证 = f'验证异常: {e}'
        self.日志.emit(f'    {验证 or "无输出"}')
        if not 验证 or 'No such file' in 验证 or '验证异常' in 验证:
            self.完成.emit(False,
                           f'安装验证失败: 设备上不存在 {远程路径}'
                           f'（{验证 or "无输出"}）')
            return
        本地大小B = os.path.getsize(临时路径)
        try:
            远端大小 = (self._adb.执行shell(
                self._序列号, f'stat -c %s {远程路径} 2>&1', timeout=10) or '').strip()
            if 远端大小.isdigit() and int(远端大小) != 本地大小B:
                self.日志.emit(f'    ✗ 大小不一致: 本地 {本地大小B}B / 远端 {远端大小}B')
                self.完成.emit(False, f'安装验证失败: 远端大小 {远端大小}B ≠ 本地 {本地大小B}B')
                return
        except Exception as e:
            self.日志.emit(f'    大小校验跳过: {e}')
        if 已桥接:
            self.日志.emit('    ⚠ 本次经由 tmpfs 桥接安装：设备重启后挂载消失，证书需重新安装')
            self.完成.emit(True, f'证书安装成功（临时，重启后需重装）: {哈希值}.0')
            return
        self.完成.emit(True, f'证书安装成功: {哈希值}.0')

    def _统计目录条目(self, 目录):
        """统计目录内条目数量（ls -1A | wc -l）；异常返回 -1。"""
        try:
            输出 = (self._adb.执行shell(
                self._序列号, f'ls -1A {目录} 2>/dev/null | wc -l', timeout=10) or '').strip()
            数字 = 输出.split()[-1] if 输出 else ''
            return int(数字) if 数字.isdigit() else -1
        except Exception:
            return -1

    def _临时挂载证书目录(self, 证书目录='/system/etc/security/cacerts'):
        """根分区满盘时的兜底：备份原证书 → tmpfs 覆盖目标目录 → 回填原证书。

        返回 True 表示目录已挂载为可写的 tmpfs；任一步失败都会 umount 还原，
        保证不会把系统原有根证书弄丢。注意 tmpfs 在内存里，重启后挂载消失。
        """
        备份目录 = '/data/local/tmp/_superadb_cacerts_bak'
        self.日志.emit('    >>> 桥接: 备份原有系统证书')
        try:
            输出 = (self._adb.执行shell(
                self._序列号,
                f'rm -rf {备份目录}; mkdir -p {备份目录}; '
                f'cp -a {证书目录}/. {备份目录}/ 2>&1 && echo CP_OK',
                timeout=30) or '').strip()
            self.日志.emit('    ' + (输出 or '无输出'))
            if 'CP_OK' not in 输出:
                self.日志.emit('    ✗ 备份原始证书失败，放弃桥接（未改动系统目录）')
                return False
            原数量 = self._统计目录条目(证书目录)
            备数量 = self._统计目录条目(备份目录)
            self.日志.emit(f'    原目录 {原数量} 项 / 备份 {备数量} 项')
            if 原数量 <= 0 or 备数量 != 原数量:
                self.日志.emit('    ✗ 备份条目数不一致，放弃桥接（避免覆盖后丢证书）')
                return False
        except Exception as e:
            self.日志.emit(f'    ✗ 备份异常: {e}')
            return False

        self.日志.emit('    >>> 桥接: mount -t tmpfs 覆盖证书目录')
        try:
            挂载输出 = (self._adb.执行shell(
                self._序列号,
                f'mount -t tmpfs -o mode=0755,size=32m tmpfs {证书目录} 2>&1 && echo MOUNT_OK',
                timeout=15) or '').strip()
            self.日志.emit('    ' + (挂载输出 or '无输出'))
            if 'MOUNT_OK' not in 挂载输出:
                self.日志.emit('    ✗ tmpfs 挂载失败，放弃桥接')
                return False
        except Exception as e:
            self.日志.emit(f'    ✗ tmpfs 挂载异常: {e}')
            return False

        self.日志.emit('    >>> 桥接: 回填原有系统证书')
        try:
            回填输出 = (self._adb.执行shell(
                self._序列号,
                f'cp -a {备份目录}/. {证书目录}/ 2>&1 && echo CP_OK',
                timeout=30) or '').strip()
            新数量 = self._统计目录条目(证书目录)
            self.日志.emit(f'    回填后 {新数量} 项')
            if 'CP_OK' not in 回填输出 or 新数量 != 备数量:
                self.日志.emit('    ✗ 回填失败，umount 还原系统目录')
                self._adb.执行shell(self._序列号, f'umount {证书目录} 2>&1; true', timeout=10)
                return False
            self._adb.执行shell(
                self._序列号,
                f'chown root:root {证书目录}; chmod 755 {证书目录}; '
                f'find {证书目录} -maxdepth 1 -type f -exec chmod 644 {{}} \\; 2>&1; true',
                timeout=20)
            self.日志.emit('    已修正目录 755 / 文件 644 root:root')
            self.日志.emit('    ⚠ 已切到内存 tmpfs 挂载：本次有效，重启后挂载消失需重装')
            return True
        except Exception as e:
            self.日志.emit(f'    ✗ 回填异常: {e}，尝试还原')
            try:
                self._adb.执行shell(self._序列号, f'umount {证书目录} 2>&1; true', timeout=10)
            except Exception:
                pass
            return False

    def _推送失败诊断(self, 临时路径, 证书目录):
        """push 失败时输出诊断日志（供用户定位是只读、目录缺失还是满盘）。"""
        self.日志.emit('    --- 诊断信息 ---')
        try:
            验证 = self._adb.执行shell(
                self._序列号,
                'touch /system/.super_adb_write_test && rm /system/.super_adb_write_test && echo WRITABLE',
                timeout=5)
            if 'WRITABLE' not in (验证 or ''):
                self.日志.emit('    ✗ 诊断: /system 实际为只读，remount 可能未生效')
            else:
                self.日志.emit('    ✓ 诊断: /system 分区可写（不是权限问题）')
        except Exception as de:
            self.日志.emit(f'    ✗ 诊断: /system 写入验证异常: {de}')
        try:
            目录检查 = self._adb.执行shell(
                self._序列号, f'ls -ld {证书目录} 2>&1', timeout=5)
            self.日志.emit(f'    诊断: 目标目录状态: {(目录检查 or "").strip() or "无输出"}')
        except Exception as de:
            self.日志.emit(f'    诊断: 目录检查异常: {de}')
        try:
            self.日志.emit(f'    诊断: 本地证书大小: {os.path.getsize(临时路径)}B')
        except Exception:
            self.日志.emit('    诊断: 无法获取本地文件大小')
        try:
            空间 = self._adb.执行shell(self._序列号, f'stat -f {证书目录} 2>&1', timeout=5)
            self.日志.emit('    诊断: 目标目录 statfs: ' + ' | '.join(
                l.strip() for l in (空间 or '').splitlines() if l.strip()))
        except Exception:
            pass
        self.日志.emit('    --- 诊断结束 ---')


# ----------------------------------------------------------------------
# 主对话框
# ----------------------------------------------------------------------
class 证书安装对话框(对话框基类):
    """证书安装弹窗：拖拽证书 → 检查权限 → 计算哈希 → 推送 → chmod。"""

    def __init__(self, adb, 获取序列号, parent=None):
        # 业务属性必须在 super().__init__ 之前设置
        self._adb = adb
        self._获取序列号 = 获取序列号
        self._证书路径 = None
        self._系统可写 = False
        self._工作线程 = None

        # 标题栏显示当前设备
        序列号 = 获取序列号() if callable(获取序列号) else None
        标题 = f'证书安装 — 设备: {序列号}' if 序列号 else '证书安装 — 未连接设备'

        super().__init__(parent, 标题=标题, 最小尺寸=(620, 480), 发光=False)

        # 内层亮边卡片（与 TCPDump/PCAP 弹窗同款 4px 主题色边框）
        self.card, _ = _create_popup_card(self, self._主题id)

        根布局 = QVBoxLayout(self.card)
        根布局.setContentsMargins(16, 16, 16, 16)
        根布局.setSpacing(10)

        # 提示标签
        提示 = QLabel('拖拽 PEM / CRT / CER 证书文件到下方区域，或点击选择文件')
        提示.setStyleSheet(f'color: {THEMES[self._主题id]["text_primary"]};')
        根布局.addWidget(提示)

        # 拖拽区
        self.拖拽区 = 拖拽区域(
            self,
            text='拖拽证书文件到此处\n（.pem / .crt / .cer）',
            file_filter='证书文件 (*.pem *.crt *.cer);;所有文件 (*.*)',
            file_mode='single',
            theme_id=self._主题id,
        )
        self.拖拽区.paths_dropped.connect(self._处理拖入文件)
        根布局.addWidget(self.拖拽区)

        # 已选证书显示
        self.证书标签 = QLabel('未选择证书')
        self.证书标签.setStyleSheet(f'color: {THEMES[self._主题id]["accent"]}; font-weight: bold;')
        根布局.addWidget(self.证书标签)

        # 按钮栏（仅保留清空输出；权限检查+安装由拖入证书后自动串联执行）
        按钮栏 = QHBoxLayout()
        按钮栏.addStretch()
        self.清空按钮 = QPushButton('清空输出')
        self.清空按钮.clicked.connect(self._清空输出)
        按钮栏.addWidget(self.清空按钮)
        根布局.addLayout(按钮栏)

        # 输出框
        输出标签 = QLabel('执行日志：')
        输出标签.setStyleSheet(f'color: {THEMES[self._主题id]["text_primary"]};')
        根布局.addWidget(输出标签)

        self.输出框 = QPlainTextEdit()
        self.输出框.setReadOnly(True)
        self.输出框.setStyleSheet(self._输出框样式())
        根布局.addWidget(self.输出框, 1)

        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    # 宿主层拖放转发到内部拖拽区（透明分层外壳下子控件收不到 shell 拖放事件）
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        区 = getattr(self, '拖拽区', None)
        if 区 is not None:
            区.dragEnterEvent(event)
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent):
        区 = getattr(self, '拖拽区', None)
        if 区 is not None:
            区.dragMoveEvent(event)
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        区 = getattr(self, '拖拽区', None)
        if 区 is not None:
            区.dragLeaveEvent(event)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        区 = getattr(self, '拖拽区', None)
        if 区 is not None:
            区.dropEvent(event)
        else:
            super().dropEvent(event)

    def _输出框样式(self):
        t = THEMES[self._主题id]
        return (
            f'QPlainTextEdit {{ background: {t["bg_input"]}; '
            f'color: {t["text_primary"]}; '
            f'border: 1px solid {t["accent"]}; border-radius: 6px; '
            f'font-family: Consolas, "微软雅黑"; font-size: 9pt; }}'
        )

    def _追加日志(self, 文本):
        self.输出框.appendPlainText(文本)
        self.输出框.verticalScrollBar().setValue(
            self.输出框.verticalScrollBar().maximum()
        )

    def _处理拖入文件(self, 路径列表):
        for 路径 in 路径列表:
            if os.path.isfile(路径):
                self._证书路径 = 路径
                文件名 = os.path.basename(路径)
                self.证书标签.setText(f'已选证书: {文件名}')
                self._追加日志(f'已选择证书: {路径}')
                # 预计算哈希
                try:
                    哈希值 = 计算证书哈希(路径)
                    self._追加日志(f'证书 subject hash: {哈希值}（将重命名为 {哈希值}.0）')
                except Exception as e:
                    self._追加日志(f'哈希计算失败: {e}')
                # 自动检查系统读写权限，通过则自动安装
                self._自动检查并安装()
                break

    def _自动检查并安装(self):
        """拖入证书后自动执行：检查系统读写权限 → 通过则自动安装，失败则输出提示。"""
        序列号 = self._获取序列号()
        if not 序列号:
            self._追加日志('✗ 未连接 Android 设备，请先连接设备')
            return
        if self._工作线程 is not None and self._工作线程.isRunning():
            self._追加日志('⚠ 已有任务在执行，请等待完成')
            return
        self._追加日志(f'设备: {序列号}')
        self._追加日志('>>> 正在检测系统读写权限...')
        self._工作线程 = 证书安装线程(self._adb, 序列号, '检查权限', 父=self)
        self._工作线程.日志.connect(self._追加日志)
        self._工作线程.完成.connect(self._权限检查完成)
        self._工作线程.start()

    def _权限检查完成(self, 成功, 消息):
        self._系统可写 = 成功
        if 成功:
            self._追加日志(f'✓ {消息}')
            self._追加日志('>>> 系统可写，开始安装证书...')
            self._安装证书()
        else:
            self._追加日志(f'✗ {消息}')
            self._追加日志('  提示：真机需 userdebug 固件并开启 root；模拟器请用 -writable-system 参数重启。')

    def _安装证书(self):
        if not self._证书路径:
            self._追加日志('✗ 未选择证书')
            return
        序列号 = self._获取序列号()
        if not 序列号:
            self._追加日志('✗ 未连接设备')
            return
        self._工作线程 = 证书安装线程(
            self._adb, 序列号, '安装证书', 证书路径=self._证书路径, 父=self
        )
        self._工作线程.日志.connect(self._追加日志)
        self._工作线程.完成.connect(self._安装完成)
        self._工作线程.start()

    def _安装完成(self, 成功, 消息):
        if 成功:
            self._追加日志(f'✓ {消息}')
        else:
            self._追加日志(f'✗ {消息}')

    def _清空输出(self):
        self.输出框.clear()

    def apply_theme(self, theme_id):
        """主题切换时刷新样式。"""
        super().apply_theme(theme_id)
        if theme_id not in THEMES:
            return
        self.card.setStyleSheet(highlight_card_style(theme_id))
        add_green_glow(self.card, accent=QColor(THEMES[theme_id]['accent']))
        self.拖拽区.apply_theme(theme_id)
        强调色 = THEMES[theme_id]['accent']
        self.证书标签.setStyleSheet(f'color: {强调色}; font-weight: bold;')
        self.输出框.setStyleSheet(self._输出框样式())


# ----------------------------------------------------------------------
# 独立运行测试入口（直接 python 证书安装对话框.py 可预览 UI）
# ----------------------------------------------------------------------
if __name__ == '__main__':
    import sys
    # 把 项目UI 目录加入路径，解决 界面样式/弹窗样式/png_rc 的导入
    _ui_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '项目UI')
    if os.path.isdir(_ui_dir):
        sys.path.insert(0, os.path.abspath(_ui_dir))
    from PySide6.QtWidgets import QApplication

    class _模拟adb:
        """单独运行时用的 mock adb，避免依赖真实设备。"""
        def root_and_remount(self, serial):
            return '① adb root：成功\n② adb remount：成功\n⑤ 验证：可在 /system 写入 ✓'
        def run_direct(self, serial, args, timeout=30):
            return f'模拟执行: adb {" ".join(args)}'
        def run_shell(self, serial, command, timeout=30):
            return f'模拟 shell: {command}'

    app = QApplication(sys.argv)
    dlg = 证书安装对话框(_模拟adb(), lambda: 'emulator-5554（模拟）')
    dlg.show()
    sys.exit(app.exec())
