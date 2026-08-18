#!/data/data/com.termux/files/usr/bin/python
"""手机1 自身的指标采集器 —— 在设备上本地跑，暴露 Prometheus 格式。

### 为什么在设备上跑，而不是从 Mac 远程采

Phase 6 的 deployment/phone_exporter.py 是从 Mac 经 SSH 采的，
但 Mac 要被带走两个月。本地跑才能覆盖「没人管的时候」——
而那恰恰是最需要数据的时段（实测：一夜被系统杀了 4 次）。

### 采什么、为什么

    温度        82 个 thermal zone 里挑有效的 —— 验证「被杀是否与发热相关」
    CPU 频率    实测 cpu0 只有 556MHz，深度节能状态本身就是被杀的线索
    电池        温度/电量/充电状态 —— Phase 6 里 TPOT 的 ×1.22 漂移当时只能猜是热节流
    内存        MemAvailable 下降 → Android 更激进回收
    服务存活    sshd/rclone/aria2c 是否在

### 采不到的（Android 权限限制，不是没写）

    /proc/stat      Permission denied → CPU 使用率
    /proc/net/dev   无输出            → 网络流量

⚑ 温度必须过滤：82 个 zone 里混着 -273°C（绝对零度）和 -40°C 这类无效值。
  不过滤的话 Grafana 的 Y 轴会被压扁，真实温度变化全挤成一条直线。
"""
import http.server, os, glob, subprocess, json, time

def read(p, d=None):
    try:
        with open(p) as f: return f.read().strip()
    except Exception: return d

def temps():
    out = []
    for z in glob.glob('/sys/class/thermal/thermal_zone*'):
        t = read(f'{z}/type'); v = read(f'{z}/temp')
        if not t or not v: continue
        try: c = int(v) / 1000.0
        except ValueError: continue
        # ⚑ 过滤无效值：-273 是绝对零度占位，>150 是失效读数
        # ⚑ 有些 zone 的单位根本不是摄氏度：vbat 是电压(3.3V)、
        #   pm8350b_*_lvl* 是电源管理告警等级(0 / 0.2)。混进温度指标会让
        #   「温度过低」这类告警长期误触发，也会压扁图表 Y 轴。按名字排除。
        if any(k in t.lower() for k in ('vbat', '_lvl', 'ibat', 'bcl', 'vph', 'volt')):
            continue
        if 0 < c < 150:
            out.append((t.replace('-', '_').replace('.', '_'), c))
    return out

def battery():
    try:
        r = subprocess.run(['termux-battery-status'], capture_output=True,
                           text=True, timeout=12)
        return json.loads(r.stdout)
    except Exception: return {}

