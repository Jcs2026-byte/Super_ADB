# -*- coding: UTF-8 -*-
"""冻结环境运行时钩子：拦截 numpy 导入（Super_ADB 专用）。

背景
----
打包 spec 已通过 excludes 排除 numpy（省 ~26MB，本工程源码从不 import
numpy，PIL 的 fromarray 惰性分支也从未触发）。但 Super_ADB.exe 若与旧
构建共享同一个 _internal 目录（如 D:\\pyexe\\JcsToolBox 聚合目录），
该目录里残留的 numpy 二进制子目录（fft/linalg/random/_core，无
__init__.py）会让 `import numpy` 以「命名空间包」形式成功——模块存在
但没有任何属性，openpyxl.compat.numbers 访问 numpy.short 时即抛
AttributeError: module 'numpy' has no attribute 'short'。

处理
----
本钩子在解释器启动阶段（PyInstaller runtime hook，早于任何业务导入）
注册一个 MetaPathFinder：凡请求 numpy 或 numpy.* 一律抛 ImportError，
让 openpyxl 等第三方库的 try/except ImportError 可选分支正常回退
（NUMPY=False），业务链路不受影响；也不依赖共享 _internal 里 numpy
二进制的去留（JcsToolBox 等其他工具仍可正常使用自己的 numpy）。
"""
import importlib.abc
import sys

_拒绝numpy = None


class _拒绝numpy(importlib.abc.MetaPathFinder):
    """拒绝 numpy 及其子模块的导入，抛 ImportError。"""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "numpy" or fullname.startswith("numpy."):
            raise ImportError("numpy 已从 Super_ADB 打包产物中排除")
        return None


def _安装():
    """幂等安装：仅当不存在同类拦截器时插入 sys.meta_path 最前。"""
    global _拒绝numpy
    if any(isinstance(f, _拒绝numpy) for f in sys.meta_path):
        return
    _拒绝numpy = _拒绝numpy()
    sys.meta_path.insert(0, _拒绝numpy)


_安装()
del _安装
