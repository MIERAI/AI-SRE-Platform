#!/data/data/com.termux/files/usr/bin/bash
# CPU 压力探针 —— 测「持续满载」会不会让 Android 杀掉 Termux。
#
# ⚑ 为什么需要单独测 CPU：memprobe 证明 14 GB 匿名分配【不会】杀掉 Termux
#   （页缓存被榨干、约 3 GB 写进 swap、oom_score 爬到 1196，但始终没被杀）。
#   所以下午 llama.cpp 那次不是内存的事。剩下的变量是：
#     · 4 个线程满载
#     · "> " 空转循环每秒写约 2 MB
#   Android 12+ 的 phantom process 机制除了进程数上限，还会杀
#   【CPU 占用过高】的子进程 —— 这个假设比"内存不够"更能解释观测。
#
#   用法：  ~/cpuprobe.sh 4 180          4 个线程烧 180 秒
#          ~/cpuprobe.sh 4 180 disk     同时每秒写 2 MB（复现完整场景）

set -u
N=${1:-4}; SEC=${2:-180}; MODE=${3:-cpu}
LOG=~/cpuprobe.log
: > "$LOG"
log(){ echo "$*" >> "$LOG"; sync; }

log "# $(date '+%F %T') threads=$N seconds=$SEC mode=$MODE"
log "t temp_max_c cpu0_mhz cpu7_mhz procs alive"

pids=""
for i in $(seq 1 "$N"); do
  ( while :; do :; done ) & pids="$pids $!"
done
if [ "$MODE" = "disk" ]; then
  # 复现那个空转循环的写盘速率
  ( while :; do head -c 2000000 /dev/zero | tr '\0' 'x' >> ~/cpuprobe_spam.log; sleep 1; done ) &
  pids="$pids $!"
fi

t=0
while [ "$t" -lt "$SEC" ]; do
  sleep 5; t=$((t+5))
  tmax=$(for z in /sys/class/thermal/thermal_zone*/temp; do cat "$z" 2>/dev/null; done \
         | awk '{if($1>m && $1<150000) m=$1} END{printf "%.1f", m/1000}')
  c0=$(( $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || echo 0) / 1000 ))
  c7=$(( $(cat /sys/devices/system/cpu/cpu7/cpufreq/scaling_cur_freq 2>/dev/null || echo 0) / 1000 ))
  np=$(ls /proc | grep -cE '^[0-9]+$')
  alive=$(for p in $pids; do kill -0 "$p" 2>/dev/null && echo x; done | wc -l)
  log "$t $tmax $c0 $c7 $np $alive"
done

for p in $pids; do kill "$p" 2>/dev/null; done
rm -f ~/cpuprobe_spam.log
log "# 正常结束，未被杀"
