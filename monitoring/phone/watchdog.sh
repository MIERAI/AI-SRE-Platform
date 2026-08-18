#!/data/data/com.termux/files/usr/bin/bash
# NAS 服务自愈。由 Android JobScheduler 每 15 分钟调用一次。
#
# ⚑ 这里【不再重复写各服务的启动命令】。原来每加一个服务就复制一段
#   「判活 + nohup 启动」，涨到七段之后，同一条命令在 watchdog.sh、
#   开机脚本、手工启动三个地方各存一份 —— 改了参数只改一处就会悄悄跑岔。
#   现在统一委托给 services.sh，它是唯一定义「怎么启动」的地方。
#
# ⚑ 只把【真正拉起过】的服务写进日志。services.sh 对已在运行的会输出
#   「· xxx 已在运行」，那不是事件。phone_service_restarts_total 指标
#   直接数这个日志的行数，混进去就没法反映「它到底挂过几次」。

export PATH=/data/data/com.termux/files/usr/bin:$PATH
LOG=~/watchdog.log
log(){ echo "$(date '+%F %T') $*" >> $LOG; }

# ⚑ 留痕。用来区分「谁触发了这次执行」：
#   boot_trace.log 里出现 boot-10-sshd → Termux:Boot 生效
#   只出现 watchdog invoked           → 是 JobScheduler 的持久化任务
#   什么都没有                         → 两条路都没走通
#   实测过一次重启后全部端口关闭，而当时无法判断是哪种情况。
date "+%F %T watchdog invoked" >> ~/boot_trace.log

termux-wake-lock 2>/dev/null

# ── 拉起掉线的服务 ──────────────────────────────────────────
# ⚑ 重启次数记在【独立的单调计数文件】里，不再数 watchdog.log 的行数。
#   原因：日志轮转会让行数归零。increase() 能正确处理计数器重置，
#   但「累计挂过多少次」这个含义会丢 —— 而那是判断设备稳定性的核心数字。
CNT=~/restart_count
[ -f "$CNT" ] || echo 0 > "$CNT"
# ⚑ 用临时文件收集本轮启动失败的服务名，而不是在管道里累加变量 ——
#   `... | while read` 的 while 体跑在子 shell 里，里面改的变量出不来。
FAILED_TMP=~/.watchdog_failed.$$
: > "$FAILED_TMP"
~/services.sh start 2>&1 | while IFS= read -r line; do
  case "$line" in
    *已启动*)
      log "${line# }"
      echo $(( $(cat "$CNT" 2>/dev/null || echo 0) + 1 )) > "$CNT" ;;
    *启动失败*)
      log "${line# }"
      echo "$line" | awk '{print $2}' >> "$FAILED_TMP" ;;
  esac
done
FAILED=$(tr '\n' ' ' < "$FAILED_TMP"); rm -f "$FAILED_TMP"

# ── 连续启动失败 → 隔离损坏数据 ──────────────────────────────
# ⚑ 硬杀之后 Prometheus 的 WAL / Grafana 的 sqlite / filebrowser 的 bolt
#   都可能损坏到【拒绝启动】。那时 watchdog 会每 15 分钟重试一次、
#   日志里一直有记录，人两个月后回来才发现监控从第三天就停了。
[ -x ~/selfrepair.sh ] && ~/selfrepair.sh "$FAILED" >/dev/null 2>&1

# ── 日志轮转 ────────────────────────────────────────────────
# ⚑ 今天见过 378 MB / 3 分钟的失控日志（约 2 MB/s）。
#   按那个速率 638 GB 会在 88 小时内填满，而人要离开两个月。
[ -x ~/logrotate.sh ] && ~/logrotate.sh >/dev/null 2>&1

# ── 磁盘保护 ────────────────────────────────────────────────
# ⚑ 放在拉起服务【之后】：万一 aria2 刚被拉起来，也要立刻受保护约束，
#   否则它会在下一个 15 分钟窗口里毫无限制地下载。
if [ -x ~/diskguard.sh ]; then
  ~/diskguard.sh >/dev/null 2>&1 || log "diskguard 返回错误"
fi

# ── 照片归档（批处理，不是常驻进程，所以无条件跑）──────────
if [ -d ~/nas/inbox ]; then
  python ~/archive_photos.py --quiet >>~/archive.log 2>&1 || log "归档脚本返回错误"
fi

# ── 数据目录统计（给健康面板用）────────────────────────────
[ -x ~/datastats.sh ] && ~/datastats.sh >/dev/null 2>&1

# ── 重新注册定时任务 ────────────────────────────────────────
# ⚑ 实测过：系统没重启，任务却被 App Standby 悄悄移除了。
#   persisted=true 保得住重启，保不住这个。所以每轮自己确认一次。
timeout 15 termux-job-scheduler --pending 2>/dev/null | grep -q watchdog || \
  timeout 15 termux-job-scheduler --script ~/watchdog.sh \
    --period-ms 900000 --persisted true >/dev/null 2>&1
