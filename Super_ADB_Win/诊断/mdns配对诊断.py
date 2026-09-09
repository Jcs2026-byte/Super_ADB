# -*- coding: utf-8 -*-
"""
无线调试扫码配对链路诊断工具（v2）
==================================
定位「手机扫描二维码后一直转圈、PC 收不到 pairing 广播」的问题。

v1 实测结论（192.168.75.15 / adb-ATLS024910000001-BEES4I）：
  - connect 服务可见（192.168.75.15:33729），说明 mDNS 多播通路正常
  - 扫 A(superadb-XXXXXX) / B(adb-xxxxxx) 两种二维码后，_adb-tls-pairing 广播
    **完全没有出现** → 该 ROM 不按二维码里的服务名注册配对服务（或根本不注册），
    纯 mDNS 发现的二维码配对路径在该机型上不可用
  - 配对码方式可用：手机端「使用配对码配对设备」直接显示 IP:端口+6位码，
    PC 主动连，不依赖 mDNS

v2 验证两条绕开 mDNS 的路径：
  【路径1】连接探测：手机若此前已与本机配对过，直接 adb connect <connect端口> 即可
  【路径2】端口扫描配对：手机「转圈」时正在某随机端口等待配对，PC 并发扫描其
           高端口段，对开放端口用已知配对码尝试配对（SPAKE2 校验，猜错立即失败）

用法（务必先关闭 Super_ADB 主程序，避免 5353 端口争抢）：
    python Super_ADB_Win/诊断/mdns配对诊断.py
"""

import os
import random
import socket
import sys
import threading
import time
import traceback

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.dirname(_HERE)
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

PAIRING_TYPE = '_adb-tls-pairing._tcp.local.'
CONNECT_TYPE = '_adb-tls-connect._tcp.local.'

SCAN_START = 30000
SCAN_END = 45000
SCAN_WORKERS = 400
SCAN_TIMEOUT = 0.25

WAIT_PER_QR = 30          # 扫码后等待 pairing 广播的秒数
_FALLBACK_AFTER = 10.0    # 超过该秒数后接受本轮新增的任意 pairing 服务

_log_lock = threading.Lock()


