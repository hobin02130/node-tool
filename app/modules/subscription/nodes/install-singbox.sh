#!/usr/bin/env bash
set -euo pipefail

# =========================================================
# 基础配置区 (在此处修改默认端口)
# =========================================================
# VLESS Reality 端口
PORT_REALITY_FIXED=51811
# Shadowsocks 端口
PORT_SS_FIXED=51812
# Hysteria2 端口
PORT_HY2_FIXED=51813
# TUIC 端口
PORT_TUIC_FIXED=51814
# =========================================================
# 如果不懂请勿对下面代码进行任何修改以防出错！！！
# 如果不懂请勿对下面代码进行任何修改以防出错！！！
# 如果不懂请勿对下面代码进行任何修改以防出错！！！
# =========================================================
# -----------------------
# 初始化变量
# -----------------------
PORT_SS=""
PORT_HY2=""
PORT_TUIC=""
PORT_REALITY=""
PSK_SS=""
PSK_HY2=""
PSK_TUIC=""
UUID_TUIC=""
UUID=""
REALITY_PK=""
REALITY_PUB=""
REALITY_SID=""
REPORT_URL="" 

# -----------------------
# 彩色输出函数
info() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err()  { echo -e "\033[1;31m[ERR]\033[0m $*" >&2; }

# -----------------------
# 参数解析
ENABLE_SS=false
ENABLE_HY2=false
ENABLE_TUIC=false
ENABLE_REALITY=false
PROTOCOL_SELECTED=false 

while [[ $# -gt 0 ]]; do
    case "$1" in
        shadowsocks|ss) 
            ENABLE_SS=true; PROTOCOL_SELECTED=true; shift ;;
        hysteria2|hy2)  
            ENABLE_HY2=true; PROTOCOL_SELECTED=true; shift ;;
        tuic)           
            ENABLE_TUIC=true; PROTOCOL_SELECTED=true; shift ;;
        vless|reality)  
            ENABLE_REALITY=true; PROTOCOL_SELECTED=true; shift ;;
        --report)
            if [[ -n "${2:-}" ]]; then
                REPORT_URL="$2"; shift 2
            else
                err "--report 参数需要提供 URL"; exit 1
            fi ;;
        *) shift ;;
    esac
done

if [ "$PROTOCOL_SELECTED" = false ]; then
    info "未指定具体协议，默认安装所有协议..."
    ENABLE_SS=true
    ENABLE_HY2=true
    ENABLE_TUIC=true
    ENABLE_REALITY=true
fi

# -----------------------
# 检测系统类型
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID="${ID:-}"
        OS_ID_LIKE="${ID_LIKE:-}"
    else
        OS_ID=""; OS_ID_LIKE=""
    fi

    if echo "$OS_ID $OS_ID_LIKE" | grep -qi "alpine"; then
        OS="alpine"
    elif echo "$OS_ID $OS_ID_LIKE" | grep -Ei "debian|ubuntu"; then
        OS="debian"
    elif echo "$OS_ID $OS_ID_LIKE" | grep -Ei "centos|rhel|fedora"; then
        OS="redhat"
    else
        OS="unknown"
    fi
}
detect_os

if [ "$(id -u)" != "0" ]; then err "此脚本需要 root 权限"; exit 1; fi

# -----------------------
# 安装依赖
install_deps() {
    info "安装系统依赖..."
    case "$OS" in
        alpine)
            apk update || true
            apk add --no-cache bash curl ca-certificates openssl openrc jq || { err "依赖安装失败"; exit 1; }
            ;;
        debian)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -y || true
            apt-get install -y curl ca-certificates openssl jq || { err "依赖安装失败"; exit 1; }
            ;;
        redhat)
            yum install -y curl ca-certificates openssl jq || { err "依赖安装失败"; exit 1; }
            ;;
    esac
}
install_deps

# -----------------------
# 工具函数 (修改版)
# -----------------------

# 1. SS 专用密钥生成 (必须是 Base64 格式)
rand_ss_key() {
    openssl rand -base64 16 2>/dev/null | tr -d '\n\r' || head -c 16 /dev/urandom | base64 | tr -d '\n\r'
}

# 2. 通用安全密码生成 (仅字母数字，防止 URL 解析错误)
rand_pass_safe() {
    # 过滤出纯字母数字，长度 16
    head -c 500 /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 16
}

