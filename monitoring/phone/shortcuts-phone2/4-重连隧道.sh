#!/data/data/com.termux/files/usr/bin/bash
# ⚑ 必须先 stop：隧道用了 ExitOnForwardFailure，端口被旧连接占着会整个失败
~/tun.sh stop; sleep 2; ~/tun.sh start
echo "隧道: $(~/tun.sh status)"
echo
read -n 1 -s -r -p "按任意键关闭"
