# -*- coding: utf-8 -*-
"""
Apifox 接口文档提取器（优化版）
================================
原脚本依赖本地 Markdown 文件手动维护接口链接，且逐条串行抓取、结果为原始文本，
已重构为：

1. 直接解析 Apifox 共享链接（s.apifox.cn/xxx）自动获取文档 ID；
2. 通过 Apifox 公开 API 拉取接口树，自动遍历所有层级目录下的全部 HTTP 接口；
3. 多线程并发抓取每个接口的完整详情（请求头 / 请求参数 / 请求体 Schema / 请求体示例 / 响应）；
4. 结构化写入 Excel：
   - 工作表「接口总览」：分类路径 / 名称 / 方法 / URL / 请求体示例 / 链接，一目了然；
   - 工作表「接口详情」：完整字段 + JSON 原文，供开发联调查阅；
5. 带重试、进度日志与友好报错，URL 可通过命令行参数传入。

用法：
    python Apifox接口提取.py                          # 使用脚本内置默认链接
    python Apifox接口提取.py <apifox共享链接>          # 指定其他链接
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# HTTP 客户端：fetch.py（Kenneth Reitz 的单文件零依赖库，随本脚本同目录分发）。
# 应用内（GUI 弹窗）运行时 Super_ADB_Win 根目录在 sys.path，走包导入；
# 命令行直接运行时脚本所在目录在 sys.path，走裸导入。
try:
    from 工具.便捷工具 import fetch  # noqa: F401  应用内（GUI）运行路径
except ImportError:
    import fetch  # noqa: F401                    命令行直接运行路径

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
API_BASE = "https://api.apifox.cn"            # Apifox 公开 API 域名
DEFAULT_DOC_URL = "https://s.apifox.cn/c7c78ea0-4189-4301-892e-caa2c6416d84"
REQUEST_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://s.apifox.cn/",
}
TIMEOUT = 30            # 单次请求超时(秒)
MAX_WORKERS = 8         # 并发抓取线程数
MAX_RETRY = 3           # 请求失败重试次数

# Excel 样式
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF")
WRAP_ALIGN = Alignment(horizontal="left", vertical="top", wrap_text=True)
CENTER_ALIGN = Alignment(horizontal="center", vertical="center")


def 获取桌面Super_ADB目录():
    """返回 桌面/Super_ADB 文件夹路径（不存在则创建）。

    Windows 优先走 SHGetKnownFolderPath 获取真实桌面路径
    （正确处理 OneDrive 等重定向），失败时回退 ~/Desktop。
    """
    desktop = None
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            FOLDERID_Desktop = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
            SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
            SHGetKnownFolderPath.argtypes = [
                ctypes.c_wchar_p, wintypes.DWORD, wintypes.HANDLE,
                ctypes.POINTER(ctypes.c_wchar_p),
            ]
            SHGetKnownFolderPath.restype = wintypes.HRESULT
            p_path = ctypes.c_wchar_p()
            if SHGetKnownFolderPath(
                    FOLDERID_Desktop, 0, None, ctypes.byref(p_path)) == 0 and p_path.value:
                desktop = p_path.value
        except Exception:
            desktop = None
    if not desktop:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    out_dir = os.path.join(desktop, "Super_ADB")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


# ---------------------------------------------------------------------------
# 基础请求封装
# ---------------------------------------------------------------------------
def fetch_json(url, params=None):
    """带重试的 GET 请求，返回响应中的 data 字段（基于 fetch.py）。

    fetch.py 默认对 4xx/5xx 抛 HTTPError，这里传 check_status=False
    自行判断状态码，以保留原有的重试语义。
    """
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = fetch.get(
                url,
                params=params,
                headers=REQUEST_HEADERS,
                timeout=TIMEOUT,
                check_status=False,   # 自行判断状态码，非 200 走重试
                trust_env=True,       # 与 requests 默认一致：启用系统/环境代理
            )
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            data = resp.json()
            if data.get("success") is False:
                raise RuntimeError(data.get("message", "接口返回失败"))
            return data.get("data")
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRY:
                time.sleep(attempt)  # 线性退避
    raise RuntimeError(f"请求失败: {url} -> {last_err}")


def extract_doc_id(url):
    """从共享链接中解析文档 ID（UUID）"""
    match = re.search(
        r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})',
        url,
    )
    if not match:
        raise ValueError(f"无法从链接解析出文档 ID: {url}")
    return match.group(1)


# ---------------------------------------------------------------------------
# 接口树解析
# ---------------------------------------------------------------------------
def collect_apis(nodes, doc_id, path=None):
    """递归遍历接口树，返回 [{category, id, name, method, path, link}, ...]"""
    path = path or []
    apis = []
    for node in nodes or []:
        name = node.get("name", "")
        node_path = path + [name]
        if node.get("type") == "apiDetail":
            api = node.get("api", {}) or {}
            api_id = api.get("id")
            apis.append({
                "id": api_id,
                "name": api.get("name") or name,
                "method": api.get("method", ""),
                "path": api.get("path", ""),
                "category": " / ".join(path),
                "folder": name,
                "link": f"https://s.apifox.cn/{doc_id}/{api_id}e0" if api_id else "",
            })
        apis.extend(collect_apis(node.get("children", []), doc_id, node_path))
    return apis


# ---------------------------------------------------------------------------
# 接口详情提取
# ---------------------------------------------------------------------------
def pretty_json(obj):
    """把对象格式化为可读 JSON 文本；非 dict/list 原样返回字符串"""
    if obj is None:
        return ""
    if isinstance(obj, (dict, list)):
        try:
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(obj)
    return str(obj)


def parse_example(value):
    """解析请求体示例：value 可能是 JSON 字符串或对象"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def extract_request_body(detail):
    """提取请求体：返回 (body_schema, body_example)"""
    body = detail.get("requestBody") or {}
    schema = pretty_json(body.get("jsonSchema"))
    example = ""
    examples = body.get("examples") or []
    if examples:
        first = examples[0]
        if isinstance(first, dict) and "value" in first:
            example = pretty_json(parse_example(first.get("value")))
        else:
            example = pretty_json(first)
    # 兜底：无独立示例时尝试从 schema 拼一个空示例
    if not example and body.get("jsonSchema"):
        example = pretty_json(body.get("jsonSchema"))
    return schema, example


