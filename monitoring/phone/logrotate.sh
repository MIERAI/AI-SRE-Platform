#!/data/data/com.termux/files/usr/bin/bash
# 日志轮转。由 watchdog 每 15 分钟调用。
#
# ⚑ 为什么需要：今天亲眼见过一次失控 —— llama-cli 进交互模式后在 EOF 上空转
#   刷 "> "，**378 MB / 3 分钟**（约 2 MB/s）。按那个速率 638 GB 会在
#   88 小时内被填满，而人要离开两个月。
#   diskguard 只管暂停 aria2 的下载，不管日志。
#
# ⚑ watchdog 每 15 分钟才跑一次，所以最坏情况下失控日志能写约 1.8 GB
#   才被截断。相对 638 GB 完全可接受 —— 这里不需要更高频的检查，
#   需要的是「不会无上界」。
#
# ⚑ 截断用 `tail > tmp && mv`，不用 `truncate` 或 `> file`：
#   后两者会让正在写这个文件的进程的文件偏移量失效（写到空洞里，
#   文件大小瞬间跳回原值且中间全是 \0）。mv 换新 inode 则让旧进程
#   继续写旧 inode —— 它会被 unlink 后随进程退出释放。
#   代价：正在运行的进程之后的输出看不到了。对失控日志来说这正是想要的。

set -u
MAX_KB=${MAX_KB:-2048}        # 单个文件超过这个大小就截断
KEEP=${KEEP:-500}             # 保留最后多少行
LOG=~/logrotate.log

FILES="
$HOME/watchdog.log
$HOME/archive.log
$HOME/diskguard.log
$HOME/rclone.log
$HOME/exporter.log
$HOME/transmission.log
$HOME/boot_trace.log
$HOME/memtest.log
$HOME/memprobe.log
$HOME/photopush.log
$HOME/tunwatch.log
$HOME/llama_test.log
$HOME/llama2.log
$HOME/prom/prometheus.log
$HOME/grafana/logs/grafana.log
$HOME/grafana/logs/stdout.log
$HOME/fb/stdout.log
$HOME/.aria2/aria2.log
$HOME/.aria2/stdout.log
$HOME/.aria2/ui.log
"

rotated=0
total_kb=0
for f in $FILES; do
  [ -f "$f" ] || continue
  kb=$(( $(wc -c < "$f" 2>/dev/null || echo 0) / 1024 ))
  total_kb=$((total_kb + kb))
  if [ "$kb" -gt "$MAX_KB" ]; then
    tail -n "$KEEP" "$f" > "$f.rot" 2>/dev/null && mv "$f.rot" "$f" 2>/dev/null && {
      echo "$(date '+%F %T') 截断 ${f#$HOME/} （${kb} KB → 保留 $KEEP 行）" >> "$LOG"
      rotated=$((rotated + 1))
    }
  fi
done

# ⚑ 兜底：任何在 $HOME 下失控的 .log，即使不在上面的白名单里也要处理。
#   今天那个 378 MB 的文件就是临时起的，白名单不可能预先包含它。
while read -r sz path; do
  [ -z "${path:-}" ] && continue
  case " $FILES " in *" $path "*) continue ;; esac
  tail -n "$KEEP" "$path" > "$path.rot" 2>/dev/null && mv "$path.rot" "$path" 2>/dev/null && {
    echo "$(date '+%F %T') 截断（白名单外）${path#$HOME/} （$((sz/1024)) KB）" >> "$LOG"
    rotated=$((rotated + 1))
  }
done <<< "$(find "$HOME" -maxdepth 3 -name '*.log' -size +${MAX_KB}k \
            -printf '%s %p\n' 2>/dev/null || true)"

# 给 exporter 读
printf '{"rotated":%d,"total_kb":%d,"checked":%d}\n' \
  "$rotated" "$total_kb" "$(date +%s)" > "$HOME/logrotate_stats.json"

[ "${1:-}" = "-v" ] && echo "  日志总计 ${total_kb} KB，本轮截断 $rotated 个"
exit 0
