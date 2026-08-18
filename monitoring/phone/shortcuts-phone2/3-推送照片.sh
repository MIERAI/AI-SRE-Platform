#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null
echo "正在推送新照片到手机1…"
~/photopush.sh
echo
read -n 1 -s -r -p "按任意键关闭"