rand_uuid() {
    if [ -f /proc/sys/kernel/random/uuid ]; then cat /proc/sys/kernel/random/uuid; else
        openssl rand -hex 16 | sed 's/\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)/\1\2\3\4-\5\6-\7\8-\9\10-\11\12\13\14\15\16/'
    fi
}

# -----------------------
# 自动获取主机名作为后缀
HOST_NAME=$(hostname)
if [[ -n "$HOST_NAME" ]]; then suffix="-${HOST_NAME}"; else suffix=""; fi
echo "$suffix" > /root/node_names.txt
info "节点名称后缀已设置为: $suffix"

# -----------------------
# 导出变量并生成配置
export ENABLE_SS ENABLE_HY2 ENABLE_TUIC ENABLE_REALITY

get_config() {
    info "正在生成配置信息..."
    
    if $ENABLE_SS; then
        PORT_SS=$PORT_SS_FIXED
        # SS 必须使用 rand_ss_key (Base64)
        PSK_SS=$(rand_ss_key)
        info "SS 端口: $PORT_SS"
    fi
    if $ENABLE_HY2; then
        PORT_HY2=$PORT_HY2_FIXED
        # HY2 使用安全字符密码
        PSK_HY2=$(rand_pass_safe)
        info "HY2 端口: $PORT_HY2"
    fi
    if $ENABLE_TUIC; then
        PORT_TUIC=$PORT_TUIC_FIXED
        # TUIC 使用安全字符密码
        PSK_TUIC=$(rand_pass_safe)
        UUID_TUIC=$(rand_uuid)
        info "TUIC 端口: $PORT_TUIC"
    fi
    if $ENABLE_REALITY; then
        PORT_REALITY=$PORT_REALITY_FIXED
        UUID=$(rand_uuid)
        info "Reality 端口: $PORT_REALITY"
    fi
}
get_config

# -----------------------
# 安装 sing-box
install_singbox() {
    info "检查 sing-box 安装..."
    if command -v sing-box >/dev/null 2>&1; then
        info "sing-box 已安装"
        return 0
    fi
    case "$OS" in
        alpine) apk add --repository=http://dl-cdn.alpinelinux.org/alpine/edge/community sing-box ;;
        debian|redhat) bash <(curl -fsSL https://sing-box.app/install.sh) ;;
    esac
}
install_singbox

# -----------------------
# 生成密钥与证书
generate_keys_and_certs() {
    mkdir -p /etc/sing-box/certs
    
    # Reality Keys
    if $ENABLE_REALITY; then
        info "生成 Reality 密钥..."
        REALITY_KEYS=$(sing-box generate reality-keypair 2>&1)
        REALITY_PK=$(echo "$REALITY_KEYS" | grep "PrivateKey" | awk '{print $NF}' | tr -d '\r')
        REALITY_PUB=$(echo "$REALITY_KEYS" | grep "PublicKey" | awk '{print $NF}' | tr -d '\r')
        REALITY_SID=$(sing-box generate rand 8 --hex 2>&1)
        echo -n "$REALITY_PUB" > /etc/sing-box/.reality_pub
        echo -n "$REALITY_SID" > /etc/sing-box/.reality_sid
    fi

    # Self-signed Certs (HY2/TUIC)
    if $ENABLE_HY2 || $ENABLE_TUIC; then
        info "生成自签证书..."
        if [ ! -f /etc/sing-box/certs/fullchain.pem ]; then
            openssl req -x509 -newkey rsa:2048 -nodes \
            -keyout /etc/sing-box/certs/privkey.pem \
            -out /etc/sing-box/certs/fullchain.pem \
            -days 3650 -subj "/CN=www.bing.com" >/dev/null 2>&1
        fi
    fi
}
generate_keys_and_certs

# -----------------------
# 生成配置文件
CONFIG_PATH="/etc/sing-box/config.json"
CACHE_FILE="/etc/sing-box/.config_cache"

