"""设备能力配置：单独存设备的通道类型（单通道/多通道），按 型号+系统版本 作为唯一键。"""
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


def 设置单通道(model, android_version, is_single_channel):
    """设置某个 型号+版本 的设备是单通道还是多通道。"""
    if not model:
        return
    data = _load_capacity()
    key = f"{model}_{android_version}"
    if key not in data:
        data[key] = {
            'model': model,
            'android_version': android_version
        }
    data[key]['is_single_channel'] = is_single_channel
    _save_capacity(data)


def 是否单通道(model, android_version):
    """查询某个 型号+版本 的设备是不是单通道。
    返回值：
        True：已知是单通道
        False：已知是多通道
        None：未知，需要检测
    """
    if not model:
        return None
    data = _load_capacity()
    key = f"{model}_{android_version}"
    if key in data:
        return data[key].get('is_single_channel', None)
    return None


def 设置tcpdump支持(model, android_version, 支持):
    """设置某个 型号+版本 的设备是否支持 tcpdump 抓包。"""
    if not model:
        return
    data = _load_capacity()
    key = f"{model}_{android_version}"
    if key not in data:
        data[key] = {
            'model': model,
            'android_version': android_version
        }
    data[key]['支持tcpdump'] = 支持
    _save_capacity(data)


def 是否支持tcpdump(model, android_version):
    """查询某个 型号+版本 的设备是否支持 tcpdump 抓包。
    返回值：
        True：已知支持
        False：已知不支持
        None：未知，需要检查
    """
    if not model:
        return None
    data = _load_capacity()
    key = f"{model}_{android_version}"
    if key in data:
        return data[key].get('支持tcpdump', None)
    return None


def 设置monkey支持(model, android_version, 支持):
    """设置某个 型号+版本 的设备是否支持 monkey。"""
    if not model:
        return
    data = _load_capacity()
    key = f"{model}_{android_version}"
    if key not in data:
        data[key] = {
            'model': model,
            'android_version': android_version
        }
    data[key]['支持monkey'] = 支持
    _save_capacity(data)


def 是否支持monkey(model, android_version):
    """查询某个 型号+版本 的设备是否支持 monkey。
    返回值：
        True：已知支持
        False：已知不支持
        None：未知，需要检查
    """
    if not model:
        return None
    data = _load_capacity()
    key = f"{model}_{android_version}"
    if key in data:
        return data[key].get('支持monkey', None)
    return None


