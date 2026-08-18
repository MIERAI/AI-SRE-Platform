# ⚑ 打开 Termux 就自动拉起服务。
#
#   起因是一次真实事故：Android 强杀 Termux 后，JobScheduler 注册的自愈任务
#   被【一起取消】，等了 30 分钟也不会恢复。唯一的救法是有人打开 Termux App ——
#   但光打开什么都不会起，还得手动敲命令。
#   而需要托人去房间的时候，对方只会点图标，不会敲命令。
#
# ⚑ 必须用 [[ $- == *i* ]] 把门关住。bash 被 sshd 以【非交互】方式调用时
#   也会 source .bashrc（$- = hBc，没有 i）—— 不加判断的话，
#   每条 `ssh host 'cmd'` 都会触发一次服务检查，慢且吵。
#
# ⚑ 判活只看一个 PID 文件，不跑完整 status。后者要发 8 次 HTTP，
#   开个终端等好几秒不可接受。

if [[ $- == *i* ]]; then
  if ! { [ -f "$HOME/prom.pid" ] && kill -0 "$(cat "$HOME/prom.pid" 2>/dev/null)" 2>/dev/null; }; then
    echo ""
    echo "  ⚠ 检测到服务未运行，正在自动启动…"
    echo ""
    "$HOME/services.sh" start
    # 自愈任务也可能被一起取消了，重新注册一次（幂等）
    timeout 15 termux-job-scheduler --pending 2>/dev/null | grep -q watchdog || \
      timeout 15 termux-job-scheduler --script "$HOME/watchdog.sh" \
        --period-ms 900000 --persisted true >/dev/null 2>&1
    echo ""
    echo "  ✅ 完成。可以关掉这个窗口了。"
    echo ""
  fi
fi