create_config() {
    info "写入配置文件..."
    mkdir -p "$(dirname "$CONFIG_PATH")"
    local TEMP_INBOUNDS="/tmp/singbox_inbounds_$$.json"
    > "$TEMP_INBOUNDS"
    
    local need_comma=false
    
    # SS
    if $ENABLE_SS; then
        cat >> "$TEMP_INBOUNDS" <<EOF
    {
      "type": "shadowsocks",
      "listen": "::",
      "listen_port": $PORT_SS,
      "method": "2022-blake3-aes-128-gcm",
      "password": "$PSK_SS",
      "tag": "ss-in"
    }
EOF
        need_comma=true
    fi
    
    # HY2
    if $ENABLE_HY2; then
        $need_comma && echo "," >> "$TEMP_INBOUNDS"
        cat >> "$TEMP_INBOUNDS" <<EOF
    {
      "type": "hysteria2",
      "tag": "hy2-in",
      "listen": "::",
      "listen_port": $PORT_HY2,
      "users": [{ "password": "$PSK_HY2" }],
      "tls": {
        "enabled": true,
        "alpn": ["h3"],
        "certificate_path": "/etc/sing-box/certs/fullchain.pem",
        "key_path": "/etc/sing-box/certs/privkey.pem"
      }
    }
EOF
        need_comma=true
    fi
    
    # TUIC
    if $ENABLE_TUIC; then
        $need_comma && echo "," >> "$TEMP_INBOUNDS"
        cat >> "$TEMP_INBOUNDS" <<EOF
    {
      "type": "tuic",
      "tag": "tuic-in",
      "listen": "::",
      "listen_port": $PORT_TUIC,
      "users": [{ "uuid": "$UUID_TUIC", "password": "$PSK_TUIC" }],
      "congestion_control": "bbr",
      "tls": {
        "enabled": true,
        "alpn": ["h3"],
        "certificate_path": "/etc/sing-box/certs/fullchain.pem",
        "key_path": "/etc/sing-box/certs/privkey.pem"
      }
    }
EOF
        need_comma=true
    fi
    
    # Reality
    if $ENABLE_REALITY; then
        $need_comma && echo "," >> "$TEMP_INBOUNDS"
        cat >> "$TEMP_INBOUNDS" <<EOF
    {
      "type": "vless",
      "tag": "vless-in",
      "listen": "::",
      "listen_port": $PORT_REALITY,
      "users": [{ "uuid": "$UUID", "flow": "xtls-rprx-vision" }],
      "tls": {
        "enabled": true,
        "server_name": "learn.microsoft.com",
        "reality": {
          "enabled": true,
          "handshake": { "server": "learn.microsoft.com", "server_port": 443 },
          "private_key": "$REALITY_PK",
          "short_id": ["$REALITY_SID"]
        }
      }
    }
EOF
    fi

    # 合并
    cat > "$CONFIG_PATH" <<EOF
{
  "log": { "level": "info", "timestamp": true },
  "inbounds": [
EOF
    cat "$TEMP_INBOUNDS" >> "$CONFIG_PATH"
    cat >> "$CONFIG_PATH" <<EOF
  ],
  "outbounds": [{ "type": "direct", "tag": "direct-out" }]
}
EOF
    rm -f "$TEMP_INBOUNDS"

    # 保存缓存
    cat > "$CACHE_FILE" <<EOF
ENABLE_SS=$ENABLE_SS
ENABLE_HY2=$ENABLE_HY2
ENABLE_TUIC=$ENABLE_TUIC
ENABLE_REALITY=$ENABLE_REALITY
PORT_SS="$PORT_SS"
PORT_HY2="$PORT_HY2"
PORT_TUIC="$PORT_TUIC"
PORT_REALITY="$PORT_REALITY"
PSK_SS="$PSK_SS"
PSK_HY2="$PSK_HY2"
PSK_TUIC="$PSK_TUIC"
UUID_TUIC="$UUID_TUIC"
UUID="$UUID"
REALITY_PK="$REALITY_PK"
REALITY_PUB="$REALITY_PUB"
REALITY_SID="$REALITY_SID"
EOF
}
create_config

# -----------------------
# 配置服务
setup_service() {
    info "配置系统服务..."
    if [ "$OS" = "alpine" ]; then
        SERVICE_PATH="/etc/init.d/sing-box"
        cat > "$SERVICE_PATH" <<'OPENRC'
#!/sbin/openrc-run
name="sing-box"
command="/usr/bin/sing-box"
command_args="run -c /etc/sing-box/config.json"
pidfile="/run/${RC_SVCNAME}.pid"
command_background="yes"
supervisor=supervise-daemon
supervise_daemon_args="--respawn-max 0 --respawn-delay 5"
depend() { need net; after firewall; }
start_pre() { checkpath --directory --mode 0755 /var/log; checkpath --directory --mode 0755 /run; }
OPENRC
        chmod +x "$SERVICE_PATH"
        rc-update add sing-box default >/dev/null 2>&1 || true
        rc-service sing-box restart
    else
        SERVICE_PATH="/etc/systemd/system/sing-box.service"
        cat > "$SERVICE_PATH" <<'SYSTEMD'
[Unit]
Description=Sing-box Proxy Server
After=network.target
[Service]
ExecStart=/usr/bin/sing-box run -c /etc/sing-box/config.json
Restart=on-failure
RestartSec=10s
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
SYSTEMD
        systemctl daemon-reload
        systemctl enable sing-box >/dev/null 2>&1
        systemctl restart sing-box
    fi
}
setup_service

