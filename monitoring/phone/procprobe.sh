#!/data/data/com.termux/files/usr/bin/bash
# 进程数探针 —— 测 Android 的 phantom process 上限（32）是不是硬性触发。
#
# ⚑ 为什么这个比内存/CPU 探针更有希望：
#   内存和 CPU 的杀进程是 lmkd 按【压力】决定的，实测四种压力都杀不掉
#   （14 GB 匿名、80°C 满载、CPU+写盘、8.6 GB mmap 抖动，全部存活）。
#   而 phantom process 是安卓文档写明的【硬性数量上限】：
#   一个应用的子进程超过 32 个就杀。这是个数字，不是判断。
#
#   用法： ~/procprobe.sh 60        爬到 60 个进程

set -u
TARGET=${1:-60}
LOG=~/procprobe.log
: > "$LOG"
log(){ echo "$*" >> "$LOG"; sync; }

count(){ ls /proc | grep -cE '^[0-9]+$'; }
svc_ok(){ 
  local n=0
  for f in prom grafana exporter fb aria2 ariang; do
    p=$(cat ~/$f.pid 2>/dev/null)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null && n=$((n+1))
  done
  pgrep -x sshd >/dev/null && n=$((n+1))
  pgrep -x rclone >/dev/null && n=$((n+1))
  echo $n
}

log "# $(date '+%F %T') target=$TARGET"
log "spawned procs services_alive"
log "0 $(count) $(svc_ok)"

pids=""
i=0
while [ "$(count)" -lt "$TARGET" ]; do
  sleep 3600 & pids="$pids $!"
  i=$((i+1))
  c=$(count); s=$(svc_ok)
  log "$i $c $s"
  # 服务掉了就立刻记下并停止爬坡 —— 这就是要找的那个点
  if [ "$s" -lt 8 ]; then
    log "# 服务从 8 掉到 $s，发生在进程数 $c（已派生 $i 个）"
    break
  fi
  sleep 0.3
done
log "# 爬坡结束：进程 $(count)  服务 $(svc_ok)/8  派生 $i 个"
# 自己清理
for p in $pids; do kill "$p" 2>/dev/null; done
sleep 2
log "# 清理后 进程 $(count)  服务 $(svc_ok)/8"
