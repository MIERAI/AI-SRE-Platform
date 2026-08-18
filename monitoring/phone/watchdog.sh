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

termux-wake-lock 2>/dev/null

# ── 拉起掉线的服务 ──────────────────────────────────────────
~/services.sh start 2>&1 | while IFS= read -r line; do
  case "$line" in
    *已启动*|*启动失败*) log "${line# }" ;;
  esac
done

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
