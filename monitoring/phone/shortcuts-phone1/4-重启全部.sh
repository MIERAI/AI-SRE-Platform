#!/data/data/com.termux/files/usr/bin/bash
# ⚑ stop 默认保留 sshd —— 否则远程就再也连不上了
termux-wake-lock 2>/dev/null
~/services.sh restart
echo
read -n 1 -s -r -p "按任意键关闭"
