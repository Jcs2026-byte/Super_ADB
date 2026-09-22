# Super_ADB v2026.09.22.01 更新说明

## 修复（Bug Fixes）

### 1. 自研 ADB 模式频繁掉线
- **问题**：自研 ADB 模式下设备经常自己掉线，用官方 ADB 不会。单客户设备（IPTV 盒子等）尤其明显。
- **根因**：四个问题叠加：
  1. **Windows Keepalive 没生效**：代码用 `sock.ioctl(0x98000004)` 设置 keepalive 参数，但 Python socket 对象没有 `ioctl()` 方法，必抛 `AttributeError` 被静默吞掉，导致 `SO_KEEPALIVE=1` 开了但参数用系统默认值（2 小时），WiFi 环境等于没保活。
  2. **连接池探活太弱**：`_连接可用()` 只看 `state == STATE_DEVICE and sock is not None`，对端静默关闭（WiFi 省电/路由器重启）时本地完全感知不到，死连接被当活连接分发。
  3. **主连接没有后台心跳**：官方 adb server 有后台监控线程定期探活，自研模式之前完全没有，空闲时 TCP 半开只能靠下一次操作才发现。
  4. **主连接长期不重建**：主连接从池剥离后长期挂着，空闲过久变成半开连接，占着单客户设备的唯一槽位。
- **修复**：
  - Windows 下用 `ctypes` 调 `WSAIoctl(SIO_KEEPALIVE_VALS)` 正确设置 keepalive：10 秒无活动开始探测，每 3 秒一次
  - 连接池 `_连接可用()` 升级：用 `select + MSG_PEEK` 做零开销真实探活，对端 FIN/RST 立即可检测
  - 新增主连接后台心跳线程：每 15 秒发一次 `echo __hb__` 探活，失败自动重建
  - 新增空闲超时主动重建：主连接连续空闲超过 5 分钟，主动关闭重建防止半开

---

## 优化（Improvements）

### 1. 启动入口精简
- 三个平台的 `启动入口/主入口_启动.py` 已删除，统一使用 `项目启动入口/` 目录下的入口文件
- 减少重复代码，降低维护成本

---

## 涉及文件

| 文件 | 修改内容 |
|------|---------|
| `工具/android调试工具/自研adb/adb协议.py` | Windows Keepalive 修复（WSAIoctl）、连接池真实探活（select+MSG_PEEK） |
| `工具/android调试工具/自研adb/自研adb客户端.py` | 主连接后台心跳线程、空闲超时主动重建 |
| `Super_ADB_Win/项目启动入口/` | 启动入口精简 |
| `Super_ADB_MAC/项目启动入口/` | 启动入口精简 |
| `Super_ADB_Linux/项目启动入口/` | 启动入口精简 |