def extract_parameters(detail):
    """提取 query/path/header/cookie 参数"""
    params = detail.get("parameters") or {}
    out = {}
    for key in ("query", "path", "header", "cookie"):
        items = params.get(key) or []
        rows = []
        for it in items:
            if not isinstance(it, dict):
                continue
            rows.append({
                "名称": it.get("name", ""),
                "类型": it.get("type", ""),
                "必填": "是" if it.get("required") else "否",
                "示例": it.get("sampleValue", ""),
                "说明": it.get("description", ""),
            })
        if rows:
            out[key] = rows
    return out


def extract_responses(detail):
    """提取响应：拼接 code + 名称 + jsonSchema"""
    parts = []
    for resp in detail.get("responses") or []:
        if not isinstance(resp, dict):
            continue
        name = resp.get("name", "")
        code = resp.get("code", "")
        ctype = resp.get("contentType", "")
        schema = resp.get("jsonSchema")
        head = f"[{code}] {name} ({ctype})" if name else f"[{code}] {ctype}"
        if schema:
            parts.append(head + "\n" + pretty_json(schema))
        else:
            parts.append(head)
    return "\n\n".join(parts)


def fetch_api_detail(api, doc_id):
    """抓取单个接口详情并整理为一行数据"""
    url = f"{API_BASE}/api/v1/shared-docs/{doc_id}/http-apis/{api['id']}"
    detail = fetch_json(url) or {}

    body_schema, body_example = extract_request_body(detail)
    params = extract_parameters(detail)
    responses = extract_responses(detail)

    headers_str = pretty_json(params.get("header")) if params.get("header") else ""
    query_str = pretty_json(params.get("query")) if params.get("query") else ""

    return {
        "category": api["category"],
        "name": api["name"],
        "method": (detail.get("method") or api["method"] or "").upper(),
        "url": detail.get("path") or api["path"],
        "headers": headers_str,
        "query": query_str,
        "body_schema": body_schema,
        "body_example": body_example,
        "responses": responses,
        "link": api["link"],
        "status": detail.get("status", ""),
        "description": detail.get("description", ""),
        "updated_at": (detail.get("updatedAt") or "").replace("T", " ").replace("Z", ""),
    }


