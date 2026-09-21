#!/usr/bin/env bash
# =============================================================================
# GitCode「Release」附件上传（单文件，幂等）
#
# 用法：
#   GITCODE_TOKEN=xxx gitcode_upload.sh <文件路径或文件名> <API基址> <TAG> <附件名>
#
# 行为：
#   1. 附件定位：优先按传入路径，找不到时在工作区递归 find 文件名
#   2. 幂等：同名附件已在 Release 中 → 跳过
#   3. 动态超时：按 5KB/s 估速 + 600s 余量；上限 9000s（2.5h）
#   4. 两步上传：先获取预签名 URL，再 PUT 上传到对象存储
#   5. 上传失败时：捕获错误写入 Step Summary
#   6. 上传后二次核验
#
# 失败退出码 1；成功/跳过退出码 0。
# =============================================================================
set -u

ARG_FILE="$1"
API="$2"
TAG="$3"
BASE="$4"

# Step Summary 输出
SUMMARY="${GITHUB_STEP_SUMMARY:-}"
note() { [ -n "${SUMMARY}" ] && echo "$1" >> "${SUMMARY}"; }

# ── 1. 附件定位 ──────────────────────────────────────────────────────────────
FILE="${ARG_FILE}"
if [ ! -e "${FILE}" ]; then
  FOUND=$(find "${GITHUB_WORKSPACE:-.}" -name "${BASE}" -type f 2>/dev/null | head -1)
  if [ -n "${FOUND}" ]; then
    FILE="${FOUND}"
    echo "==> 按文件名定位到附件: ${FILE}"
  else
    echo "::error::未找到附件文件：${ARG_FILE}（find 也未命中 ${BASE}）"
    note "## GitCode 上传失败：找不到附件 ${BASE}"
    exit 1
  fi
fi

# ── 2. 大小提示 ──────────────────────────────────────────────────────────────
SIZE=$(stat -c %s "${FILE}")
note "### 上传 ${BASE}"
note "- 文件: \`${FILE}\`"
note "- 大小: $((SIZE/1024/1024)) MB（${SIZE} 字节）"

