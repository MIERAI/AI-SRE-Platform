#!/data/data/com.termux/files/usr/bin/bash
# 启动手机1 上的 File Browser（NAS 的 Web 文件管理界面）。幂等。
#
# ⚑ 绑 127.0.0.1 而不是 0.0.0.0 —— 与 Grafana 的取舍刻意不同。
#   Grafana 泄露的是温度和电量；这东西能【读写全部文件】。
#   访问路径本来就是 SSH 隧道（手机2 的 tun.sh、Mac 的 -L），
#   绑本地不影响使用，却把家里 WiFi 上的其他设备挡在外面。
#
# ⚑ --database 必须显式给。不给的话 filebrowser 会在【当前工作目录】
#   找 filebrowser.db；watchdog 由 JobScheduler 触发、工作目录不确定，
#   会导致它悄悄建一个空数据库 —— 登录失败，但进程活得好好的。

set -u
FB_DIR="$HOME/fb"
PIDFILE="$HOME/fb.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi

cd "$FB_DIR" || exit 1
nohup ./filebrowser --database "$FB_DIR/filebrowser.db" \
  >"$FB_DIR/stdout.log" 2>&1 &

echo $! > "$PIDFILE"
