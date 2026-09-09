# -*- coding: utf-8 -*-
"""兼容转发模块：Gitee 版重组后 工具.X 旧模块名 -> 工具.android调试模块.图表JS 真身。
保持历史 `from 工具.X import ...` 引用可用（Win 已直接用新名，Linux/MAC 保留本转发）。"""
from 工具.android调试模块.图表JS import *  # noqa: F401,F403
