#!/data/data/com.termux/files/usr/bin/bash
# 手机2 的自愈。由 Android JobScheduler 每 15 分钟调用。
#
# ⚑ 这一版把 `tun.sh start` 换成了 `services.sh start`。原因是真实事故：
#   旧版只检查隧道，不管 sshd。某次 Android 杀掉 Termux 后，
#   JobScheduler 照常唤醒本脚本、隧道也修好了，但【sshd 永远没回来】——
#   而 sshd 才是唯一的入口。表现为 ping 通、8022 拒绝连接，远程彻底失联。
#   手机1 的 watchdog 一直调 services.sh start（覆盖 sshd），
#   两台的自愈逻辑不一致才留下了这个洞。
#
# ⚑ Tailscale 不在此脚本能力范围内。它是安卓 App，Termux 管不到。
#   同一次事故里它也断了，且不会自己回来 —— 那个只能靠系统设置里的
#   「始终开启的 VPN」。这里只能【检测并记录】，修不了。

export PATH=/data/data/com.termux/files/usr/bin:$PATH
LOG=~/tunwatch.log
log(){ echo "$(date '+%F %T') $*" >> $LOG; }

termux-wake-lock 2>/dev/null

# ── 拉起掉线的服务（sshd + 隧道）──────────────────────────
~/services.sh start 2>&1 | while IFS= read -r line; do
  case "$line" in
    *已启动*|*启动失败*) log "${line# }" ;;
  esac
done

# ── Tailscale 探测。修不了，但要留下证据 ────────────────────
if ! timeout 8 curl -s -o /dev/null -m 6 http://100.80.225.15:9101/metrics 2>/dev/null; then
  log "Tailscale 不通 —— 服务可能都正常，但连不到手机1（需人工打开 App）"
fi

# ── 照片推送 ────────────────────────────────────────────────
# 想省流量时改成： ~/photopush.sh --wifi-only
[ -x ~/photopush.sh ] && ~/photopush.sh >/dev/null 2>&1

# ── 重新注册定时任务 ────────────────────────────────────────
# ⚑ 实测过：系统没重启，任务却被 App Standby 悄悄移除了。
timeout 15 termux-job-scheduler --pending 2>/dev/null | grep -q tunwatch || \
  timeout 15 termux-job-scheduler --script ~/tunwatch.sh \
    --period-ms 900000 --persisted true >/dev/null 2>&1
