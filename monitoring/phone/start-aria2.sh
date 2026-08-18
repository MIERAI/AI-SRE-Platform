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
  # ⚑ 必须用 aria2 自带的 --daemon，不能用 nohup ... &。
  #   实测：nohup 启动的 aria2 在终端会话关闭时会【优雅退出】，
  #   日志里留下 "Download Results:" 的退出摘要。nohup 只是让进程忽略
  #   SIGHUP 的默认动作，而 aria2 自己把 SIGHUP 当成关机信号来处理。
  #   同样方式启动的 rclone/prometheus/grafana/filebrowser 都活着 ——
  #   这是 aria2 特有的行为，不是 nohup 失效。
  #
  #   发作场景很具体：有人点开 Termux（.bashrc 钩子拉起服务）→ 关掉窗口
  #   → aria2 死掉，而 PID 文件还在，status 看起来一切正常。
  #
  #   --daemon 会 fork 后父进程退出，所以 $! 拿到的是错的 PID，
  #   改用 pgrep -x（精确名匹配，命令行里不含 aria2c 字样，无自匹配风险）。
  aria2c --conf-path="$A2/aria2.conf" --daemon=true >>"$A2/stdout.log" 2>&1
  sleep 1
  pgrep -x aria2c | head -1 > "$HOME/aria2.pid"
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
