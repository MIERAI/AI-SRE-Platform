#!/data/data/com.termux/files/usr/bin/sh
# 开机自启。⚑ 只调 watchdog.sh 一处 —— 它内部委托 services.sh 启动全部服务。
date '+%F %T boot-20-services started' >> "$HOME/boot_trace.log"
termux-wake-lock
sleep 10                      # 等网络和存储挂载就绪
bash ~/watchdog.sh
date '+%F %T boot-20-services finished' >> "$HOME/boot_trace.log"
