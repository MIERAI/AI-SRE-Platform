#!/data/data/com.termux/files/usr/bin/python
"""部署后自检。在手机1 上跑：python ~/verify.py

### 为什么需要它

Phase 6 踩过两次同类的坑，都属于「看起来一切正常」：

  1. 一条 PromQL 告警因裸 `and` 的 label 集不匹配而【永不触发】，
     Prometheus 界面上一直安详地显示 inactive。
  2. 14 个 Grafana 面板加载成功，实际只有 4 个有数据 ——
     其中两处是永远不会有数据的埋点缺失。

所以这里检查的不是「服务是否 Running」，而是三件事：
  ① 每条告警规则**能不能返回结果**（把阈值换成必然成立的版本）
  ② 每个面板查询**当前是否真有数据**
  ③ Grafana 是否真的把 provisioning 加载进去了（数据源 uid、面板存在）
"""
import json
import os
import sys
import urllib.parse
import urllib.request

PROM = "http://127.0.0.1:9090"
GRAF = "http://127.0.0.1:3000"
PW_FILE = os.path.expanduser("~/grafana/ADMIN_PASSWORD.txt")


def get(url, auth=None, timeout=25):
    req = urllib.request.Request(url)
    if auth:
        import base64
        tok = base64.b64encode(auth.encode()).decode()
        req.add_header("Authorization", "Basic " + tok)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def q(expr):
    """返回该查询当前命中的序列数；-1 表示查询本身出错。"""
    url = f"{PROM}/api/v1/query?query=" + urllib.parse.quote(expr)
    try:
        r = get(url)
        return len(r["data"]["result"]) if r.get("status") == "success" else -1
    except Exception as e:                                  # noqa: BLE001
        print(f"      ! {type(e).__name__}: {str(e)[:50]}")
        return -1


def main():
    ok = True

    print("=" * 66)
    print("① 告警规则：能不能触发")
    print("=" * 66)
    # ⚑ 用「必然成立」的对照式检验，而不是等真实条件发生。
    #   只看规则 state=inactive 无法区分「健康」和「表达式根本匹配不到序列」。
    probes = [
        ("PhoneExporterDown", 'up{job="phone"} == 1'),
        ("PhoneServiceDown", "phone_service_up == 1"),
        ("PhoneRestartStorm", "increase(phone_service_restarts_total[1h]) >= 0"),
        ("PhoneOverheat", "max(phone_thermal_celsius) > 0"),
        ("PhoneUnplugged", "phone_battery_charging >= 0"),
        ("PhoneMemoryLow", "phone_memavailable_bytes > 0"),
        ("PhoneDiskLow", "phone_disk_free_bytes > 0"),
    ]
    for name, expr in probes:
        n = q(expr)
        mark = "✅" if n > 0 else "❌"
        if n <= 0:
            ok = False
        print(f"  {mark} {name:<20} {n:>3} 条序列")

    print()
    print("=" * 66)
    print("② Grafana provisioning 是否真的加载")
    print("=" * 66)
    try:
        pw = open(PW_FILE).read().strip()
    except OSError:
        print("  ✗ 读不到密码文件，跳过 Grafana 检查")
        return 1
    auth = f"admin:{pw}"

    try:
        ds = get(f"{GRAF}/api/datasources", auth)
        uids = [d["uid"] for d in ds]
        hit = "prometheus" in uids
        print(f"  {'✅' if hit else '❌'} 数据源 uid=prometheus  （现有：{uids}）")
        # uid 写死很重要：面板按 uid 引用，随机 uid 会让所有面板变成
        # 「Datasource not found」—— 而那时服务全是绿的。
        ok &= hit

        boards = {}
        for uid in ("phone1", "phone1m"):
            d = get(f"{GRAF}/api/dashboards/uid/{uid}", auth)["dashboard"]
            boards[uid] = d
            print(f"  ✅ 面板已加载：{d['title']}（{len(d['panels'])} 个 panel）")
    except Exception as e:                                  # noqa: BLE001
        print(f"  ✗ Grafana API 失败：{type(e).__name__}: {str(e)[:60]}")
        return 1

    print()
    print("=" * 66)
    print("③ 每个面板查询当前是否真有数据")
    print("=" * 66)
    # ⚑ 注意这一节只能证明「查得到数据」，证明不了「数据是对的」。
    #   实测踩过：cpu 标签解析错误让 8 个核塌缩成一条 {cpu=""} 序列，
    #   这里照样打 ✅ —— 发现它靠的是「序列数该是 8 却只有 1」这个人眼比对。
    #   所以下面对已知基数的指标额外断言条数。
    EXPECT = {"phone_cpu_freq_mhz": 8, "phone_service_up": 3, "up": 2}
    empty = []
    for uid, dash in boards.items():
        print(f"  --- {dash['title']} ---")
        for p in dash["panels"]:
            for t in p.get("targets", []):
                expr = t.get("expr", "")
                if not expr:
                    continue
                n = q(expr)
                want = EXPECT.get(expr.strip())
                bad = n <= 0 or (want is not None and n != want)
                mark = "❌" if bad else "✅"
                note = f"（应为 {want}）" if want is not None and n != want else ""
                if bad:
                    empty.append((p["title"], expr))
                    ok = False
                print(f"  {mark} {p['title'][:24]:<26} {n:>3} 条{note}  {expr[:30]}")

    print()
    if empty:
        print("⚠️  以下面板【现在没有数据】—— 要么埋点没上，要么查询写错：")
        for title, expr in empty:
            print(f"     {title}  ←  {expr}")
    print("=" * 66)
    print("结论：" + ("全部通过 ✅" if ok else "存在问题 ❌ 见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
