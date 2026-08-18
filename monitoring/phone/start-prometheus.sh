#!/data/data/com.termux/files/usr/bin/bash
# 启动手机1 上的 Prometheus。幂等：已在跑就直接退出。
#
# ⚑ 为什么必须有这个包装脚本，而不是让 watchdog 直接敲命令：
#   prometheus.yml 里的 `rule_files: [rules.yml]` 是**相对路径，而且相对的是
#   进程的工作目录，不是配置文件所在目录**。watchdog 由 JobScheduler 触发，
#   工作目录不确定 —— 直接敲命令会因为找不到 rules.yml 而【拒绝启动】。
#   这里先 cd 到脚本自己所在的目录，把这个坑一次性钉死。
#
# ⚑ 用 PID 文件判断存活，不用 pgrep -f：后者会匹配到调用它的命令行本身。
#   这个错误在本项目里已经犯过四次（rclone / ssh -D / phone_metrics ×2）。

cd "$(dirname "$0")" || exit 1

PIDFILE="$HOME/prom.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi

nohup ./prometheus \
  --config.file=prometheus.yml \
  --storage.tsdb.path=data \
  --storage.tsdb.retention.time=120d \
  --web.listen-address=0.0.0.0:9090 \
  --web.enable-lifecycle \
  >prometheus.log 2>&1 &

echo $! > "$PIDFILE"
