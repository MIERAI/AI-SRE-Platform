#!/data/data/com.termux/files/usr/bin/bash
# 博客对外服务:静态服务器 + cloudflared 临时隧道。由 watchdog 调用,幂等。
#
# ⚑ 临时隧道(trycloudflare)的地址每次重启都变。所以这个脚本除了拉起服务,
#   还负责【把当前地址抓出来、写到多个你能看到的地方】:
#     ~/blog_url.txt              纯文本,ssh 进来 cat 就看到
#     ~/nas/当前博客地址.txt      File Browser 里能看到
#   地址变了不用我盯着,这些文件自动更新。

set -u
PORT=8090
BLOG=~/nas/blog
HTTP_PID=~/caddy.pid
CF_PID=~/cf.pid
URLFILE=~/blog_url.txt

# ① 静态服务器:Caddy(替代 python http.server,为了记录真实访客IP+国家)
#   ⚑ Caddy 从 Cloudflare 的 CF-Connecting-IP 头还原真实IP,写 JSON 日志,
#     供 DuckDB 分析访问。python http.server 只能看到 127.0.0.1,换不掉。
if ! { [ -f "$HTTP_PID" ] && kill -0 "$(cat "$HTTP_PID")" 2>/dev/null; }; then
  setsid nohup caddy run --config ~/Caddyfile --adapter caddyfile >~/caddy.log 2>&1 &
  echo $! > "$HTTP_PID"
fi

# ② cloudflared 隧道
if ! { [ -f "$CF_PID" ] && kill -0 "$(cat "$CF_PID")" 2>/dev/null; }; then
  setsid nohup cloudflared tunnel --url http://127.0.0.1:$PORT >~/cloudflared.log 2>&1 &
  echo $! > "$CF_PID"
  # 等它拿到新地址(重启后地址会变),最多等 25 秒
  for i in $(seq 1 25); do
    url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/cloudflared.log 2>/dev/null | tail -1)
    [ -n "$url" ] && break
    sleep 1
  done
fi

# ③ 抓当前地址,写到所有你能看到的地方
url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/cloudflared.log 2>/dev/null | tail -1)
if [ -n "$url" ]; then
  old=$(cat "$URLFILE" 2>/dev/null | grep -oE 'https://[^ ]+' | tail -1)
  echo "$url" > "$URLFILE"
  mkdir -p ~/nas
  printf '博客当前地址(会随重启变化):\n%s\n\n更新时间: %s\n' "$url" "$(date '+%F %T')" > ~/nas/当前博客地址.txt
  # 地址变了才记一笔日志(给你事后查"什么时候变的")
  if [ -n "$old" ] && [ "$old" != "$url" ]; then
    echo "$(date '+%F %T') 地址变更: $old → $url" >> ~/blog_url_history.log
  fi
fi

[ "${1:-}" = "-v" ] && echo "  博客地址: ${url:-未取到}"
exit 0
