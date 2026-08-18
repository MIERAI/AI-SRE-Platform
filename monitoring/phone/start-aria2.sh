#!/data/data/com.termux/files/usr/bin/bash
# 启动 aria2 下载器 + AriaNg 网页界面。幂等。
#
# ⚑ session 文件必须先存在，否则 aria2 会因为 input-file 指向不存在的路径
#   而【拒绝启动】。这不是降级运行 —— 进程直接退出，而 watchdog 只会
#   一遍遍重试，日志里堆满「已重启」却始终起不来。
#
# ⚑ AriaNg 是纯静态单文件，但必须用 http:// 打开，不能 file://：
#   从 file:// 发起的 RPC 请求会被浏览器的同源策略挡掉。
#   所以配一个只绑本地的极简静态服务器。

set -u
A2="$HOME/.aria2"
UI="$HOME/.aria2/ui"

start_aria2() {
  [ -f "$HOME/aria2.pid" ] && kill -0 "$(cat "$HOME/aria2.pid")" 2>/dev/null && return 0
  mkdir -p "$A2" "$HOME/nas/downloads"
  touch "$A2/session"                      # 见上方说明
  nohup aria2c --conf-path="$A2/aria2.conf" >"$A2/stdout.log" 2>&1 &
  echo $! > "$HOME/aria2.pid"
}

start_ui() {
  [ -f "$HOME/ariang.pid" ] && kill -0 "$(cat "$HOME/ariang.pid")" 2>/dev/null && return 0
  [ -d "$UI" ] || return 0
  cd "$UI" || return 0
  nohup python -m http.server 6801 --bind 127.0.0.1 >"$A2/ui.log" 2>&1 &
  echo $! > "$HOME/ariang.pid"
}

start_aria2
start_ui
