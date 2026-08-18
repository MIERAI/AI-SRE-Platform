#!/data/data/com.termux/files/usr/bin/bash
# 手机上所有常驻服务的统一启停。两台设备共用这一个脚本，按 whoami 区分。
#
#     ~/services.sh start            启动所有未运行的（幂等，可反复跑）
#     ~/services.sh stop             停止所有【除 sshd 外】的服务
#     ~/services.sh stop --all       连 sshd 一起停 —— 远程执行会失去连接
#     ~/services.sh restart          先停后起
#     ~/services.sh status           逐个检查：进程 + 端口 + HTTP 是否真在服务
#     ~/services.sh start grafana    只操作指定的服务
#
# ⚑ **stop 默认保留 sshd**，这不是疏忽。这台设备唯一的入口就是 sshd，
#   人在外地时一旦把它停掉，就只能等回家才能恢复 —— 没有任何补救手段
#   （路由器没有端口转发，Tailscale 也要靠 Termux 里的进程）。
#
# ⚑ **status 不满足于「进程在」**。今天踩过太多次「进程活着但没在服务」：
#   Grafana 少了 --homepath 会端口通、页面全白；rsync 接收端 chdir 失败但
#   退出码看起来正常。所以 status 对每个 HTTP 服务都实际发一次请求。
#
# ⚑ 密码从 ~/.services.env 读，不写在脚本里 —— 这个文件在公开仓库里。
#   设备上需要有：
#       RCLONE_USER=nas
#       RCLONE_PASS=...
#
# ⚑ Transmission 已移除：它只能下 BT，而 aria2 覆盖了它的全部功能，
#   两个 BT 客户端共管同一个下载目录迟早会打架。移除时种子数为 0。

set -u
ENV_FILE="$HOME/.services.env"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

RCLONE_USER="${RCLONE_USER:-nas}"
RCLONE_PASS="${RCLONE_PASS:-}"

case "$(whoami)" in
  u0_a506) DEVICE=phone1; ALL_SVC="sshd rclone aria2 ariang exporter prometheus grafana filebrowser" ;;
  u0_a371) DEVICE=phone2; ALL_SVC="sshd tunnel" ;;
  *)       DEVICE=unknown; ALL_SVC="sshd" ;;
esac

pid_of() {   # 从 PID 文件取活着的进程号，否则空
  local f="$1"
  [ -f "$f" ] || return 1
  local p; p=$(cat "$f" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo "$p"
}

is_up() {
  case "$1" in
    sshd)         pgrep -x sshd >/dev/null ;;
    rclone)       pgrep -x rclone >/dev/null ;;
    exporter)     pid_of "$HOME/exporter.pid" >/dev/null ;;
    prometheus)   pid_of "$HOME/prom.pid" >/dev/null ;;
    grafana)      pid_of "$HOME/grafana.pid" >/dev/null ;;
    filebrowser)  pid_of "$HOME/fb.pid" >/dev/null ;;
    aria2)        pid_of "$HOME/aria2.pid" >/dev/null ;;
    ariang)       pid_of "$HOME/ariang.pid" >/dev/null ;;
    tunnel)       [ "$(bash "$HOME/tun.sh" status 2>/dev/null)" = "up" ] ;;
    *) return 1 ;;
  esac
}

svc_pid() {
  case "$1" in
    sshd)         pgrep -x sshd | head -1 ;;
    rclone)       pgrep -x rclone | head -1 ;;
    exporter)     pid_of "$HOME/exporter.pid" ;;
    prometheus)   pid_of "$HOME/prom.pid" ;;
    grafana)      pid_of "$HOME/grafana.pid" ;;
    filebrowser)  pid_of "$HOME/fb.pid" ;;
    aria2)        pid_of "$HOME/aria2.pid" ;;
    ariang)       pid_of "$HOME/ariang.pid" ;;
    tunnel)       pid_of "$HOME/tun.pid" ;;
  esac
}

# 端口与「健康」的期望状态码。401 也算健康 —— 说明服务在，只是要认证。
svc_port() {
  case "$1" in
    sshd) echo 8022 ;; rclone) echo 8080 ;;
    exporter) echo 9101 ;; prometheus) echo 9090 ;; grafana) echo 3000 ;;
    filebrowser) echo 8081 ;; tunnel) echo 3000 ;;
    aria2) echo 6800 ;; ariang) echo 6801 ;;
  esac
}

