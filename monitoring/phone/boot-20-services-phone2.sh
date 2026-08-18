#!/data/data/com.termux/files/usr/bin/sh
# 手机2 开机自启：sshd + 到手机1 的隧道，并重新注册定时任务。
# ⚑ 掉电关机是这台设备的常态（随身携带），所以开机恢复必须是全自动的。
termux-wake-lock
sleep 10                       # 等网络就绪，否则隧道会连不上
~/services.sh start
bash ~/tunwatch.sh             # 内部会重新注册 JobScheduler
