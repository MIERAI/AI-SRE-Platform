#!/data/data/com.termux/files/usr/bin/bash
# 一键关闭服务。   用法：  ~/stop.sh        （问一次再动手）
#                        ~/stop.sh -y     （不问，直接关）
#                        ~/stop.sh --all  （连自愈一起停，不会自动恢复）
#
# ⚑ 【始终保留 sshd】。services.sh stop 默认就跳过它 ——
#   停掉的话远程再也连不上，只能等回家。
#
# ⚑ 默认不停自愈任务。所以「关闭」的实际效果是【暂停最多 15 分钟】，
#   watchdog 到点会把服务全部拉回来。想彻底停要加 --all。
#   这两种后果完全不同，所以分成两个开关而不是一个。

set -u
YES=0; ALSO_WATCHDOG=0
for a in "$@"; do
  case "$a" in
    -y|--yes) YES=1 ;;
    --all)    ALSO_WATCHDOG=1; YES=1 ;;
  esac
done

case "$(whoami)" in
  u0_a506) DEV="手机1（家里的服务器）" ;;
  u0_a371) DEV="手机2（随身）" ;;
  *)       DEV="本机" ;;
esac

if [ "$YES" = "0" ]; then
  echo "即将关闭 $DEV 的服务（sshd 会保留）"
  [ "$ALSO_WATCHDOG" = "1" ] && echo "并且会停掉自愈任务 —— 服务不会自动恢复" \
                             || echo "自愈任务保留 —— 服务将在 15 分钟内自动恢复"
  read -n 1 -r -p "继续？(y/N) " r; echo
  case "$r" in y|Y) ;; *) echo "已取消"; exit 0 ;; esac
fi

~/services.sh stop

if [ "$ALSO_WATCHDOG" = "1" ]; then
  # ⚑ 取消后服务不会自己回来，必须手动 ~/services.sh start
  timeout 15 termux-job-scheduler --cancel-all >/dev/null 2>&1
  echo
  echo "✅ 已彻底关闭，不会自动恢复。"
  echo "   恢复：~/services.sh start  然后重新注册自愈任务"
else
  echo
  echo "✅ 已关闭。自愈任务仍在，15 分钟内服务会自动回来。"
  echo "   想立刻恢复：~/services.sh start"
fi