start_one() {
  is_up "$1" && { echo "  · $1 已在运行"; return 0; }
  case "$1" in
    sshd)         sshd ;;
    rclone)       nohup rclone serve webdav "$HOME/nas" --addr 127.0.0.1:8080 \
                    --user "$RCLONE_USER" --pass "$RCLONE_PASS" >"$HOME/rclone.log" 2>&1 & ;;
    exporter)     nohup python "$HOME/phone_metrics.py" >"$HOME/exporter.log" 2>&1 &
                  echo $! > "$HOME/exporter.pid" ;;
    prometheus)   "$HOME/prom/start-prometheus.sh" ;;
    grafana)      "$HOME/grafana/start-grafana.sh" ;;
    filebrowser)  "$HOME/fb/start-filebrowser.sh" ;;
    aria2|ariang) "$HOME/start-aria2.sh" ;;
    tunnel)       bash "$HOME/tun.sh" start >/dev/null ;;
  esac
  sleep 1
  is_up "$1" && echo "  ✓ $1 已启动" || echo "  ✗ $1 启动失败"
}

stop_one() {
  is_up "$1" || { echo "  · $1 本来就没在跑"; return 0; }
  case "$1" in
    sshd)         pkill -x sshd ;;
    rclone)       pkill -x rclone ;;
    tunnel)       bash "$HOME/tun.sh" stop >/dev/null ;;
    *)            # 走 PID 文件的服务
                  local f
                  case "$1" in
                    exporter) f="$HOME/exporter.pid" ;; prometheus) f="$HOME/prom.pid" ;;
                    grafana)  f="$HOME/grafana.pid"  ;; filebrowser) f="$HOME/fb.pid" ;;
                    aria2)    f="$HOME/aria2.pid"    ;; ariang)      f="$HOME/ariang.pid" ;;
                  esac
                  local p; p=$(cat "$f" 2>/dev/null)
                  [ -n "$p" ] && kill "$p" 2>/dev/null
                  rm -f "$f" ;;
  esac
  sleep 1
  is_up "$1" && echo "  ✗ $1 仍在运行" || echo "  ✓ $1 已停止"
}

status_all() {
  printf "  %-13s %-8s %-7s %-6s %s\n" 服务 PID 内存 端口 HTTP
  printf "  %-13s %-8s %-7s %-6s %s\n" ───── ──── ──── ──── ────
  for s in $ALL_SVC; do
    local p rss port code
    p=$(svc_pid "$s" 2>/dev/null); p=${p:-—}
    rss="—"
    [ "$p" != "—" ] && rss=$(awk '/VmRSS/{printf "%.0fM", $2/1024}' "/proc/$p/status" 2>/dev/null)
    port=$(svc_port "$s")
    if [ "$s" = "sshd" ]; then
      code=$(is_up "$s" && echo "监听" || echo "—")
    elif [ "$s" = "aria2" ]; then
      # ⚑ aria2 的 RPC 端口对普通 GET 返回 400，光看状态码分不出
      #   「服务正常」和「服务坏了」。所以发一次真的 JSON-RPC 调用。
      local sec ver
      sec=$(cat "$HOME/.aria2/RPC_SECRET.txt" 2>/dev/null)
      ver=$(timeout 8 curl -s -m 6 "http://127.0.0.1:$port/jsonrpc" \
              -H "Content-Type: application/json" \
              -d "{\"jsonrpc\":\"2.0\",\"id\":\"h\",\"method\":\"aria2.getVersion\",\"params\":[\"token:$sec\"]}" \
              2>/dev/null | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
      [ -n "$ver" ] && code="RPC v$ver ✓" || code="RPC ✗ 无应答"
    else
      code=$(timeout 8 curl -s -o /dev/null -m 6 -w "%{http_code}" "http://127.0.0.1:$port/" 2>/dev/null)
      case "$code" in
        200|302|401) code="$code ✓" ;;
        000|"")      code="000 ✗ 无响应" ;;
        *)           code="$code ?" ;;
      esac
    fi
    printf "  %-13s %-8s %-7s %-6s %s\n" "$s" "$p" "${rss:-—}" "$port" "$code"
  done
}

CMD="${1:-status}"; shift 2>/dev/null || true
INCLUDE_SSHD=0
TARGETS=""
for a in "$@"; do
  case "$a" in
    --all) INCLUDE_SSHD=1 ;;
    -*) ;;
    *) TARGETS="$TARGETS $a" ;;
  esac
done
[ -z "$TARGETS" ] && TARGETS="$ALL_SVC"

case "$CMD" in
  start)
    echo "启动 $DEVICE 的服务："
    for s in $TARGETS; do start_one "$s"; done ;;
  stop)
    echo "停止 $DEVICE 的服务："
    for s in $TARGETS; do
      if [ "$s" = "sshd" ] && [ "$INCLUDE_SSHD" = "0" ]; then
        echo "  · sshd 已跳过（停掉就再也连不上了；确要停请加 --all）"
        continue
      fi
      stop_one "$s"
    done ;;
  restart)
    "$0" stop $TARGETS; echo; "$0" start $TARGETS ;;
  status)
    echo "$DEVICE 服务状态："
    status_all ;;
  *)
    echo "用法: $0 {start|stop|restart|status} [--all] [服务名...]"
    echo "可用服务: $ALL_SVC"
    exit 1 ;;
esac
