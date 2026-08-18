"""手机传感器 → Prometheus。**给这个项目补上第一个真实数据源。**

### 为什么需要它

整个项目的告警一直是假的：`agent/v1.py` 里的 `ALERTS` 是我手写的 JSON 常量，
`agent/tools/cluster.py` 第一行就写着「明确是模拟器，不是真集群」。

这有具体的风险，而且 Phase 3 已经实证过一次：
**教程默认值（512-token 分块、段落切分、hybrid 检索、nomic 前缀）在本语料上全错。**
同理，我们关于注入、判别器、净化的全部结论，都建立在我编的 9 个 namespace 上。

手机传感器给出的是**真实的、带噪声的、异常真实发生的**时序数据：

    电池温度   跑模型/充电        缓慢漂移 + 真实的热积累
    光线       开灯/关灯/遮挡      真实的阶跃突变
    加速度     拿起手机/走动       真实的尖峰
    电流       负载变化           与计算强度真实相关

虽然场景不是 K8s，但**"数据是真的"这件事本身**就让异常检测、告警、排查
面对的不再是我设计好让它答对的题。

### 第一个用途不是演示，是补一个旧结论的证据

Phase 6 跨设备实验里，手机1 出现 ×1.22 的 TPOT 漂移，我判断「疑似降频/热节流」——
**但当时没有温度数据，那只是推测。**
现在可以一边压测一边采温度，看衰减与温升是否真的对应。

    # 持续采集并暴露 /metrics（供 Prometheus 抓）
    uv run deployment/phone_exporter.py --host 10.122.94.11 --port 9101

    # 或者一次性采样（调试用）
    uv run deployment/phone_exporter.py --host 10.122.94.11 --once
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

from prometheus_client import Gauge, start_http_server

SSH_USER = "u0_a506"
SSH_PORT = "8022"
SSH_KEY = "~/.ssh/id_ed25519_personal"

# ⚑ 指标命名带 phone_ 前缀，且**不复用 sre_agent_ 命名空间** ——
#   这是外部设备的物理量，混进 Agent 的指标里会让人误以为是被监控系统的属性。
batt_temp = Gauge("phone_battery_temperature_celsius", "电池温度", ["device"])
batt_pct = Gauge("phone_battery_percentage", "电量百分比", ["device"])
batt_current = Gauge("phone_battery_current_microamps", "电流（负=放电）", ["device"])
batt_voltage = Gauge("phone_battery_voltage_millivolts", "电压", ["device"])
light = Gauge("phone_light_lux", "环境光照", ["device"])
accel = Gauge("phone_acceleration_magnitude", "加速度模长（含重力≈9.8）", ["device"])
scrape_ok = Gauge("phone_scrape_success", "本轮采集是否成功", ["device"])
scrape_seconds = Gauge("phone_scrape_duration_seconds", "采集耗时", ["device"])


def sh(host: str, cmd: str, timeout: int = 25) -> str:
    """在手机上执行命令。

    ⚑ `-o BatchMode=yes` 不能省：否则 key 失效时 ssh 会挂在密码提示上，
      而这个进程是后台采集器，没人会看到那个提示 —— 表现为"采集静默停止"。
      这与 Phase 6 那条教训同源：**静默失效比报错危险**。
    """
    r = subprocess.run(
        ["ssh", "-p", SSH_PORT, "-i", SSH_KEY, "-o", "BatchMode=yes",
         "-o", f"ConnectTimeout={min(timeout,15)}", "-o", "StrictHostKeyChecking=accept-new",
         f"{SSH_USER}@{host}", cmd],
        capture_output=True, text=True, timeout=timeout)
    return r.stdout


def read_battery(host: str) -> dict:
    out = sh(host, "timeout 12 termux-battery-status")
    return json.loads(out) if out.strip().startswith("{") else {}


def read_sensor(host: str, name: str, n: int = 1) -> dict:
    """读一次传感器。

    ⚑ termux-sensor 是**流式**的：不给 -n 会一直输出直到被杀。
      必须限定次数，否则 SSH 会话永远不返回（我第一版就是这么挂住的）。
    """
    out = sh(host, f"timeout 15 termux-sensor -s '{name}' -n {n} 2>/dev/null")
    try:
        # 输出可能是多个 JSON 对象拼接，取第一个完整的
        dec = json.JSONDecoder()
        obj, _ = dec.raw_decode(out.strip())
        return obj
    except Exception:      # noqa: BLE001
        return {}


def sample(host: str, device: str, light_name: str | None,
           accel_name: str | None) -> dict:
    t0 = time.perf_counter()
    got = {}
    b = read_battery(host)
    if b:
        batt_temp.labels(device=device).set(b.get("temperature", 0))
        batt_pct.labels(device=device).set(b.get("percentage", 0))
        batt_current.labels(device=device).set(b.get("current", 0))
        batt_voltage.labels(device=device).set(b.get("voltage", 0))
        got.update({"temp": b.get("temperature"), "pct": b.get("percentage"),
                    "current": b.get("current")})
    if light_name:
        s = read_sensor(host, light_name)
        v = next(iter(s.values()), {}).get("values", []) if s else []
        if v:
            light.labels(device=device).set(v[0])
            got["lux"] = v[0]
    if accel_name:
        s = read_sensor(host, accel_name)
        v = next(iter(s.values()), {}).get("values", []) if s else []
        if len(v) >= 3:
            mag = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
            accel.labels(device=device).set(mag)
            got["accel"] = round(mag, 2)
    dt = time.perf_counter() - t0
    scrape_seconds.labels(device=device).set(dt)
    scrape_ok.labels(device=device).set(1 if got else 0)
    got["_seconds"] = round(dt, 1)
    return got


def discover_sensors(host: str) -> tuple[str | None, str | None]:
    """找出光线和加速度传感器的确切名字（各机型命名不同）。"""
    out = sh(host, "timeout 15 termux-sensor -l")
    try:
        names = json.loads(out)["sensors"]
    except Exception:      # noqa: BLE001
        return None, None
    lig = next((n for n in names if "light" in n.lower()), None)
    acc = next((n for n in names if "acceleromet" in n.lower()), None)
    return lig, acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--device", default="phone1")
    ap.add_argument("--port", type=int, default=9101)
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    lig, acc = discover_sensors(a.host)
    print(f"传感器: light={lig}  accel={acc}")

    if a.once:
        print(json.dumps(sample(a.host, a.device, lig, acc), ensure_ascii=False))
        return

    start_http_server(a.port)
    print(f"exporter 已启动 → http://localhost:{a.port}/metrics（每 {a.interval}s 采一次）")
    while True:
        try:
            s = sample(a.host, a.device, lig, acc)
            print(f"  {time.strftime('%H:%M:%S')}  {json.dumps(s, ensure_ascii=False)}")
        except Exception as e:      # noqa: BLE001
            scrape_ok.labels(device=a.device).set(0)
            print(f"  {time.strftime('%H:%M:%S')}  ✗ {type(e).__name__}: {str(e)[:60]}")
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