# -----------------------
# 输出与上报逻辑
get_public_ip() { curl -s --max-time 5 "https://api.ipify.org" || echo "YOUR_SERVER_IP"; }
PUB_IP=$(get_public_ip)

report_node() {
    local proto=$1
    local link=$2
    if [ -z "$REPORT_URL" ]; then return; fi
    info "☁️ 正在上报 [${proto}] 节点信息到服务器..."
    local node_name="${HOST_NAME:-Node}"
    local json_payload="{\"name\":\"${node_name}\", \"protocol\":\"${proto}\", \"link\":\"${link}\"}"
    curl -s -X POST -H "Content-Type: application/json" -d "$json_payload" "$REPORT_URL" >/dev/null || warn "⚠️ 上报 [${proto}] 失败"
}

print_info() {
    local host="$PUB_IP"
    echo ""
    info "📜 节点链接列表:"
    echo ""
    
    if $ENABLE_SS; then
        local ss_info="2022-blake3-aes-128-gcm:${PSK_SS}"
        local ss_b64=$(printf "%s" "$ss_info" | base64 | tr -d '\n')
        local link="ss://${ss_b64}@${host}:${PORT_SS}#ss${suffix}"
        # 【修改点】去除协议前缀 [SS]
        echo "   $link"
        report_node "ss" "$link"
    fi
    
    if $ENABLE_HY2; then
        local link="hy2://${PSK_HY2}@${host}:${PORT_HY2}/?sni=www.bing.com&alpn=h3&insecure=1#hy2${suffix}"
        # 【修改点】去除协议前缀 [HY2]
        echo "   $link"
        report_node "hy2" "$link"
    fi

    if $ENABLE_TUIC; then
        local link="tuic://${UUID_TUIC}:${PSK_TUIC}@${host}:${PORT_TUIC}/?congestion_control=bbr&alpn=h3&sni=www.bing.com&insecure=1#tuic${suffix}"
        # 【修改点】去除协议前缀 [TUIC]
        echo "   $link"
        report_node "tuic" "$link"
    fi
    
    if $ENABLE_REALITY; then
        local link="vless://${UUID}@${host}:${PORT_REALITY}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=learn.microsoft.com&fp=chrome&pbk=${REALITY_PUB}&sid=${REALITY_SID}#reality${suffix}"
        # 【修改点】去除协议前缀 [VLESS]
        echo "   $link"
        report_node "vless" "$link"
    fi

    echo ""
    info "📊 协议端口汇总:"
    printf "   %-12s | %-8s | %s\n" "协议" "端口" "传输层"
    echo "   ------------------------------------"
    $ENABLE_SS      && printf "   %-12s | %-8s | %s\n" "Shadowsocks" "$PORT_SS" "TCP/UDP"
    $ENABLE_REALITY && printf "   %-12s | %-8s | %s\n" "VLESS" "$PORT_REALITY" "TCP"
    $ENABLE_HY2     && printf "   %-12s | %-8s | %s\n" "Hysteria2" "$PORT_HY2" "UDP"
    $ENABLE_TUIC    && printf "   %-12s | %-8s | %s\n" "TUIC" "$PORT_TUIC" "UDP"
    echo ""
    
    if [ -n "$REPORT_URL" ]; then
        info "✅ 节点自动上报已完成。"
    fi
}

print_info

# -----------------------
# 部署 sb 管理脚本
SB_PATH="/usr/local/bin/sb"
cat > "$SB_PATH" <<'SB_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
info() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
CACHE_FILE="/etc/sing-box/.config_cache"
CONFIG_PATH="/etc/sing-box/config.json"

service_restart() {
    if [ -f /etc/alpine-release ]; then rc-service sing-box restart; else systemctl restart sing-box; fi
}

