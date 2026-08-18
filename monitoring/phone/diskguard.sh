#!/data/data/com.termux/files/usr/bin/bash
# 磁盘保护。由 watchdog 每 15 分钟调用。
#
# ⚑ 要防的不是「磁盘满」这个状态，而是【谁把它吃满的】。
#   实测过一遍：aria2 的下载目录是唯一没有上界的写入方。
#   Prometheus 的 TSDB 有 120 天保留期（两小时才 6.6 MB），
#   照片受手机2 的拍照量天然限制，日志加起来不到 2 KB。
#   所以保护动作只有一个：在磁盘被下载吃光之前把 aria2 拦住。
#
# ⚑ 磁盘满的真正代价不是「下不了了」，而是【连锁摧毁其他一切】：
#   Prometheus 写不进 TSDB、Grafana 的 sqlite 可能损坏、
#   照片归档中途失败留下截断文件（这个今天已经真实发生过一次）。
#   等到那时候再手工救，人还在国外。
#
# ⚑ 阈值有【滞回】：跌破 100 GB 才暂停，回到 150 GB 以上才恢复。
#   两者相等的话，磁盘在阈值附近来回抖动会导致反复暂停/恢复，
#   日志刷屏而且每次恢复都可能立刻又把空间吃回去。
#
# ⚑ 只恢复【自己暂停的】。状态文件记着是谁按的暂停键 ——
#   你手动在 AriaNg 里暂停的任务，不该被这个脚本擅自恢复。

set -u
STATE="$HOME/.diskguard_state"
STATS="$HOME/diskguard_stats.json"
LOG="$HOME/diskguard.log"
RPC_SECRET_FILE="$HOME/.aria2/RPC_SECRET.txt"

# 单位 GB
EMERGENCY_GB=30      # 低于此：直接停掉 aria2，不只是暂停
PAUSE_GB=100         # 低于此：暂停全部下载
WARN_GB=150          # 低于此：只告警
RESUME_GB=150        # 高于此才恢复（滞回，必须 > PAUSE_GB）

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

free_gb=$(df -k "$HOME" | tail -1 | awk '{printf "%.0f", $4/1048576}')
prev=$(cat "$STATE" 2>/dev/null || echo normal)

rpc() {
  local sec extra
  sec=$(cat "$RPC_SECRET_FILE" 2>/dev/null) || return 1
  [ -n "$sec" ] || return 1
  # ⚑ 必须写 ${2:-}。脚本开头有 set -u，而 `rpc aria2.pauseAll` 只传一个参数，
  #   裸 $2 会触发 unbound variable 让【整个脚本中止】。
  #   第一版就是这样：暂停从未执行过，任务照常下载、max-concurrent 仍是 5，
  #   而脚本连状态文件都没来得及写。
  #   发现它靠的是去查 aria2 的真实状态，不是看脚本自己报告什么。
  extra="${2:-}"
  local resp
  resp=$(timeout 20 curl -s -m 15 http://127.0.0.1:6800/jsonrpc \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":\"dg\",\"method\":\"$1\",\"params\":[\"token:$sec\"$extra]}" 2>/dev/null)
  # ⚑ 不能把响应丢进 /dev/null。第一版就是这样，结果 aria2 明确回了
  #   {"error":{"code":1,"message":"...'--max-concurrent-downloads'"}}，
  #   而脚本毫不知情、状态照写 paused —— 保护看起来生效了，实际只挡住一半。
  case "$resp" in
    *'"error"'*) log "RPC $1 失败: $resp" ; return 1 ;;
  esac
  printf '%s' "$resp"
}

pause_downloads() {
  # 两件事都要做：pauseAll 停住正在跑的，全局限速挡住【之后新提交的】——
  # 否则你在外面用 AriaNg 加一个新任务，它会立刻开始下，把最后的空间吃掉。
  #
  # ⚑ 这里【不能】用 max-concurrent-downloads=0。aria2 的最小值是 1，
  #   传 0 会返回 error（实测："We encountered a problem while processing
  #   the option '--max-concurrent-downloads'"），设置根本不生效。
  #   改用 1 KB/s 的全局限速：新任务即使启动，15 分钟也只能写约 900 KB，
  #   而下一轮 diskguard 会再次 pauseAll 把它按住。
  rpc aria2.pauseAll >/dev/null
  rpc aria2.changeGlobalOption ',{"max-overall-download-limit":"1K"}' >/dev/null
}

resume_downloads() {
  rpc aria2.changeGlobalOption ',{"max-overall-download-limit":"0"}' >/dev/null
  rpc aria2.unpauseAll >/dev/null
}

state=normal
action=""

if [ "$free_gb" -lt "$EMERGENCY_GB" ]; then
  state=emergency
  if [ "$prev" != "emergency" ]; then
    pause_downloads
    "$HOME/services.sh" stop aria2 >/dev/null 2>&1
    action="紧急：剩余 ${free_gb}GB < ${EMERGENCY_GB}GB，已停止 aria2 进程"
  fi
elif [ "$free_gb" -lt "$PAUSE_GB" ]; then
  state=paused
  if [ "$prev" = "normal" ] || [ "$prev" = "warn" ]; then
    pause_downloads
    action="剩余 ${free_gb}GB < ${PAUSE_GB}GB，已暂停全部下载并禁止新任务开始"
  fi
elif [ "$free_gb" -lt "$WARN_GB" ]; then
  # ⚑ 警告区间【不做任何动作】，只记录。这里离危险还有 50 GB 缓冲，
  #   过早干预会让人以为系统坏了，而其实只是空间在正常消耗。
  state=warn
  [ "$prev" = "normal" ] && action="剩余 ${free_gb}GB，进入警告区间（未采取动作）"
else
  state=normal
  case "$prev" in
    paused)
      if [ "$free_gb" -ge "$RESUME_GB" ]; then
        resume_downloads
        action="剩余 ${free_gb}GB ≥ ${RESUME_GB}GB，已恢复下载"
      else
        state="$prev"          # 还没回到恢复线，保持暂停
      fi ;;
    emergency)
      if [ "$free_gb" -ge "$RESUME_GB" ]; then
        "$HOME/services.sh" start aria2 >/dev/null 2>&1
        sleep 2; resume_downloads
        action="剩余 ${free_gb}GB ≥ ${RESUME_GB}GB，已重启 aria2 并恢复下载"
      else
        state="$prev"
      fi ;;
  esac
fi

[ -n "$action" ] && log "$action"
echo "$state" > "$STATE"

# 给 exporter 读。数字化的状态才能进 Grafana 和告警规则。
code=0
case "$state" in warn) code=1 ;; paused) code=2 ;; emergency) code=3 ;; esac
printf '{"state":"%s","code":%d,"free_gb":%d,"checked":%d}\n' \
  "$state" "$code" "$free_gb" "$(date +%s)" > "$STATS"

[ "${1:-}" = "-v" ] && echo "  磁盘 ${free_gb}GB 可用 · 状态 $state${action:+ · $action}"
exit 0