def collect():
    L = []
    A = L.append
    A('# HELP phone_thermal_celsius 各 thermal zone 温度（已过滤无效值）')
    A('# TYPE phone_thermal_celsius gauge')
    for name, c in temps():
        A(f'phone_thermal_celsius{{zone="{name}"}} {c:.1f}')

    A('# HELP phone_cpu_freq_mhz CPU 当前频率')
    A('# TYPE phone_cpu_freq_mhz gauge')
    for c in sorted(glob.glob('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq')):
        # ⚑ 不能用 c.split('/cpu')[1] 取核号 —— 路径里 '/cpu' 出现三次
        #   （/cpu/、/cpu0、/cpufreq），split 得到 ['...system', '', '0', 'freq/...']，
        #   [1] 是【空字符串】。结果 8 个核塌缩成同一条 {cpu=""} 序列，
        #   而 Prometheus 不报错、up 仍是 1 —— 面板上是一条看着正常的曲线。
        #   这是本项目第 N 次遇到「静默失效比报错危险」。
        n = os.path.basename(os.path.dirname(os.path.dirname(c)))[3:]   # cpu0 -> 0
        f = read(c)
        if n.isdigit() and f and f.isdigit():
            A(f'phone_cpu_freq_mhz{{cpu="{n}"}} {int(f)//1000}')

    b = battery()
    if b:
        A('# TYPE phone_battery_temperature_celsius gauge')
        A(f'phone_battery_temperature_celsius {b.get("temperature",0)}')
        A('# TYPE phone_battery_percentage gauge')
        A(f'phone_battery_percentage {b.get("percentage",0)}')
        A('# TYPE phone_battery_current_ua gauge')
        A(f'phone_battery_current_ua {b.get("current",0)}')
        A('# HELP phone_battery_charging 1=充电中')
        A('# TYPE phone_battery_charging gauge')
        A(f'phone_battery_charging {1 if b.get("status") in ("CHARGING","FULL") else 0}')

    mem = read('/proc/meminfo', '')
    for line in mem.splitlines():
        if line.startswith(('MemTotal', 'MemAvailable')):
            k, v = line.split(':')[0], line.split()[1]
            A(f'# TYPE phone_{k.lower()}_bytes gauge')
            A(f'phone_{k.lower()}_bytes {int(v)*1024}')

    A('# HELP phone_service_up 关键服务是否存活（数据缺口本身也是信号）')
    A('# TYPE phone_service_up gauge')
    # ⚑ 这个列表必须与实际在跑的服务一致。Transmission 移除后忘了改这里，
    #   phone_service_up{service="transmission-daemon"} 会永远是 0，
    #   PhoneServiceDown 永久触发 —— 一条永远红着的告警比没有告警更糟。
    for s in ('sshd', 'rclone', 'aria2c'):
        ok = subprocess.run(['pgrep', '-x', s], capture_output=True).returncode == 0
        A(f'phone_service_up{{service="{s}"}} {1 if ok else 0}')

    try:
        st = os.statvfs(os.path.expanduser('~'))
        A('# TYPE phone_disk_free_bytes gauge')
        A(f'phone_disk_free_bytes {st.f_bavail*st.f_frsize}')
    except Exception: pass

    # ⚑ 被杀次数：从 watchdog.log 累计。这是【唯一】能反映"曾经挂过"的指标 ——
    #   因为进程被杀期间 exporter 自己也停了，那段时间根本没有数据点。
    try:
        n = sum(1 for _ in open(os.path.expanduser('~/watchdog.log')))
        A('# HELP phone_service_restarts_total watchdog 记录的累计重启次数')
        A('# TYPE phone_service_restarts_total counter')
        A(f'phone_service_restarts_total {n}')
    except Exception: pass

    # ⚑ 照片归档的健康度。归档脚本是【定时跑的批处理】，它停掉时没有任何
    #   进程会消失、没有端口会关闭 —— 所有存活类指标都照常绿。
    #   唯一能反映它出事的，是「上次成功运行距今多久」和「inbox 积压了多少」。
    try:
        with open(os.path.expanduser('~/photo_archive_stats.json')) as f:
            ps = json.load(f)
        A('# HELP phone_photo_archive_last_run_timestamp 上次归档完成的时刻')
        A('# TYPE phone_photo_archive_last_run_timestamp gauge')
        A(f'phone_photo_archive_last_run_timestamp {ps.get("last_run", 0)}')
        A('# TYPE phone_photos_total gauge')
        A(f'phone_photos_total {ps.get("total_photos", 0)}')
        A('# TYPE phone_photo_archive_errors gauge')
        A(f'phone_photo_archive_errors {ps.get("errors", 0)}')
    except Exception:
        pass
    # inbox 积压：归档正常时应该接近 0。持续增长 = 归档没在跑。
    try:
        inbox = os.path.expanduser('~/nas/inbox')
        n = sum(len([f for f in fs if not f.startswith('.')])
                for _r, _d, fs in os.walk(inbox))
        A('# HELP phone_photo_inbox_pending inbox 里等待归档的文件数')
        A('# TYPE phone_photo_inbox_pending gauge')
        A(f'phone_photo_inbox_pending {n}')
    except Exception:
        pass

    A('# TYPE phone_scrape_timestamp gauge')
    A(f'phone_scrape_timestamp {int(time.time())}')

    # ⚑ 自查重复序列。起因：cpu 标签取错导致 8 个核塌缩成一条 {cpu=""}，
    #   而 Prometheus 既不报错、up 也仍是 1 —— 面板上是一条看着正常的曲线。
    #   把这类静默失效变成一个【能告警的数字】，比下次再靠肉眼发现强。
    seen, dup = set(), 0
    for ln in L:
        if ln.startswith('#'):
            continue
        key = ln.rsplit(' ', 1)[0]          # 指标名 + 标签，去掉数值
        if key in seen:
            dup += 1
        seen.add(key)
    A('# HELP phone_exporter_duplicate_series 本轮输出里重复的序列数（应恒为 0）')
    A('# TYPE phone_exporter_duplicate_series gauge')
    A(f'phone_exporter_duplicate_series {dup}')
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
    # 绑 0.0.0.0 让 tailnet 内可访问；公网仍不可达（路由器无端口转发）
    http.server.HTTPServer(('0.0.0.0', 9101), H).serve_forever()