show_links() {
    if [ -f "$CACHE_FILE" ]; then
        source "$CACHE_FILE"
        suffix=$(cat /root/node_names.txt 2>/dev/null || echo "")
        PUB_IP=$(curl -s --max-time 5 "https://api.ipify.org" || echo "YOUR_SERVER_IP")
        
        echo ""
        info "📜 节点链接列表:"
        echo ""
        
        if [ "${ENABLE_SS:-false}" = "true" ]; then
            ss_info="2022-blake3-aes-128-gcm:${PSK_SS}"
            ss_b64=$(printf "%s" "$ss_info" | base64 | tr -d '\n')
            echo "ss://${ss_b64}@${PUB_IP}:${PORT_SS}#ss${suffix}"
            echo ""
        fi
        
        if [ "${ENABLE_HY2:-false}" = "true" ]; then
            echo "hy2://${PSK_HY2}@${PUB_IP}:${PORT_HY2}/?sni=www.bing.com&alpn=h3&insecure=1#hy2${suffix}"
            echo ""
        fi

        if [ "${ENABLE_TUIC:-false}" = "true" ]; then
            echo "tuic://${UUID_TUIC}:${PSK_TUIC}@${PUB_IP}:${PORT_TUIC}/?congestion_control=bbr&alpn=h3&sni=www.bing.com&insecure=1#tuic${suffix}"
            echo ""
        fi
        
        if [ "${ENABLE_REALITY:-false}" = "true" ]; then
            # 注意：这里 VLESS SNI 默认使用 learn.microsoft.com
            echo "vless://${UUID}@${PUB_IP}:${PORT_REALITY}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=learn.microsoft.com&fp=chrome&pbk=${REALITY_PUB}&sid=${REALITY_SID}#reality${suffix}"
            echo ""
        fi
        
        info "📊 协议端口汇总:"
        printf "   %-12s | %-8s | %s\n" "协议" "端口" "传输层"
        echo "   ------------------------------------"
        [ "${ENABLE_SS:-false}" = "true" ]      && printf "   %-12s | %-8s | %s\n" "Shadowsocks" "$PORT_SS" "TCP/UDP"
        [ "${ENABLE_REALITY:-false}" = "true" ] && printf "   %-12s | %-8s | %s\n" "VLESS" "$PORT_REALITY" "TCP"
        [ "${ENABLE_HY2:-false}" = "true" ]     && printf "   %-12s | %-8s | %s\n" "Hysteria2" "$PORT_HY2" "UDP"
        [ "${ENABLE_TUIC:-false}" = "true" ]    && printf "   %-12s | %-8s | %s\n" "TUIC" "$PORT_TUIC" "UDP"
        echo ""
    else
        echo "错误：未找到配置缓存文件，无法生成链接。"
    fi
}

uninstall_singbox() {
    echo ""
    read -p "⚠️ 确定要完全卸载 sing-box 吗？(y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        info "已取消"
        return
    fi

    info "正在停止服务..."
    if [ -f /etc/alpine-release ]; then
        rc-service sing-box stop 2>/dev/null || true
        rc-update del sing-box default 2>/dev/null || true
        rm -f /etc/init.d/sing-box
        apk del sing-box 2>/dev/null || true
    else
        systemctl stop sing-box 2>/dev/null || true
        systemctl disable sing-box 2>/dev/null || true
        rm -f /etc/systemd/system/sing-box.service
        systemctl daemon-reload 2>/dev/null || true
    fi

    info "正在删除文件..."
    rm -rf /etc/sing-box
    rm -f /usr/bin/sing-box
    rm -f /usr/local/bin/sb
    rm -f /root/node_names.txt
    rm -rf /var/log/sing-box*

    info "✅ 卸载完成，感谢使用！"
    exit 0
}

show_menu() {
    echo ""
    echo "=== Sing-box 管理 (快捷指令 sb) ==="
    echo "1) 查看配置与链接"
    echo "2) 重启服务"
    echo "3) 编辑配置文件"
    echo "4) 完全卸载"
    echo "0) 退出"
}

while true; do
    show_menu
    read -p "选项: " opt
    case "$opt" in
        1) show_links;;
        2) service_restart && info "已重启";;
        3) ${EDITOR:-vi} "$CONFIG_PATH" && service_restart;;
        4) uninstall_singbox;;
        0) exit 0;;
        *) echo "无效选项";;
    esac
done
SB_SCRIPT
chmod +x "$SB_PATH"

echo ""
info "🎉 安装完成! 输入 'sb' 可调用管理菜单。"