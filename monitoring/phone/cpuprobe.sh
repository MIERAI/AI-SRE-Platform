#!/data/data/com.termux/files/usr/bin/bash
# CPU 热极限探针 —— 8 线程全核烧久，看热杀/热节流的底。
# ⚑ 上次只烧 180 秒、4 线程，系统降频就扛住了 —— 那不是极限。
#   这次 8 线程全核，烧到指定秒数，看温度爬到多高、频率被压多低、会不会被杀。
set -u
N=${1:-8}; SEC=${2:-600}
LOG=~/cpuprobe.log; : > "$LOG"
log(){ echo "$*" >> "$LOG"; sync; }
tmax(){ for z in /sys/class/thermal/thermal_zone*/temp; do cat "$z" 2>/dev/null; done | awk '{if($1>m&&$1<150000)m=$1}END{printf "%.1f",m/1000}'; }
freq(){ echo $(( $(cat /sys/devices/system/cpu/cpu$1/cpufreq/scaling_cur_freq 2>/dev/null||echo 0)/1000 )); }
svc(){ local n=0; for f in prom grafana exporter fb aria2 ariang; do p=$(cat ~/$f.pid 2>/dev/null); [ -n "$p" ]&&kill -0 "$p" 2>/dev/null&&n=$((n+1)); done; pgrep -x sshd>/dev/null&&n=$((n+1)); pgrep -x rclone>/dev/null&&n=$((n+1)); echo $n; }

log "# $(date '+%F %T') threads=$N seconds=$SEC"
log "t temp_c cpu0 cpu4 cpu7 workers_alive svc"
pids=""
for i in $(seq 1 "$N"); do ( while :; do :; done ) & pids="$pids $!"; done
t=0
while [ "$t" -lt "$SEC" ]; do
  sleep 5; t=$((t+5))
  alive=$(for p in $pids; do kill -0 "$p" 2>/dev/null&&echo x; done | wc -l)
  s=$(svc)
  log "$t $(tmax) $(freq 0) $(freq 4) $(freq 7) $alive $s"
  # 有 worker 被杀 或 服务掉了 → 记下就停
  [ "$alive" -lt "$N" ] && { log "# worker 被杀：$alive/$N 存活，t=$t，温度 $(tmax)°C"; break; }
  [ "$s" -lt 8 ] && { log "# 服务掉到 $s/8，t=$t，温度 $(tmax)°C"; break; }
done
for p in $pids; do kill "$p" 2>/dev/null; done
sleep 2
log "# 结束 t=$t 峰值温度见上 worker存活=$(for p in $pids; do kill -0 $p 2>/dev/null&&echo x;done|wc -l) svc=$(svc)/8"