def log(msg):
    ts = time.strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    with _log_lock:
        print(line, flush=True)
        try:
            with open(os.path.join(_HERE, 'mdns配对诊断.log'), 'a',
                      encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass


def 输入(提示):
    try:
        return input(提示).strip()
    except Exception:
        return ''


# ── 1. 本机网络接口 ────────────────────────────────────────
def 打印本机网卡():
    log('=' * 60)
    log('【步骤1】本机 IPv4 接口')
    try:
        seen = []
        for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = a[4][0]
            if ip not in seen:
                seen.append(ip)
        for ip in seen:
            if ip.startswith('169.254.'):
                标记 = '  ← 自动配置地址（虚拟网卡/热点，易干扰 mDNS）'
            elif ip.startswith('127.'):
                标记 = '  ← 回环'
            else:
                标记 = '  ← 局域网（手机应与此同网段）'
            log(f'  {ip}{标记}')
    except Exception as e:
        log(f'  枚举失败: {e}')
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        log(f'  默认出口 IP（同网段判定基准）: {s.getsockname()[0]}')
    except Exception as e:
        log(f'  默认出口 IP 获取失败: {e}')
    finally:
        try:
            s.close()
        except Exception:
            pass
    log('=' * 60)


# ── 2. mDNS 被动监听 ───────────────────────────────────────
class _Listener:
    def __init__(self, tag):
        self.tag = tag
        self.seen = set()
        self.found = []          # [(name, ips, port)]
        self.lock = threading.Lock()

    def add_service(self, zc, type_, name):
        self._show(zc, type_, name)

    def update_service(self, zc, type_, name):
        self._show(zc, type_, name)

    def remove_service(self, zc, type_, name):
        log(f'[mdns:{self.tag}] 服务移除 {name}')

    def _show(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name)
        except Exception as e:
            log(f'[mdns:{self.tag}] get_service_info 异常 {name}: {e}')
            return
        if not info:
            return
        ips = []
        try:
            for a in info.addresses:
                if len(a) == 4:
                    ips.append(socket.inet_ntoa(bytes(a)))
        except Exception:
            pass
        with self.lock:
            self.found.append((name, ips, info.port))
            if (name, info.port) in self.seen:
                return
            self.seen.add((name, info.port))
        log(f'[mdns:{self.tag}] 发现 {name}')
        log(f'    └ 类型={type_} 端口={info.port} IP列表={ips}')


# ── 3. mDNS 主动查询 ───────────────────────────────────────
def 主动查询循环(stop_event):
    try:
        from 工具.android调试模块.自研adb.mdns主动查询 import query_mdns
    except Exception as e:
        log(f'[主动查询] 导入失败，跳过：{e}')
        return
    while not stop_event.is_set():
        for ty, tag in ((PAIRING_TYPE, 'pairing'), (CONNECT_TYPE, 'connect')):
            try:
                r = query_mdns(ty, timeout=1.2)
                if r:
                    for name, ip, port in r:
                        log(f'[主动查询:{tag}] {name} @ {ip}:{port}')
            except Exception as e:
                log(f'[主动查询:{tag}] 异常 {e}')
        stop_event.wait(2.0)


# ── 工具 ───────────────────────────────────────────────────
def 选ip(ips):
    lan = None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        lan = s.getsockname()[0]
    except Exception:
        pass
    finally:
        try:
            s.close()
        except Exception:
            pass
    if lan and ips:
        sub = '.'.join(lan.split('.')[:3])
        for c in ips:
            if c.startswith(sub + '.'):
                return c
    return ips[0] if ips else None


def 执行配对(ip, port, code):
    """执行自研 adb 配对，返回 (ok, msg)。"""
    try:
        import importlib
        mod = importlib.import_module('工具.自研adb.配对客户端')
        ok, msg = mod.配对设备(ip, port, code, timeout=12,
                               log_callback=lambda m: log(f'   [配对] {m}'))
        log(f'   配对结果：ok={ok} msg={msg}')
        return ok, msg
    except Exception as e:
        log(f'❌ 配对调用异常：{e}')
        log(traceback.format_exc())
        return False, str(e)


def 生成二维码打开(name, code, tag):
    try:
        import segno
    except Exception as e:
        log(f'❌ 缺少 segno，无法生成二维码：{e}')
        return None
    payload = f'WIFI:T:ADB;S:{name};P:{code};;'
    out = os.path.join(_HERE, f'诊断二维码_{tag}.png')
    try:
        segno.make(payload, error='m').save(out, kind='png', scale=12, border=2)
    except Exception as e:
        log(f'❌ 二维码生成失败：{e}')
        return None
    log(f'  二维码已生成：{out}')
    log(f'  原始内容：{payload}')
    try:
        os.startfile(out)
    except Exception as e:
        log(f'  （自动打开图片失败，请手动打开：{e}）')
    return out


# ── 路径1：连接探测（判断是否已配对）───────────────────────
def 探测已配对连接(listener, 等待秒=8):
    log('-' * 60)
    log(f'【步骤2.5】收集 connect 服务（{等待秒} 秒）并逐个探测是否已配对')
    log('  👉 请确保手机「无线调试」页面已打开')
    time.sleep(等待秒)
    服务 = list(listener.found)
    if not 服务:
        log('  ⚠️ 未发现任何 connect 服务（手机未开无线调试 / 不在同网段）')
        return []
    候选 = []
    for name, ips, port in 服务:
        ip = 选ip(ips)
        if not ip:
            continue
        候选.append((ip, port, name))
        log(f'  → 探测 {ip}:{port}  {name}')
        try:
            from 工具.android调试模块.ADB工具 import AdbHelper
            h = AdbHelper()
            h.log_callback = lambda m: log(f'     [adb] {m}')
            r = h.连接设备(f'{ip}:{port}', timeout=8)
            log(f'     连接结果: {r}')
        except Exception as e:
            log(f'     连接异常: {e}')
    log('-' * 60)
    return 候选


# ── 路径2：端口扫描配对 ────────────────────────────────────
def 扫描开放端口(ip, start=SCAN_START, end=SCAN_END):
    import concurrent.futures
    log(f'  扫描 {ip} 端口 {start}-{end}（并发 {SCAN_WORKERS}）…')
    开放 = []

    def probe(p):
        s = socket.socket()
        s.settimeout(SCAN_TIMEOUT)
        try:
            s.connect((ip, p))
            return p
        except Exception:
            return None
        finally:
            try:
                s.close()
            except Exception:
                pass

    t0 = time.time()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_WORKERS) as ex:
            for r in ex.map(probe, range(start, end + 1)):
                if r:
                    开放.append(r)
    except Exception as e:
        log(f'  扫描异常: {e}')
    log(f'  扫描完成，用时 {int(time.time() - t0)} 秒，开放端口：{sorted(开放)}')
    return sorted(开放)


def 端口扫描配对(ip, code, 排除端口=()):
    log('=' * 60)
    log(f'【路径2】端口扫描配对：目标 {ip}，配对码 {code}')
    log('  ⚠️ 请保持手机处于「扫码后转圈 / 等待配对」状态')
    开放 = 扫描开放端口(ip)
    候选 = [p for p in 开放 if p not in 排除端口]
    if not 候选:
        log('  ❌ 未发现可用于配对的开放端口')
        return False
    log(f'  待尝试（已排除已知调试端口 {sorted(排除端口)}）：{候选}')
    for p in 候选:
        log(f'  → 尝试配对 {ip}:{p} …')
        ok, _msg = 执行配对(ip, p, code)
        if ok:
            log(f'  ✅✅ 端口扫描配对成功：{ip}:{p}')
            return True
    log('  ❌ 所有开放端口均配对失败（手机可能已退出等待状态）')
    return False


