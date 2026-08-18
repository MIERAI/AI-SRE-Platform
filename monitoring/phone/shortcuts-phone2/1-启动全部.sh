#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null
echo "正在启动手机2 的服务…"
echo
~/services.sh start
echo
timeout 15 termux-job-scheduler --pending 2>/dev/null | grep -q tunwatch || {
  timeout 15 termux-job-scheduler --script ~/tunwatch.sh --period-ms 900000 --persisted true >/dev/null 2>&1
  echo "已重新注册 15 分钟自愈任务"; }
echo "──────── 结果 ────────"
~/services.sh status
echo
# ⚑ Tailscale 是安卓 App，不归 Termux 管。它断了的话服务全好也连不上手机1，
#   所以这里必须单独探测，并且明确告诉人该去开哪个 App。
if timeout 8 curl -s -o /dev/null -m 6 http://100.80.225.15:9101/metrics 2>/dev/null; then
  echo "✅ Tailscale 正常，能连到手机1"
else
  echo "❌ 连不到手机1 —— 请打开 Tailscale App 检查是否已连接"
fi
echo
read -n 1 -s -r -p "按任意键关闭"
