#!/data/data/com.termux/files/usr/bin/bash
# 查博客访问统计(用 DuckDB 分析 Caddy 的 JSON 日志)
C=~/blog_access.jsonl
[ -f "$C" ] || { echo "还没有访问日志"; exit 0; }
echo "═══ 博客访问统计 ═══"
echo "【按国家】"
duckdb -c "SELECT request.headers['Cf-Ipcountry'][1] AS 国家, COUNT(*) AS 请求, COUNT(DISTINCT request.client_ip) AS 访客 FROM read_json_auto('$C') WHERE request.client_ip != '127.0.0.1' GROUP BY 国家 ORDER BY 请求 DESC;" 2>/dev/null
echo "【最热页面】"
duckdb -c "SELECT request.uri AS 页面, COUNT(*) AS 访问 FROM read_json_auto('$C') WHERE request.uri NOT LIKE '%.woff' AND request.uri NOT LIKE '%favicon%' AND request.uri NOT LIKE '%_astro%' AND request.client_ip!='127.0.0.1' GROUP BY 页面 ORDER BY 访问 DESC LIMIT 8;" 2>/dev/null
echo "【独立访客总数】"
duckdb -c "SELECT COUNT(DISTINCT request.client_ip) AS 独立访客 FROM read_json_auto('$C') WHERE request.client_ip!='127.0.0.1';" 2>/dev/null
