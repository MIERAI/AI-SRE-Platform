#!/data/data/com.termux/files/usr/bin/sh
# 开机自启。⚑ 这里只调 watchdog.sh 一处 —— 它内部委托 services.sh 启动全部服务。
#   原来这里还单独列了 prometheus/grafana/filebrowser 三行，是重复的：
#   同一条启动命令存在多个地方，改参数漏改一处就会跑出两套不同的配置。
termux-wake-lock
sleep 10                      # 等网络和存储挂载就绪
bash ~/watchdog.sh
