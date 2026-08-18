#!/data/data/com.termux/files/usr/bin/bash
~/services.sh status
echo
echo "磁盘剩余 $(df -h ~ | tail -1 | awk '{print $4}') · 照片 $(find ~/nas/photos -type f -not -path '*.thumbs*' | wc -l) 张"
echo "watchdog 上次运行 $(( $(date +%s) - $(python -c "import json,os;print(json.load(open(os.path.expanduser('~/diskguard_stats.json')))['checked'])" 2>/dev/null || echo 0) )) 秒前"
echo
read -n 1 -s -r -p "按任意键关闭"
