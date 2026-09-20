"""设备能力配置：按 型号 分组，型号下按 系统版本 为子 key 存各项能力。

新格式示例::

    {
      "CM211": {
        "model": "CM211",
        "versions": {
          "9":  { "is_single_channel": true,  "支持tcpdump": true },
          "11": { "is_single_channel": false, "支持monkey": true }
        }
      }
    }

对外接口签名保持 ``设置X(model, version, value)`` / ``是否X(model, version)``，
调用方无需改动。读取时兼容旧格式（顶层 key 形如 ``model_version``）。
"""
from 工具.android调试工具.ADB工具 import 加载json配置, 保存json配置

# 配置文件名
_CFG_NAME = '设备能力.json'


def _load_capacity():
    """加载设备能力配置。"""
    try:
        data = 加载json配置(_CFG_NAME)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_capacity(data):
    """保存设备能力配置。"""
    保存json配置(_CFG_NAME, data)


def _get_version_entry(data, model, android_version):
    """从 data 中取 (型号节点, 版本节点)。不存在则按需创建型号节点。

    兼容旧格式：旧格式顶层 key 为 ``model_version``，直接平铺在顶层。
    本函数优先查新格式；若新格式没有，再从旧格式里找对应条目并返回
    一个「虚拟版本节点」引用（仍挂在 data 上，后续写入会落到新格式）。
    """
    if not model:
        return None, None
    model_node = data.get(model)
    # 新格式：型号节点下有 versions 子字典
    if isinstance(model_node, dict) and isinstance(model_node.get('versions'), dict):
        versions = model_node['versions']
        ver_node = versions.get(android_version)
        if not isinstance(ver_node, dict):
            ver_node = {}
            versions[android_version] = ver_node
        return model_node, ver_node
    # 新格式但型号节点异常，重建
    if not isinstance(model_node, dict):
        model_node = {'model': model, 'versions': {}}
        data[model] = model_node
    versions = model_node.setdefault('versions', {})
    if not isinstance(versions, dict):
        versions = {}
        model_node['versions'] = versions
    ver_node = versions.get(android_version)
    if not isinstance(ver_node, dict):
        ver_node = {}
        versions[android_version] = ver_node
    return model_node, ver_node


def _read_capability(data, model, android_version, field):
    """读某个能力字段，兼容新/旧格式。返回 None 表示未知。"""
    if not model:
        return None
    # 新格式
    model_node = data.get(model)
    if isinstance(model_node, dict):
        versions = model_node.get('versions')
        if isinstance(versions, dict):
            ver_node = versions.get(android_version)
            if isinstance(ver_node, dict) and field in ver_node:
                return ver_node.get(field)
    # 兼容旧格式：顶层 key 为 model_version
    legacy_key = f"{model}_{android_version}"
    legacy = data.get(legacy_key)
    if isinstance(legacy, dict) and field in legacy:
        return legacy.get(field)
    return None


# ----------------------------------------------------------------------
# 单通道
# ----------------------------------------------------------------------
def 设置单通道(model, android_version, is_single_channel):
    """设置某个 型号+版本 的设备是单通道还是多通道。"""
    if not model:
        return
    data = _load_capacity()
    _, ver_node = _get_version_entry(data, model, android_version)
    if ver_node is not None:
        ver_node['is_single_channel'] = is_single_channel
        _save_capacity(data)


def 是否单通道(model, android_version):
    """查询某个 型号+版本 的设备是不是单通道。
    返回值：
        True：已知是单通道
        False：已知是多通道
        None：未知，需要检测
    """
    return _read_capability(data=_load_capacity(), model=model,
                            android_version=android_version,
                            field='is_single_channel')


# ----------------------------------------------------------------------
# tcpdump
# ----------------------------------------------------------------------
def 设置tcpdump支持(model, android_version, 支持):
    """设置某个 型号+版本 的设备是否支持 tcpdump 抓包。"""
    if not model:
        return
    data = _load_capacity()
    _, ver_node = _get_version_entry(data, model, android_version)
    if ver_node is not None:
        ver_node['支持tcpdump'] = 支持
        _save_capacity(data)


def 是否支持tcpdump(model, android_version):
    """查询某个 型号+版本 的设备是否支持 tcpdump 抓包。
    返回值：
        True：已知支持
        False：已知不支持
        None：未知，需要检查
    """
    return _read_capability(data=_load_capacity(), model=model,
                            android_version=android_version,
                            field='支持tcpdump')


# ----------------------------------------------------------------------
# monkey
# ----------------------------------------------------------------------
def 设置monkey支持(model, android_version, 支持):
    """设置某个 型号+版本 的设备是否支持 monkey。"""
    if not model:
        return
    data = _load_capacity()
    _, ver_node = _get_version_entry(data, model, android_version)
    if ver_node is not None:
        ver_node['支持monkey'] = 支持
        _save_capacity(data)


def 是否支持monkey(model, android_version):
    """查询某个 型号+版本 的设备是否支持 monkey。
    返回值：
        True：已知支持
        False：已知不支持
        None：未知，需要检查
    """
    return _read_capability(data=_load_capacity(), model=model,
                            android_version=android_version,
                            field='支持monkey')
