#!/data/data/com.termux/files/usr/bin/sh
# ⚑ 编号 10 = 第一个执行，而且【不 sleep、不依赖网络】。
#   sshd 是这台设备唯一的入口：后面任何脚本卡住，只要它起来了就还能远程救。
#
# ⚑ 第一行先留痕。否则「重启后服务没起来」分不清是
#   Termux:Boot 没触发、还是触发了但脚本失败 —— 两者的修法完全不同。
#   实测过一次重启后全部端口关闭，而当时无法判断是哪种。
date '+%F %T boot-10-sshd executed' >> "$HOME/boot_trace.log"
termux-wake-lock
sshd
date '+%F %T boot-10-sshd finished, sshd rc='$? >> "$HOME/boot_trace.log"
