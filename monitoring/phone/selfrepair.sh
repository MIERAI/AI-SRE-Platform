#!/data/data/com.termux/files/usr/bin/bash
# 连续启动失败时隔离损坏数据。由 watchdog 每轮调用。
#
# ⚑ 要解决的失效：硬杀之后数据文件损坏，服务【拒绝启动】。
#   Prometheus 的 WAL、Grafana 的 sqlite、filebrowser 的 bolt 都有这个特性。
#   而 watchdog 会每 15 分钟重试一次、日志里一直有「启动失败」的记录 ——
#   人两个月后回来才发现监控从第三天就停了。
#   今天把这几个服务硬杀过很多次，所以这不是假想。
#
# ⚑ **隔离，不删除。** 移到 quarantine/ 带时间戳，人回来还能分析。
#   自动删数据是绝对不能做的事：万一判断错了就是永久损失，
#   而「判断错」在今天已经发生过好几次（截断检测误杀 11 张 Motion Photo）。
#
# ⚑ 触发阈值是【连续】3 次失败（45 分钟），不是累计。
#   偶发的启动失败（端口还没释放、锁还没清）不该触发重建。
#
# ⚑ 为什么重建是安全的：Grafana 的看板和数据源全部来自 provisioning，
#   admin 账号会按 grafana.ini 重建；filebrowser 的密码存在
#   ADMIN_PASSWORD.txt 里。所以丢的只有历史数据，不是配置。
#   Prometheus 的 TSDB 丢了确实可惜 —— 但「完全没有监控」更糟。

set -u
STATE=~/.start_failures
QUAR=~/quarantine
LOG=~/selfrepair.log
THRESHOLD=${THRESHOLD:-3}

mkdir -p "$STATE" "$QUAR"
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

# 由 watchdog 传入本轮失败的服务名（空格分隔）；没传就自己探测
failed="${1:-}"
if [ -z "$failed" ]; then
  failed=$(~/services.sh status 2>/dev/null | awk '/✗|无响应|无应答/{print $1}' | tr '\n' ' ')
fi

repaired=0
all_svc="prometheus grafana filebrowser aria2 exporter rclone ariang"

for svc in $all_svc; do
  f="$STATE/$svc"
  case " $failed " in
    *" $svc "*)
      n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 ))
      echo "$n" > "$f"
      [ "$n" -ge "$THRESHOLD" ] || continue
      ts=$(date +%Y%m%d_%H%M%S)
      case "$svc" in
        prometheus)
          # WAL 损坏是最常见的；整个 data 目录移走，Prometheus 会建新的
          [ -d ~/prom/data ] && mv ~/prom/data "$QUAR/prom_data_$ts" && \
            log "prometheus 连续失败 $n 次 → TSDB 已隔离到 quarantine/prom_data_$ts（历史数据丢失，配置不动）"
          ;;
        grafana)
          # ⚑ 看板与数据源来自 provisioning，admin 按 grafana.ini 重建 ——
          #   所以丢的只有用户偏好和告警静默记录
          [ -f ~/grafana/data/grafana.db ] && mv ~/grafana/data/grafana.db "$QUAR/grafana_db_$ts" && \
            log "grafana 连续失败 $n 次 → sqlite 已隔离（看板由 provisioning 恢复）"
          ;;
        filebrowser)
          [ -f ~/fb/filebrowser.db ] && mv ~/fb/filebrowser.db "$QUAR/fb_db_$ts" && {
            log "filebrowser 连续失败 $n 次 → bolt 已隔离，正在重建"
            cd ~/fb || true
            ./filebrowser config init --database ~/fb/filebrowser.db >/dev/null 2>&1
            ./filebrowser config set --database ~/fb/filebrowser.db \
              --root ~/nas --address 127.0.0.1 --port 8081 --locale zh-cn >/dev/null 2>&1
            pw=$(cat ~/fb/ADMIN_PASSWORD.txt 2>/dev/null)
            [ -n "$pw" ] && ./filebrowser users add admin "$pw" --perm.admin \
              --database ~/fb/filebrowser.db >/dev/null 2>&1
            log "filebrowser 已用保存的密码重建"
          }
          ;;
        aria2)
          # session 文件损坏会让 aria2 拒绝启动（input-file 指向坏文件）
          [ -f ~/.aria2/session ] && mv ~/.aria2/session "$QUAR/aria2_session_$ts" && {
            : > ~/.aria2/session
            log "aria2 连续失败 $n 次 → session 已隔离并重置（下载队列丢失）"
          }
          ;;
        *)
          log "$svc 连续失败 $n 次 —— 没有对应的修复动作，需人工介入"
          ;;
      esac
      echo 0 > "$f"          # 重建后计数归零，给它一次重新尝试的机会
      repaired=$((repaired + 1))
      ;;
    *)
      # 这一轮它是好的 → 连续计数清零
      [ -f "$f" ] && echo 0 > "$f"
      ;;
  esac
done

# ⚑ 隔离目录只留最近 3 份。否则反复损坏会把磁盘填满 ——
#   那正是 diskguard 要防的事，别自己制造它。
ls -1dt "$QUAR"/* 2>/dev/null | tail -n +4 | while read -r old; do
  rm -rf "$old" && log "清理旧隔离数据 $(basename "$old")"
done

# 给 exporter 读
pend=0
for f in "$STATE"/*; do
  [ -f "$f" ] && pend=$(( pend + $(cat "$f" 2>/dev/null || echo 0) ))
done
printf '{"repaired_this_round":%d,"pending_failures":%d,"quarantined":%d,"checked":%d}\n' \
  "$repaired" "$pend" "$(ls -1 "$QUAR" 2>/dev/null | wc -l)" "$(date +%s)" \
  > ~/selfrepair_stats.json

# ⚑ -v 要在任意位置都能识别：$1 是服务名列表，不能只查 $1
case " $* " in *" -v "*) echo "  失败中: [${failed:-无}]  本轮修复 $repaired  累计待观察 $pend" ;; esac
exit 0
