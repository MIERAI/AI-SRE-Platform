#!/data/data/com.termux/files/usr/bin/python
"""博客访问指标 exporter。数 Caddy 的 JSON 日志,暴露 Prometheus 格式。
监听 9102(exporter 用的 9101,错开)。由 watchdog 拉起。

⚑ 为什么单独一个 exporter,不塞进 phone_metrics.py:
  博客日志可能几 MB,每次全量解析有开销;而且它是独立关注点(网站 vs 设备)。
  Prometheus 分两个 job 抓,互不拖累。

⚑ 指标设计:累计计数器(counter)+ 标签,让 Grafana 能算 rate(每分钟访问量)、
  按国家/页面/状态码切。counter 只增不减,重启会归零 —— Prometheus 的
  increase()/rate() 能正确处理重置。
"""
import http.server, json, os, collections

LOG = os.path.expanduser('~/blog_access.jsonl')

def collect():
    total = 0
    by_country = collections.Counter()
    by_status = collections.Counter()
    by_page = collections.Counter()
    uniq_ips = set()
    try:
        for line in open(LOG):
            try:
                d = json.loads(line)
                r = d.get('request', {})
                ip = r.get('client_ip', '')
                if ip == '127.0.0.1' or not ip:
                    continue  # 跳过本地健康检查,只统计真实访客
                uri = r.get('uri', '')
                # 只统计页面访问,不含静态资源
                if any(x in uri for x in ('.woff', 'favicon', '/_astro/', '.css', '.js', '.svg', '.xml')):
                    continue
                total += 1
                uniq_ips.add(ip)
                hdrs = r.get('headers', {})
                cc = hdrs.get('Cf-Ipcountry', ['??'])
                by_country[cc[0] if isinstance(cc, list) else cc] += 1
                by_status[str(d.get('status', 0))] += 1
                by_page[uri[:80]] += 1
            except Exception:
                pass
    except FileNotFoundError:
        pass

    L = []
    L.append('# HELP blog_requests_total 博客真实访客的页面请求总数')
    L.append('# TYPE blog_requests_total counter')
    L.append(f'blog_requests_total {total}')
    L.append('# HELP blog_unique_visitors 独立访客数(去重IP)')
    L.append('# TYPE blog_unique_visitors gauge')
    L.append(f'blog_unique_visitors {len(uniq_ips)}')
    L.append('# HELP blog_requests_by_country 按国家的请求数')
    L.append('# TYPE blog_requests_by_country counter')
    for c, n in by_country.items():
        cc = c.replace('\\', '').replace('"', '')
        L.append(f'blog_requests_by_country{{country="{cc}"}} {n}')
    L.append('# TYPE blog_requests_by_status counter')
    for s, n in by_status.items():
        L.append(f'blog_requests_by_status{{status="{s}"}} {n}')
    L.append('# HELP blog_page_views 各页面浏览数')
    L.append('# TYPE blog_page_views counter')
    for p, n in by_page.most_common(20):
        pp = p.replace('\\', '').replace('"', '')
        L.append(f'blog_page_views{{page="{pp}"}} {n}')
    return '\n'.join(L) + '\n'

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip('/') in ('/metrics', ''):
            body = collect().encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass

if __name__ == '__main__':
    http.server.HTTPServer(('127.0.0.1', 9102), H).serve_forever()
