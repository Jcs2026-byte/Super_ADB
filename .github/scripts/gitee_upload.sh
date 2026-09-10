#!/usr/bin/env bash
# =============================================================================
# Gitee「发行版」附件上传（单文件，幂等）
#
# 用法：
#   GITEE_TOKEN=xxx gitee_upload.sh <文件路径或文件名> <API基址> <RID> <附件名>
#
# 行为：
#   1. 附件定位：优先按传入路径，找不到时在工作区递归 find 文件名
#      （兼容 actions/download-artifact 不同版本目录结构差异）
#   2. 幂等：同名附件已在 Gitee 发行版中 → 跳过（支持安全重跑，只补传失败的包）
#   3. 超过 Gitee 单附件 100MB 硬限制 → 跳过并提示去 GitHub Release 下载
#   4. 动态超时：按 5KB/s 估速 + 600s 余量；上限 9000s（2.5h），下限 900s
#   5. 动态速度底线：低于「能在超时内传完」的最低平均速度且持续 300s → 判死
#      （下限 5120 B/s，即 5KB/s；跨境 10~20KB/s 常态链路可稳定传完）
#   6. 上传失败时：捕获 curl 退出码 + 服务器响应体，全部写入 Step Summary
#      （Actions 网页可直接查看，无需登录拉日志）
#   7. 上传后二次核验：响应含 id 且 Gitee 附件列表真实出现该文件名
#
# 失败退出码 1；成功/跳过退出码 0。
# =============================================================================
set -u

ARG_FILE="$1"
API="$2"
RID="$3"
BASE="$4"

# Step Summary 输出（网页可见，无需拉日志）
SUMMARY="${GITHUB_STEP_SUMMARY:-}"
note() { [ -n "${SUMMARY}" ] && echo "$1" >> "${SUMMARY}"; }

# ── 1. 附件定位 ──────────────────────────────────────────────────────────────
FILE="${ARG_FILE}"
if [ ! -e "${FILE}" ]; then
  # 递归查找同名文件（兼容下载目录结构差异）
  FOUND=$(find "${GITHUB_WORKSPACE:-.}" -name "${BASE}" -type f 2>/dev/null | head -1)
  if [ -n "${FOUND}" ]; then
    FILE="${FOUND}"
    echo "==> 按文件名定位到附件: ${FILE}"
  else
    echo "::error::未找到附件文件：${ARG_FILE}（find 也未命中 ${BASE}）"
    note "## Gitee 上传失败：找不到附件 ${BASE}"
    note "请求路径: ${ARG_FILE}"
    note "工作目录: $(pwd)"
    note "当前目录内容:"
    ls -la | sed 's/^/    /' >> "${SUMMARY}"
    exit 1
  fi
fi

# ── 2. 大小与硬限制 ──────────────────────────────────────────────────────────
SIZE=$(stat -c %s "${FILE}")
note "### 上传 ${BASE}"
note "- 文件: \`${FILE}\`"
note "- 大小: $((SIZE/1024/1024)) MB（${SIZE} 字节）"
if [ "${SIZE}" -gt 104857600 ]; then
  echo "::warning::${BASE} 大小 ${SIZE} 字节（约 $((SIZE/1024/1024))MB）超过 Gitee 单附件 100MB 限制，跳过上传"
  echo "::warning::请到 GitHub Release 下载：https://github.com/Jcs2026-byte/Super_ADB/releases"
  note "- 结果: 超过 100MB 硬限制，跳过（去 GitHub Release 下载）"
  exit 0
fi

# ── 3. 幂等检查 ──────────────────────────────────────────────────────────────
LIST_RESP=$(curl -s --max-time 60 "${API}/releases/${RID}/attach_files?per_page=100&access_token=${GITEE_TOKEN}")
if echo "${LIST_RESP}" | python -c "import json,sys; data=json.load(sys.stdin); names=[a.get('name','') for a in data]; sys.exit(0 if '${BASE}' in names else 1)" 2>/dev/null; then
  echo "==> 已存在附件 ${BASE}，跳过"
  note "- 结果: 附件已存在，跳过（幂等）"
  exit 0
fi

# ── 4. 动态超时与速度底线 ────────────────────────────────────────────────────
timeout=$(( SIZE / 5120 + 600 ))
[ "${timeout}" -lt 900 ] && timeout=900
[ "${timeout}" -gt 9000 ] && timeout=9000
speed_limit=$(( SIZE / timeout ))
[ "${speed_limit}" -lt 5120 ] && speed_limit=5120
echo "==> 上传 ${BASE} ($(du -h "${FILE}" | cut -f1)) -> release ${RID}（timeout=${timeout}s, 底线=${speed_limit}B/s）"

# ── 5. 上传（捕获退出码，服务器错误体进 summary）────────────────────────────
TMPRESP=$(mktemp)
set +e
STATS=$(curl -s --connect-timeout 30 --max-time "${timeout}" \
  --fail-with-body \
  --retry 1 --retry-all-errors --retry-delay 60 \
  --speed-limit "${speed_limit}" --speed-time 300 \
  -o "${TMPRESP}" \
  -w 'http=%{http_code} time=%{time_total}s speed=%{speed_download}B/s' \
  -X POST "${API}/releases/${RID}/attach_files" \
  -F "access_token=${GITEE_TOKEN}" -F "file=@${FILE}")
CURL_EXIT=$?
set -e
RESP=$(cat "${TMPRESP}")
rm -f "${TMPRESP}"
echo "    curl exit=${CURL_EXIT}, ${STATS}"
note "- curl exit=${CURL_EXIT}，${STATS}"
[ -n "${RESP}" ] || RESP="(无响应体)"

# ── 6. 二次核验 ──────────────────────────────────────────────────────────────
if [ "${CURL_EXIT}" -eq 0 ] \
  && echo "${RESP}" | python -c "import json,sys; d=json.load(sys.stdin); assert d.get('id'); print('    uploaded id=', d.get('id'))" 2>/dev/null \
  && sleep 3 \
  && curl -s --max-time 60 "${API}/releases/${RID}/attach_files?per_page=100&access_token=${GITEE_TOKEN}" \
       | python -c "import json,sys; data=json.load(sys.stdin); names=[a.get('name','') for a in data]; sys.exit(0 if '${BASE}' in names else 1)" 2>/dev/null; then
  echo "    ${BASE} 上传成功并通过核验"
  note "- 结果: ✅ 上传成功并通过核验"
else
  echo "::error::Gitee 上传 ${BASE} 失败（curl exit=${CURL_EXIT}）: ${RESP:0:500}"
  note "- 结果: ❌ 上传失败"
  note "- 服务器响应: \`\`\`${RESP:0:500}\`\`\`"
  note ""
  note "补救：1) 本页 Re-run failed jobs（幂等，已成功附件跳过，只补传失败的包）；"
  note "      2) 手动上传：从 GitHub Release 下载 ${BASE} 后到 Gitee 发行版页添加附件（国内链路，速度快）。"
  exit 1
fi