# ---------------------------------------------------------------------------
# Excel 写入
# ---------------------------------------------------------------------------
def write_excel(rows, doc_id, output_dir=None):
    """把接口数据写入 Excel，返回输出文件路径。

    output_dir 为空时保存到 桌面/Super_ADB 文件夹（自动创建）。
    """
    wb = Workbook()

    # ---- 工作表 1：接口总览 ----
    ws_overview = wb.active
    ws_overview.title = "接口总览"
    overview_headers = ["序号", "分类路径", "接口名称", "请求方法", "接口URL", "请求体示例", "接口链接"]
    ws_overview.append(overview_headers)
    _style_header(ws_overview)

    for idx, row in enumerate(rows, 1):
        ws_overview.append([
            idx,
            row["category"],
            row["name"],
            row["method"],
            row["url"],
            row["body_example"],
            row["link"],
        ])
    _style_body(ws_overview, ncols=len(overview_headers))
    widths = [6, 30, 34, 10, 46, 70, 50]
    for i, w in enumerate(widths, 1):
        ws_overview.column_dimensions[chr(64 + i)].width = w
    ws_overview.freeze_panes = "A2"

    # ---- 工作表 2：接口详情 ----
    ws_detail = wb.create_sheet("接口详情")
    detail_headers = [
        "序号", "分类路径", "接口名称", "请求方法", "接口URL",
        "请求头(Header)", "请求参数(Query)", "请求体Schema", "请求体示例",
        "响应(Response)", "接口链接", "状态", "接口说明", "更新时间",
    ]
    ws_detail.append(detail_headers)
    _style_header(ws_detail)

    for idx, row in enumerate(rows, 1):
        ws_detail.append([
            idx,
            row["category"],
            row["name"],
            row["method"],
            row["url"],
            row["headers"],
            row["query"],
            row["body_schema"],
            row["body_example"],
            row["responses"],
            row["link"],
            row["status"],
            row["description"],
            row["updated_at"],
        ])
    _style_body(ws_detail, ncols=len(detail_headers))
    detail_widths = [6, 26, 30, 10, 40, 40, 40, 60, 70, 60, 46, 10, 30, 20]
    for i, w in enumerate(detail_widths, 1):
        ws_detail.column_dimensions[get_column_letter(i)].width = w
    ws_detail.freeze_panes = "A2"

    # ---- 保存 ----
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_dir = output_dir or 获取桌面Super_ADB目录()
    output_path = os.path.join(save_dir, f"Apifox接口提取_{doc_id[:8]}_{timestamp}.xlsx")
    wb.save(output_path)
    return output_path


def _style_header(ws):
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER_ALIGN


def _style_body(ws, ncols):
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = WRAP_ALIGN


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run_extract(doc_url=None, log_func=None, output_dir=None):
    """完整提取流程：解析链接 → 拉接口树 → 并发抓详情 → 写 Excel。

    doc_url    : Apifox 共享文档链接，为空时使用 DEFAULT_DOC_URL
    log_func   : 逐行日志回调 callable(str)，为空时打印到 stdout
    output_dir : Excel 输出目录，为空时保存到 桌面/Super_ADB
    返回        : 输出文件路径；任一步骤失败抛异常
    """
    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    doc_url = (doc_url or DEFAULT_DOC_URL).strip()
    doc_id = extract_doc_id(doc_url)
    _log(f"[步骤1] 解析文档 ID: {doc_id}")

    # 1. 拉取接口树
    _log("[步骤2] 正在拉取接口树...")
    tree_url = f"{API_BASE}/api/v1/shared-docs/{doc_id}/http-api-tree"
    tree = fetch_json(tree_url) or []
    apis = collect_apis(tree, doc_id)
    if not apis:
        raise RuntimeError("接口树为空，未找到任何接口，请检查链接是否有效")
    _log(f"[成功] 接口树中识别到 {len(apis)} 个 HTTP 接口")

    # 2. 并发抓取接口详情
    _log(f"[步骤3] 开始并发抓取接口详情（{MAX_WORKERS} 线程）...")
    rows = []
    failed = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {pool.submit(fetch_api_detail, api, doc_id): api for api in apis}
        for idx, future in enumerate(as_completed(future_map), 1):
            api = future_map[future]
            try:
                row = future.result()
                rows.append(row)
                _log(f"  [{idx}/{len(apis)}] 完成: {api['name']}")
            except Exception as e:
                failed.append((api, str(e)))
                _log(f"  [{idx}/{len(apis)}] 失败: {api['name']} -> {e}")

    if failed:
        _log(f"\n[警告] {len(failed)} 个接口抓取失败：")
        for api, err in failed:
            _log(f"  - {api['name']} ({api['id']}): {err}")

    if not rows:
        raise RuntimeError("所有接口均抓取失败，未生成 Excel")

    # 3. 写入 Excel
    _log("[步骤4] 正在写入 Excel...")
    output_path = write_excel(rows, doc_id, output_dir)
    _log(f"\n[成功] 共导出 {len(rows)} 条接口数据")
    _log(f"[成功] 文件已保存至: {output_path}")
    if failed:
        _log(f"[提示] 另有 {len(failed)} 个接口抓取失败，详见上方日志")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Apifox 接口文档提取器")
    parser.add_argument("url", nargs="?", default=DEFAULT_DOC_URL,
                        help="Apifox 共享文档链接，默认使用内置链接")
    args = parser.parse_args()

    try:
        run_extract(args.url)
    except Exception as e:
        print(f"[失败] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