# ── 二维码等待（精确匹配 + 宽松兜底）────────────────────────
def 等待并配对(expected_name, code, listeners, timeout, 基线=0):
    key = expected_name.lower()
    start = time.time()
    deadline = start + timeout
    last_report = 0
    while time.time() < deadline:
        hit = None
        兜底 = False
        新增 = list(listeners[0].found)[基线:]
        for name, ips, port in 新增:
            if key in name.lower():
                hit = (name, ips, port)
                break
        if hit is None and 新增 and (time.time() - start) > _FALLBACK_AFTER:
            hit = 新增[0]
            兜底 = True
        if hit is None:
            now = time.time()
            if now - last_report > 5:
                last_report = now
                log(f'  … 等待中，剩余 {int(deadline - now)} 秒'
                    f'（本轮新增 pairing 服务 {len(新增)} 个）')
            time.sleep(0.3)
            continue
        name, ips, port = hit
        ip = 选ip(ips)
        log('=' * 60)
        if 兜底:
            log(f'⚠️ 未匹配服务名，启用【宽松兜底】：{name}')
        log(f'✅ 发现配对服务：{name} → {ip}:{port}')
        return 执行配对(ip, port, code)
    log(f'❌ {timeout} 秒内未发现任何 pairing 广播（服务名「{expected_name}」未命中）')
    return False, '未发现配对广播'


def main():
    log('')
    log('#' * 60)
    log('# 无线调试扫码配对链路诊断 v2  启动')
    log('#' * 60)
    打印本机网卡()

    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except Exception as e:
        log(f'❌ 缺少 zeroconf：{e}')
        return

    try:
        zc = Zeroconf()
    except Exception as e:
        log(f'❌ Zeroconf() 创建失败（5353 被占用？请先关闭 Super_ADB）：{e}')
        return

    listeners = [_Listener('pairing'), _Listener('connect')]
    browsers = [
        ServiceBrowser(zc, PAIRING_TYPE, listeners[0]),
        ServiceBrowser(zc, CONNECT_TYPE, listeners[1]),
    ]
    log('【步骤2】mDNS 监听已启动（pairing + connect）')

    stop = threading.Event()
    threading.Thread(target=主动查询循环, args=(stop,), daemon=True).start()
    log('【步骤3】mDNS 主动查询已启动（每 2 秒一轮）')

    try:
        候选 = 探测已配对连接(listeners[1], 等待秒=8)

        目标ip = ''
        if 候选:
            log('  发现以下设备（connect 服务）：')
            for i, (ip, port, name) in enumerate(候选, 1):
                log(f'    [{i}] {ip}:{port}   {name}')
            sel = 输入('  👉 输入要测试的设备序号（回车用 [1]）：')
            try:
                目标ip = 候选[(int(sel) if sel else 1) - 1][0]
            except Exception:
                目标ip = 候选[0][0]
        else:
            目标ip = 输入('  👉 未自动发现设备，请手动输入手机 IP：')
        log(f'  目标设备 IP：{目标ip}')

        alphabet = 'abcdefghjklmnpqrstuvwxyz23456789'
        name = 'adb-superadb-' + ''.join(random.choices(alphabet, k=6))
        code = f'{random.randint(0, 999999):06d}'
        log('')
        log('=' * 60)
        log(f'【步骤4】二维码测试  服务名={name}  配对码={code}')
        log('  👉 请用手机「无线调试 → 使用二维码配对设备」扫描弹出的二维码')
        生成二维码打开(name, code, 'C')
        基线 = len(listeners[0].found)
        ok, _msg = 等待并配对(name, code, listeners, WAIT_PER_QR, 基线=基线)

        if not ok and 目标ip:
            log('')
            log('  ⚠️ 手机未广播配对服务（该 ROM 的二维码配对依赖 mDNS，本机型不可用）')
            sel = 输入('  👉 手机是否仍在「转圈等待」？输入 y 立即端口扫描配对（回车跳过）：')
            if sel.lower() in ('y', 'yes', '是'):
                已知 = {port for ip, port, _n in 候选 if ip == 目标ip}
                端口扫描配对(目标ip, code, 排除端口=已知)
    finally:
        stop.set()
        time.sleep(0.5)
        for b in browsers:
            try:
                b.cancel()
            except Exception:
                pass
        try:
            zc.close()
        except Exception:
            pass

    log('')
    log('=' * 60)
    log('诊断结束。请把本窗口输出或 诊断/mdns配对诊断.log 全文发给开发者。')
    log('=' * 60)
    输入('\n按回车键退出…')


if __name__ == '__main__':
    main()