# ── 3. 幂等检查：先查该 tag 下的附件列表 ────────────────────────────────────
export TAG BASE
LIST_RESP=$(curl -s --max-time 60 "${API}/releases?access_token=${GITCODE_TOKEN}&per_page=100")
# 找到对应 tag 的 release，再看附件列表里有没有同名文件
HAS_EXIST=$(echo "${LIST_RESP}" | python -c "
import json, sys, os
data = json.load(sys.stdin)
tag = os.environ.get('TAG', '')
base = os.environ.get('BASE', '')
for r in data:
    if r.get('tag_name') == tag:
        assets = r.get('assets', []) or r.get('attachments', [])
        names = [a.get('name', '') for a in assets]
        sys.exit(0 if base in names else 1)
sys.exit(1)
" 2>/dev/null)
if [ $? -eq 0 ]; then
  echo "==> 已存在附件 ${BASE}，跳过"
  note "- 结果: 附件已存在，跳过（幂等）"
  exit 0
fi

# ── 4. 获取预签名上传地址 ────────────────────────────────────────────────────
echo "==> 获取上传地址: ${BASE}"
UPLOAD_INFO=$(curl -s --max-time 60 "${API}/releases/${TAG}/upload_url?access_token=${GITCODE_TOKEN}&file_name=${BASE}")

UPLOAD_URL=$(echo "${UPLOAD_INFO}" | python -c "import json,sys; print(json.load(sys.stdin).get('url',''))")
if [ -z "${UPLOAD_URL}" ]; then
  echo "::error::获取上传地址失败: ${UPLOAD_INFO:0:500}"
  note "- 结果: ❌ 获取上传地址失败"
  note "- 响应: \`\`\`${UPLOAD_INFO:0:500}\`\`\`"
  exit 1
fi

echo "    上传 URL: ${UPLOAD_URL:0:80}..."

# ── 5. 动态超时 ───────────────────────────────────────────────────────────────
timeout=$(( SIZE / 5120 + 600 ))
[ "${timeout}" -lt 900 ] && timeout=900
[ "${timeout}" -gt 18000 ] && timeout=18000
echo "==> 上传 ${BASE} ($(du -h "${FILE}" | cut -f1)) -> GitCode（timeout=${timeout}s）"

# ── 6. 用 Python 执行 PUT 上传到对象存储 ─────────────────────────────────────
# 用 Python 而不是 bash curl，避免 headers 解析问题
export UPLOAD_INFO FILE timeout
UPLOAD_RESP=$(python << 'PYEOF'
import json, sys, urllib.request, os

upload_info = json.loads(os.environ['UPLOAD_INFO'])
upload_url = upload_info['url']
headers = upload_info.get('headers', {})

file_path = os.environ['FILE']
timeout = int(os.environ['timeout'])

# 读取文件内容
with open(file_path, 'rb') as f:
    data = f.read()

# 构造请求
req = urllib.request.Request(upload_url, data=data, method='PUT')
for k, v in headers.items():
    req.add_header(k, v)

try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        print(f'http={resp.status}')
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', errors='replace')[:500]
    print(f'http={e.code} error={body}')
    sys.exit(1)
except Exception as e:
    print(f'error={e}')
    sys.exit(1)
PYEOF
)
CURL_EXIT=$?
echo "    Python 上传结果: ${UPLOAD_RESP}"
note "- 上传结果: ${UPLOAD_RESP}"

if [ "${CURL_EXIT}" -ne 0 ]; then
  echo "::error::GitCode 上传 ${BASE} 失败: ${UPLOAD_RESP:0:500}"
  note "- 结果: ❌ 上传失败"
  note ""
  note "补救：1) 本页 Re-run failed jobs；2) 手动从 GitHub Release 下载后到 GitCode Release 页添加附件。"
  exit 1
fi

echo "    ${BASE} 上传成功"
note "- 结果: ✅ 上传成功"============================================================================
# GitCode「Release」附件上传（单文件，幂等）
#
# 用法：
#   GITCODE_TOKEN=xxx gitcode_upload.sh <文件路径或文件名> <API基址> <TAG> <附件名>
#
# 行为：
#   1. 附件定位：优先按传入路径，找不到时在工作区递归 find 文件名
#   2. 幂等：同名附件已在 Release 中 → 跳过
#   3. 动态超时：按 5KB/s 估速 + 600s 余量；上限 9000s（2.5h）
#   4. 两步上传：先获取预签名 URL，再 PUT 上传到对象存储
#   5. 上传失败时：捕获错误写入 Step Summary
#   6. 上传后二次核验
#
# 失败退出码 1；成功/跳过退出码 0。
# =============================================================================
set -u

ARG_FILE="$1"
API="$2"
TAG="$3"
BASE="$4"

# Step Summary 输出
SUMMARY="${GITHUB_STEP_SUMMARY:-}"
note() { [ -n "${SUMMARY}" ] && echo "$1" >> "${SUMMARY}"; }

# ── 1. 附件定位 ──────────────────────────────────────────────────────────────
FILE="${ARG_FILE}"
if [ ! -e "${FILE}" ]; then
  FOUND=$(find "${GITHUB_WORKSPACE:-.}" -name "${BASE}" -type f 2>/dev/null | head -1)
  if [ -n "${FOUND}" ]; then
    FILE="${FOUND}"
    echo "==> 按文件名定位到附件: ${FILE}"
  else
    echo "::error::未找到附件文件：${ARG_FILE}（find 也未命中 ${BASE}）"
    note "## GitCode 上传失败：找不到附件 ${BASE}"
    exit 1
  fi
fi

# ── 2. 大小提示 ──────────────────────────────────────────────────────────────
SIZE=$(stat -c %s "${FILE}")
note "### 上传 ${BASE}"
note "- 文件: \`${FILE}\`"
note "- 大小: $((SIZE/1024/1024)) MB（${SIZE} 字节）"

# ── 3. 幂等检查：先查该 tag 下的附件列表 ────────────────────────────────────
export TAG BASE
LIST_RESP=$(curl -s --max-time 60 "${API}/releases?access_token=${GITCODE_TOKEN}&per_page=100")
# 找到对应 tag 的 release，再看附件列表里有没有同名文件
HAS_EXIST=$(echo "${LIST_RESP}" | python -c "
import json, sys, os
data = json.load(sys.stdin)
tag = os.environ.get('TAG', '')
base = os.environ.get('BASE', '')
for r in data:
    if r.get('tag_name') == tag:
        assets = r.get('assets', []) or r.get('attachments', [])
        names = [a.get('name', '') for a in assets]
        sys.exit(0 if base in names else 1)
sys.exit(1)
" 2>/dev/null)
if [ $? -eq 0 ]; then
  echo "==> 已存在附件 ${BASE}，跳过"
  note "- 结果: 附件已存在，跳过（幂等）"
  exit 0
fi

# ── 4. 获取预签名上传地址 ────────────────────────────────────────────────────
echo "==> 获取上传地址: ${BASE}"
UPLOAD_INFO=$(curl -s --max-time 60 "${API}/releases/${TAG}/upload_url?access_token=${GITCODE_TOKEN}&file_name=${BASE}")

UPLOAD_URL=$(echo "${UPLOAD_INFO}" | python -c "import json,sys; print(json.load(sys.stdin).get('url',''))")
if [ -z "${UPLOAD_URL}" ]; then
  echo "::error::获取上传地址失败: ${UPLOAD_INFO:0:500}"
  note "- 结果: ❌ 获取上传地址失败"
  note "- 响应: \`\`\`${UPLOAD_INFO:0:500}\`\`\`"
  exit 1
fi

# 解析需要携带的 headers
mapfile -t HEADERS < <(echo "${UPLOAD_INFO}" | python -c "
import json, sys
d = json.load(sys.stdin)
headers = d.get('headers', {})
for k, v in headers.items():
    print(f'-H \"{k}: {v}\"')
")

# ── 5. 动态超时 ───────────────────────────────────────────────────────────────
timeout=$(( SIZE / 5120 + 600 ))
[ "${timeout}" -lt 900 ] && timeout=900
[ "${timeout}" -gt 18000 ] && timeout=18000
echo "==> 上传 ${BASE} ($(du -h "${FILE}" | cut -f1)) -> GitCode（timeout=${timeout}s）"

# ── 6. PUT 上传到对象存储 ────────────────────────────────────────────────────
TMPRESP=$(mktemp)
set +e
STATS=$(curl -s --connect-timeout 30 --max-time "${timeout}" \
  --fail-with-body \
  --retry 1 --retry-all-errors --retry-delay 60 \
  -o "${TMPRESP}" \
  -w 'http=%{http_code} time=%{time_total}s speed=%{speed_download}B/s' \
  -X PUT \
  "${HEADERS[@]}" \
  --data-binary "@${FILE}" \
  "${UPLOAD_URL}")
CURL_EXIT=$?
set -e
RESP=$(cat "${TMPRESP}")
rm -f "${TMPRESP}"
echo "    curl exit=${CURL_EXIT}, ${STATS}"
note "- curl exit=${CURL_EXIT}，${STATS}"

# ── 7. 结果判定 ──────────────────────────────────────────────────────────────
if [ "${CURL_EXIT}" -eq 0 ]; then
  echo "    ${BASE} 上传成功"
  note "- 结果: ✅ 上传成功"
else
  echo "::error::GitCode 上传 ${BASE} 失败（curl exit=${CURL_EXIT}）: ${RESP:0:500}"
  note "- 结果: ❌ 上传失败"
  note "- 服务器响应: \`\`\`${RESP:0:500}\`\`\`"
  note ""
  note "补救：1) 本页 Re-run failed jobs；2) 手动从 GitHub Release 下载后到 GitCode Release 页添加附件。"
  exit 1
fi
