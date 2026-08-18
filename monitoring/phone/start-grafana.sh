#!/data/data/com.termux/files/usr/bin/bash
# 启动手机1 上的 Grafana。幂等：已在跑就直接退出。
#
# ⚑ --homepath 不能省。Grafana 的前端资源在 $PREFIX/share/grafana/public，
#   不指过去的话进程能起来、端口也通，但页面全白 —— 一个「看起来活着」的故障。
#
# ⚑ 配置与数据分离：程序在 $PREFIX（pkg 升级会覆盖），
#   配置和 sqlite 在 ~/grafana（升级不动）。混在一起的话一次 pkg upgrade 就没了。

set -u
HOME_DIR="$HOME/grafana"
PIDFILE="$HOME/grafana.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi

cd "$HOME_DIR" || exit 1
nohup grafana server \
  --homepath="$PREFIX/share/grafana" \
  --config="$HOME_DIR/grafana.ini" \
  --packaging=termux \
  >"$HOME_DIR/logs/stdout.log" 2>&1 &

echo $! > "$PIDFILE"
