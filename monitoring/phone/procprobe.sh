#!/data/data/com.termux/files/usr/bin/bash
# 进程数极限探针 —— 一路爬到被杀或撞 ulimit，不在中途停。
# ⚑ 上次只测到 60 就停，那是我自己设的线，不是设备的极限。
#   ulimit -u=58911，phantom 上限又没生效，真极限远在 60 之上。
set -u
TARGET=${1:-2000}
LOG=~/procprobe.log; : > "$LOG"
log(){ echo "$*" >> "$LOG"; sync; }
count(){ ls /proc 2>/dev/null | grep -cE '^[0-9]+$'; }
svc(){ local n=0; for f in prom grafana exporter fb aria2 ariang; do p=$(cat ~/$f.pid 2>/dev/null); [ -n "$p" ]&&kill -0 "$p" 2>/dev/null&&n=$((n+1)); done; pgrep -x sshd>/dev/null&&n=$((n+1)); pgrep -x rclone>/dev/null&&n=$((n+1)); echo $n; }
log "# $(date '+%F %T') target=$TARGET ulimit_u=$(ulimit -u)"
log "spawned procs svc"
pids=""; i=0
while [ "$i" -lt "$TARGET" ]; do
  sleep 3600 & pids="$pids $!" || { log "# fork 失败 at $i"; break; }
  i=$((i+1))
  if [ $((i % 50)) -eq 0 ]; then
    c=$(count); s=$(svc); log "$i $c $s"
    [ "$s" -lt 8 ] && { log "# 服务掉到 $s，进程数 $c，已派生 $i"; break; }
  fi
done
log "# 峰值：派生 $i  进程 $(count)  服务 $(svc)/8"
for p in $pids; do kill "$p" 2>/dev/null; done
sleep 3
log "# 清理后 进程 $(count) 服务 $(svc)/8"
