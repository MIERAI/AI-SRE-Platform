#!/data/data/com.termux/files/usr/bin/sh
# ⚑ 编号 10 = 第一个执行，而且【不 sleep、不依赖网络】。
#   sshd 是这台设备唯一的入口：后面任何脚本卡住，只要它起来了就还能远程救。
#   反过来如果它排在需要联网的脚本后面，那些脚本一卡，人就彻底进不来了。
termux-wake-lock
sshd
