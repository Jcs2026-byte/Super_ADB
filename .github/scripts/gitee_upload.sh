#!/usr/bin/env bash
# =============================================================================
# Gitee「发行版」附件上传（单文件，幂等）
#
# 用法：
#   GITEE_TOKEN=xxx gitee_upload.sh <文件路径> <API基址> <RID> <附件名>
#
# 行为：
#   1. 幂等：同名附件已在 Gitee 发行版中 → 跳过（支持安全重跑，只补传失败的包）
#   2. 超过 Gitee 单附件 100MB 硬限制 → 跳过并提示去 GitHub Release 下载
#   3. 动态超时：按 5KB/s 估速 + 600s 余量；上限 9000s（2.5h），下限 900s
#   4. 动态速度底线：低于「能在超时内传完」的最低平均速度且持续 300s
#      → 判死快速重试（默认 1 次，间隔 60s），避免在死链路上空耗
#      下限 5120 B/s（5KB/s）：跨境 10~20KB/s 常态链路可稳定传完，
#      而旧的 10KB/s 硬底线 + 60min 超时会在临界速度上反复判死重试。
#   5. 上传后二次核验：响应含 id 且 Gitee 附件列表真实出现该文件名
#
# 失败退出码 1；成功/跳过退出码 0。
# =============================================================================
set -u

FILE="$1"
API="$2"
RID="$3"
BASE="$4"

if [ ! -e "${FILE}" ]; then
  echo "::warning::缺少附件 ${FILE}，跳过（GitHub Release 仍已正常发布）"
  exit 0
fi

# Gitee 单附件硬限制 100MB：超限则跳过上传并提示去 GitHub 下载（上传必败，不再空耗）
SIZE=$(stat -c %s "${FILE}")
if [ "${SIZE}" -gt 104857600 ]; then
  echo "::warning::${BASE} 大小 ${SIZE} 字节（约 $((SIZE/1024/1024))MB）超过 Gitee 单附件 100MB 限制，跳过上传"
  echo "::warning::请到 GitHub Release 下载：https://github.com/Jcs2026-byte/Super_ADB/releases"
  exit 0
fi

# 幂等：同名附件已存在则跳过
if curl -s --max-time 60 "${API}/releases/${RID}/attach_files?per_page=100&access_token=${GITEE_TOKEN}" \
    | python -c "import json,sys; data=json.load(sys.stdin); names=[a.get('name','') for a in data]; sys.exit(0 if '${BASE}' in names else 1)" 2>/dev/null; then
  echo "==> 已存在附件 ${BASE}，跳过"
  exit 0
fi

# 动态超时：按 5KB/s 估速 + 600s 固定余量；上限 9000s(2.5h)，下限 900s
timeout=$(( SIZE / 5120 + 600 ))
[ "${timeout}" -lt 900 ] && timeout=900
[ "${timeout}" -gt 9000 ] && timeout=9000
# 动态速度底线：低于"能在超时内传完"的平均速度且持续 300s → 判死重试；下限 5KB/s
# （v2026.09.10 教训：56MB 包在 ~12KB/s 慢速链路空耗 74min，固定 10KB/s 底线太高；
#   当前 55MB 包旧参数底线 ~20KB/s，跨境链路一低于它即判死，3 次重试全败 → mac 一直传不上）
speed_limit=$(( SIZE / timeout ))
[ "${speed_limit}" -lt 5120 ] && speed_limit=5120
echo "==> 上传 ${BASE} ($(du -h "${FILE}" | cut -f1)) -> release ${RID}（timeout=${timeout}s, 底线=${speed_limit}B/s）"

TMPRESP=$(mktemp)
# -o 写响应体、-w 写统计到 stdout，互不污染；HTTP 码 + 耗时 + 速度一并输出
STATS=$(curl -s --connect-timeout 30 --max-time "${timeout}" \
  --retry 1 --retry-all-errors --retry-delay 60 \
  --speed-limit "${speed_limit}" --speed-time 300 \
  -o "${TMPRESP}" \
  -w 'http=%{http_code} time=%{time_total}s speed=%{speed_download}B/s' \
  -X POST "${API}/releases/${RID}/attach_files" \
  -F "access_token=${GITEE_TOKEN}" -F "file=@${FILE}")
RESP=$(cat "${TMPRESP}")
rm -f "${TMPRESP}"
echo "    curl: ${STATS}"
[ -n "${RESP}" ] || RESP="(无响应体)"

# 上传后二次核验：确认附件真实出现在 Gitee 附件列表（防半截上传）
if echo "${RESP}" | python -c "import json,sys; d=json.load(sys.stdin); assert d.get('id'); print('    uploaded id=', d.get('id'))" 2>/dev/null \
  && sleep 3 \
  && curl -s --max-time 60 "${API}/releases/${RID}/attach_files?per_page=100&access_token=${GITEE_TOKEN}" \
       | python -c "import json,sys; data=json.load(sys.stdin); names=[a.get('name','') for a in data]; sys.exit(0 if '${BASE}' in names else 1)" 2>/dev/null; then
  echo "    ${BASE} 上传成功并通过核验"
else
  echo "::error::Gitee 上传 ${BASE} 失败: ${RESP:0:300}"
  echo "::error::补救：1) 本页 Re-run failed jobs（幂等，已成功附件跳过，只补传失败的包）；"
  echo "::error::      2) 手动上传：从 GitHub Release 下载 ${BASE} 后到 Gitee 发行版页添加附件（国内链路，速度快）。"
  exit 1
fi
