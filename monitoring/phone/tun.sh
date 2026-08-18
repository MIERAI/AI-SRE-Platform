#!/data/data/com.termux/files/usr/bin/bash
# 手机2 上的隧道管理。用 PID 文件而非 pgrep -f —— 后者会匹配到调用者自己的命令行。
#
# ⚑ 为什么监控面板要走隧道，而不是直接开 http://100.80.225.15:3000：
#   实测手机2 的 Termux 里 curl 那个地址完全正常（200 / 58KB），
#   但同一台手机的浏览器打不开，而 http://127.0.0.1:8080 却能开。
#   也就是说系统层的 Tailscale 是通的，卡在浏览器这个 App 上。
#   与其继续追查是哪个浏览器设置/ROM 限制，不如用【已被证明可用】的路径：
#   把远端端口映射成本地端口，浏览器只访问 127.0.0.1。
#
#   代价：隧道断了页面就打不开（tunwatch.sh 负责重连）。
#   好处：不依赖浏览器怎么处理 100.64/10 这段地址。

PIDF=~/tun.pid
case "$1" in
 start)
   [ -f $PIDF ] && kill -0 $(cat $PIDF) 2>/dev/null && { echo already-running; exit 0; }
   ssh -f -N -D 1080 \
       -L 8080:127.0.0.1:8080 \
       -L 3000:127.0.0.1:3000 \
       -L 9090:127.0.0.1:9090 \
       -L 9101:127.0.0.1:9101 \
       -L 8081:127.0.0.1:8081 \
       -L 6800:127.0.0.1:6800 \
       -L 6801:127.0.0.1:6801 \
       -p 8022 -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new \
       -o ConnectTimeout=25 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
       u0_a506@100.80.225.15 && \
   sleep 2 && ps -eo pid,args | grep '[-]D 1080' | awk '{print $1}' | head -1 > $PIDF
   echo started pid=$(cat $PIDF 2>/dev/null) ;;
 stop) [ -f $PIDF ] && kill $(cat $PIDF) 2>/dev/null; rm -f $PIDF; echo stopped ;;
 status) [ -f $PIDF ] && kill -0 $(cat $PIDF) 2>/dev/null && echo up || echo down ;;
esac
