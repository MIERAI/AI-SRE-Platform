#!/data/data/com.termux/files/usr/bin/bash
~/services.sh status
echo
timeout 8 curl -s -o /dev/null -m 6 http://100.80.225.15:9101/metrics 2>/dev/null \
  && echo "Tailscale → 手机1  ✅ 通" || echo "Tailscale → 手机1  ❌ 不通（去开 Tailscale App）"
echo "已推送照片 $(wc -l < ~/.photopush_sent 2>/dev/null | tr -d ' ') 张"
echo
read -n 1 -s -r -p "按任意键关闭"
