# -*- coding: UTF-8 -*-
"""
Chart.js 本地化加载。

导出 HTML 性能报告时，把 chart.umd.min.js 内联进 HTML，避免依赖公网 CDN
（cdn.jsdelivr.net）。Super_ADB 大量场景是给电视盒子 / 离线环境抓数据，
离线打开报告时 CDN 加载失败会导致图表全空，故改为随包分发 + 内联。
"""
import os
import sys

_CHART_JS_NAME = 'chart.umd.min.js'


def load_chart_js():
    """返回 chart.umd.min.js 文本；找不到时返回空串（报告仍可生成，图表降级）。

    路径解析：
      - 冻结运行（PyInstaller）：sys._MEIPASS/资源/chart.umd.min.js
        （spec datas: (项目根/资源, '资源') → 包内保持中文名）
      - 源码运行：本文件在 Super_ADB_Win/工具/android调试工具/，
        资源在 Super_ADB_Win/资源/
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates = [
            os.path.join(sys._MEIPASS, '资源', _CHART_JS_NAME),
            os.path.join(sys._MEIPASS, 'resources', _CHART_JS_NAME),
        ]
    else:
        # __file__ = Super_ADB_Win/工具/android调试工具/图表JS.py
        # 向上三级: android调试工具 -> 工具 -> Super_ADB_Win
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates = [
            os.path.join(project_root, '资源', _CHART_JS_NAME),
        ]
    for p in candidates:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return f.read()
        except OSError:
            continue
    return ''
