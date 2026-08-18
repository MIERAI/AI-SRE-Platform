#!/data/data/com.termux/files/usr/bin/bash
# 桌面一键启动。设计成【不懂技术的人也能用】——托人去房间时点这个就行。
termux-wake-lock 2>/dev/null
echo "正在启动手机1 的全部服务…"
echo
~/services.sh start
echo
# 重新注册定时任务：Termux 被杀时它常常一起被移除，persisted 也保不住
timeout 15 termux-job-scheduler --pending 2>/dev/null | grep -q watchdog || {
  timeout 15 termux-job-scheduler --script ~/watchdog.sh --period-ms 900000 --persisted true >/dev/null 2>&1
  echo "已重新注册 15 分钟自愈任务"; }
echo
echo "──────── 结果 ────────"
~/services.sh status
n=$(~/services.sh status | grep -cE "✓|监听")
echo
if [ "$n" -ge 8 ]; then echo "✅ 全部正常（$n/8）"; else echo "⚠️  只有 $n/8 正常，请把这个画面截图发给我"; fi
echo
read -n 1 -s -r -p "按任意键关闭"
