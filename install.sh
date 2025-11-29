#!/bin/bash

# 定义颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---------------------------------------------------------
# 全局变量定义
# ---------------------------------------------------------
INSTALL_DIR="$HOME/nodetool"
BINARY_NAME="NodeTool"
SERVICE_NAME="nodetool"
PORT=5000
LOG_FILE="$INSTALL_DIR/server.log"

# --- GitHub 配置 ---
REPO_OWNER="Hobin66"               # 项目所属用户
REPO_NAME="node-tool"              # 仓库名称
# ---------------------

echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}      NodeTool 安装/更新脚本                  ${NC}"
echo -e "${GREEN}=============================================${NC}"

# 检查当前用户是否有 root 权限或 sudo 命令
CMD_PREFIX=""
if [ "$EUID" -ne 0 ] && command -v sudo &> /dev/null; then
    CMD_PREFIX="sudo"
fi

# ---------------------------------------------------------
# 辅助函数：识别系统架构并设置变量
# ---------------------------------------------------------
function set_architecture_vars() {
    # 检查系统架构
    ARCH=$(uname -m)

    # 将 uname 的输出映射到压缩包命名规则
    case "$ARCH" in
        "x86_64" | "amd64")
            export TOOL_ARCH="amd64"
            ;;
        "aarch64" | "arm64" | "armv8")
            export TOOL_ARCH="arm64"
            ;;
        *)
            echo -e "${RED}错误: 不支持的系统架构 '$ARCH'。${NC}"
            echo "当前脚本仅支持 amd64 (x86_64) 和 arm64 (aarch64)。"
            exit 1
            ;;
    esac

    # 定义基础文件名
    BASE_ASSET_NAME="NodeTool-Linux"
    
    # 最终的压缩包文件名将是：NodeTool-Linux-amd64.zip 或 NodeTool-Linux-arm64.zip
    export ASSET_NAME="${BASE_ASSET_NAME}-${TOOL_ARCH}.zip"

    echo -e "✅ 系统架构: ${CYAN}$ARCH${NC}"
}

# 获取相应架构的最新 Release 下载链接
function get_latest_release_url() {

    API_URL="https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest" 
    
    # 使用 curl 获取 JSON 数据
    RELEASE_INFO=$(curl -s $API_URL)
    
    # 检查 API 请求是否成功
    if echo "$RELEASE_INFO" | grep -q "Not Found"; then
        echo -e "${RED}错误: GitHub 仓库 $REPO_OWNER/$REPO_NAME 未找到或无任何 Release。${NC}"
        exit 1
    fi
    
    # 使用 jq 解析 JSON，提取动态生成的 $ASSET_NAME 对应的链接
    LATEST_URL=$(echo "$RELEASE_INFO" | jq -r ".assets[] | select(.name == \"$ASSET_NAME\") | .browser_download_url")

    if [ -z "$LATEST_URL" ] || [ "$LATEST_URL" == "null" ]; then
        # 提示用户具体缺失的是哪个架构包
        echo -e "${RED}错误: 未能在最新 Release 中找到名为 '$ASSET_NAME' 的附件 (对应的架构是 $TOOL_ARCH)。${NC}"
        echo "请检查 Release 中是否存在该架构的压缩包。"
        exit 1
    fi
    
    # 添加输出链接，并添加用户反馈
    echo -e "${YELLOW}--- 正在从 GitHub Releases 获取最新下载链接 ---${NC}"
    echo -e "✅ 成功获取最新版本链接！"
    echo -e "版本: $(echo "$RELEASE_INFO" | jq -r .tag_name)"
    echo -e "下载链接: ${CYAN}$LATEST_URL${NC}" >&2
    echo "$LATEST_URL"
}

# ---------------------------------------------------------
# 辅助函数：核心安装/更新逻辑 (下载、验证、替换)
# ---------------------------------------------------------
function core_install_logic() {
    # 临时工作目录，用于下载和验证
    local TEMP_DIR="$INSTALL_DIR/temp_update" 

    # 1. 获取下载链接
    DOWNLOAD_URL=$(get_latest_release_url)

    if [ -z "$DOWNLOAD_URL" ]; then
        echo -e "${RED}错误: 无法获取下载链接。${NC}"
        return 1
    fi

# 2. 下载到临时目录
    echo -e "${YELLOW}--- 正在下载文件到临时目录...${NC}"
    mkdir -p "$TEMP_DIR"
    cd "$TEMP_DIR" || return 1
    rm -f package.zip

    curl -L --retry 3 --fail -o package.zip "$DOWNLOAD_URL" > /dev/null 2>&1
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}下载失败。请检查网络连接或 GitHub API 限制。${NC}"
        cd "$INSTALL_DIR" # 返回主目录
        rm -rf "$TEMP_DIR" # 清理临时目录
        return 1
    fi

    # 3. 解压和验证
    echo -e "${YELLOW}--- 正在解压并验证新文件...${NC}"
    unzip -o package.zip > /dev/null
    
    # 查找新的二进制文件
    FOUND_BIN=$(find . -name "$BINARY_NAME" -type f | head -n 1)

    if [ -n "$FOUND_BIN" ]; then
        echo -e "✅ 新的二进制文件验证成功。"
    else
        echo -e "${RED}错误: 在压缩包中未找到新的二进制文件 '$BINARY_NAME'。${NC}"
        cd "$INSTALL_DIR"
        rm -rf "$TEMP_DIR"
        return 1
    fi
    
    # 4. 替换旧文件 (在替换前停止服务)
    echo -e "${YELLOW}--- 正在替换旧文件...${NC}"
    
    # 停止服务 (如果服务已配置)
    if [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
        echo -e "${CYAN}停止 NodeTool 服务...${NC}"
        $CMD_PREFIX systemctl stop $SERVICE_NAME > /dev/null 2>&1
    fi

    # 移动新文件到安装目录 (处理子目录结构)
    if [ "$(dirname "$FOUND_BIN")" != "." ]; then
        # 移动子目录中的所有内容到临时目录根目录
        mv "$(dirname "$FOUND_BIN")"/* "$TEMP_DIR/"
    fi
    
    # 移动新的二进制文件到安装目录
    mv "$TEMP_DIR/$BINARY_NAME" "$INSTALL_DIR/$BINARY_NAME"
    chmod +x "$INSTALL_DIR/$BINARY_NAME"
    
    # 5. 清理
    cd "$INSTALL_DIR"
    rm -rf "$TEMP_DIR"
    echo -e "${GREEN}🎉 核心二进制文件已更新。${NC}"

    return 0
}


# ---------------------------------------------------------
# 辅助函数：检查并卸载旧版本 (Clean Install)
# ---------------------------------------------------------
function check_and_uninstall_if_exists() {
    local SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    local CONTROL_SCRIPT_PATH="/usr/local/bin/nt"

    if [ -f "$SERVICE_FILE" ] || [ -d "$INSTALL_DIR" ]; then
        echo -e "${YELLOW}--- 检测到 NodeTool 已安装 ---${NC}"
        read -r -p "是否要完全卸载旧版本并重新安装？(这将删除所有旧文件和数据库) [y/N] " response
        
        if [[ "$response" =~ ^([yY])$ ]]; then
            echo -e "${RED}执行完全卸载...${NC}"
            
            # 停止和禁用服务
            $CMD_PREFIX systemctl stop $SERVICE_NAME 2>/dev/null
            $CMD_PREFIX systemctl disable $SERVICE_NAME 2>/dev/null
            $CMD_PREFIX rm -f $SERVICE_FILE 2>/dev/null
            $CMD_PREFIX systemctl daemon-reload 2>/dev/null
            
            # 删除安装目录
            rm -rf $INSTALL_DIR
            
            # 删除控制命令
            $CMD_PREFIX rm -f $CONTROL_SCRIPT_PATH
            
            echo -e "${GREEN}🎉 旧版本已彻底卸载。${NC}"
            # 卸载完成后，脚本会继续执行后续的安装步骤
            
        else
            echo -e "${CYAN}取消卸载。退出${NC}"
            exit 0
        fi
    fi
}


# ---------------------------------------------------------
# 辅助函数：安装 nt 控制脚本
# ---------------------------------------------------------
function install_control_script() {
    # 定义控制脚本路径
    local CONTROL_SCRIPT_PATH="/usr/local/bin/nt"
    # 使用 heredoc 创建 nt 脚本内容
    cat <<'NT_SCRIPT_EOF' | $CMD_PREFIX tee $CONTROL_SCRIPT_PATH > /dev/null
#!/bin/bash

# NodeTool 服务控制脚本
SERVICE_NAME="nodetool"
INSTALL_DIR="$HOME/nodetool"
BIN_PATH="/usr/local/bin/nt"
# 定义颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# 检查是否使用 sudo
if [ "$EUID" -ne 0 ] && command -v sudo &> /dev/null; then
    CMD_PREFIX="sudo"
else
    CMD_PREFIX=""
fi

# 显示服务状态 (已优化，提供简洁状态，详细状态可选)
function show_status() {
    echo -e "\n${CYAN}--- ${SERVICE_NAME} 运行状态概览 ---${NC}"
    
    if command -v systemctl &> /dev/null; then
        # 简洁状态：是否激活？
        if $CMD_PREFIX systemctl is-active $SERVICE_NAME &> /dev/null; then
            echo -e "状态: ${GREEN}● 正在运行${NC}"
        else
            echo -e "状态: ${RED}○ 已停止${NC}"
        fi
        
        # 详细状态：提供查看详细日志的入口
        echo -e "日志/详细状态: ${CYAN}nt status detailed${NC} 或 ${CYAN}nt log${NC}"
        
    else
        # 非 systemd 系统的备用显示
        echo -e "${RED}Systemctl 命令不可用。${NC}"
        echo "进程状态: $($CMD_PREFIX pgrep -f ${INSTALL_DIR}/NodeTool)"
    fi
    echo "----------------------------------"
}

# 显示详细 Systemd 状态
function show_detailed_status() {
    echo -e "\n${CYAN}--- ${SERVICE_NAME} 详细状态 (systemctl status) ---${NC}"
    if command -v systemctl &> /dev/null; then
        # 使用 --no-pager 或 less/more 来防止输出过多刷屏
        $CMD_PREFIX systemctl status $SERVICE_NAME --no-pager
    else
        echo -e "${RED}Systemctl 命令不可用。${NC}"
    fi
    echo "----------------------------------"
}

# 卸载功能
function uninstall() {
    read -r -p "警告：您确定要彻底卸载 NodeTool 吗？(这将删除服务和安装目录：$INSTALL_DIR) [y/N] " response
    if [[ "$response" =~ ^([yY])$ ]]; then
        echo -e "${YELLOW}停止并禁用服务...${NC}"
        $CMD_PREFIX systemctl stop $SERVICE_NAME > /dev/null 2>&1 # 静默停止
        $CMD_PREFIX systemctl disable $SERVICE_NAME > /dev/null 2>&1 # 静默禁用
        $CMD_PREFIX rm -f /etc/systemd/system/${SERVICE_NAME}.service 2>/dev/null
        $CMD_PREFIX systemctl daemon-reload > /dev/null 2>&1
        
        echo -e "${YELLOW}删除安装目录 $INSTALL_DIR...${NC}"
        rm -rf $INSTALL_DIR
        
        echo -e "${YELLOW}删除控制命令 'nt'...${NC}"
        $CMD_PREFIX rm -f $BIN_PATH
        
        echo -e "${GREEN}🎉 NodeTool 已彻底卸载。${NC}"
        exit 0
    else
        echo -e "${CYAN}取消卸载。${NC}"
    fi
}

# 核心更新功能
function update() {
    # 假设 install.sh 脚本位于用户的主目录下
    INSTALL_SCRIPT="$HOME/install.sh" 
    
    if [ ! -f "$INSTALL_SCRIPT" ]; then
        echo -e "${RED}错误: 未找到主安装脚本 $INSTALL_SCRIPT，无法执行核心更新。${NC}"
        echo "请确保 install.sh 文件在您的 $HOME 目录下。"
        return 1
    fi
    
    echo -e "${CYAN}执行核心更新流程...${NC}"
    
    # 警告：此命令将执行 install.sh 脚本中的 core_install_logic 函数。
    # 假设 install.sh 脚本的结构已经被修改为仅执行 core_install_logic 并退出。
    # 运行 install.sh 脚本 (它现在只执行 core_install_logic)
    
    $CMD_PREFIX bash "$INSTALL_SCRIPT"
    
    if [ $? -eq 0 ]; then
        echo -e "${YELLOW}重新启动 NodeTool 服务...${NC}"
        $CMD_PREFIX systemctl restart $SERVICE_NAME > /dev/null 2>&1
        show_status
    else
        echo -e "${RED}更新失败，请检查 $INSTALL_SCRIPT 脚本的输出。${NC}"
    fi
}


# ---------------------------------------------------------
# 主控制逻辑：支持参数或菜单
# ---------------------------------------------------------
if [ -z "$1" ]; then
    # 菜单模式
    while true; do
        echo -e "\n${GREEN}--- NodeTool 控制台 ---${NC}"
        echo -e "1) ${CYAN}查看状态 (status)${NC}"
        echo -e "2) ${CYAN}启动服务 (start)${NC}"
        echo -e "3) ${CYAN}重启服务 (restart)${NC}"
        echo -e "4) ${CYAN}停止服务 (stop)${NC}"
        echo -e "5) ${CYAN}更新程序 (update)${NC}" # 新增更新选项
        echo -e "6) ${RED}查看日志 (log)${NC}"
        echo -e "7) ${RED}完全卸载 (uninstall)${NC}"
        echo -e "0) ${YELLOW}退出面板${NC}"
        read -r -p "请输入选项 [0-7]: " choice
        
        case "$choice" in
            1) show_status ;;
            2) 
                echo -e "${CYAN}正在启动 NodeTool...${NC}"
                $CMD_PREFIX systemctl start $SERVICE_NAME > /dev/null 2>&1
                sleep 1
                show_status
                ;;
            3) 
                echo -e "${CYAN}正在重启 NodeTool...${NC}"
                $CMD_PREFIX systemctl restart $SERVICE_NAME > /dev/null 2>&1
                sleep 1
                show_status
                ;;
            4) 
                echo -e "${CYAN}正在停止 NodeTool...${NC}"
                $CMD_PREFIX systemctl stop $SERVICE_NAME > /dev/null 2>&1
                sleep 1
                show_status
                ;;
            5) update ;; # 调用 update 函数
            6)
                echo -e "${CYAN}--- NodeTool 实时日志 (Ctrl+C 退出) ---${NC}"
                $CMD_PREFIX journalctl -u $SERVICE_NAME -f
                ;;
            7) uninstall; break ;;
            0) echo -e "${CYAN}退出控制面板。${NC}"; break ;;
            *) echo -e "${RED}输入无效，请重新选择。${NC}" ;;
        esac
    done
else
    # 参数模式 (兼容旧命令，并新增 detailed/log/update)
    case "$1" in
        start)
            echo -e "${CYAN}正在启动 NodeTool...${NC}"
            $CMD_PREFIX systemctl start $SERVICE_NAME > /dev/null 2>&1
            sleep 2
            show_status
            ;;
        stop)
            echo -e "${CYAN}正在停止 NodeTool...${NC}"
            $CMD_PREFIX systemctl stop $SERVICE_NAME > /dev/null 2>&1
            sleep 2
            show_status
            ;;
        restart)
            echo -e "${CYAN}正在重启 NodeTool...${NC}"
            $CMD_PREFIX systemctl restart $SERVICE_NAME > /dev/null 2>&1
            sleep 2
            show_status
            ;;
        status)
            show_status
            ;;
        update) # 新增 update 命令
            update
            ;;
        detailed | status-detailed)
            show_detailed_status
            ;;
        log)
            echo -e "${CYAN}--- NodeTool 实时日志 (Ctrl+C 退出) ---${NC}"
            $CMD_PREFIX journalctl -u $SERVICE_NAME -f
            ;;
        uninstall)
            uninstall
            ;;
        *)
            echo -e "${RED}NodeTool 控制台${NC}"
            echo -e "${CYAN}用法: nt [start | stop | restart | status | update | detailed | log | uninstall]${NC}"
            echo -e "例如: nt status"
            ;;
    esac
fi
NT_SCRIPT_EOF

    # 赋予执行权限
    $CMD_PREFIX chmod +x $CONTROL_SCRIPT_PATH
    echo -e "✅ 'nt' 命令已安装到 $CONTROL_SCRIPT_PATH"
}


# ---------------------------------------------------------
# 主脚本开始
# ---------------------------------------------------------

# 调用架构识别函数
set_architecture_vars

# 检查并卸载旧版本
check_and_uninstall_if_exists

# 1. 检查依赖
echo -e "${YELLOW} 检查系统环境...${NC}"
DEPENDENCIES=("unzip" "curl" "wget" "pgrep" "jq" "timeout") # 🟢 添加 timeout
INSTALL_TIMEOUT=120 # 设置超时时间为 60 秒

for cmd in "${DEPENDENCIES[@]}"; do
    if ! command -v $cmd &> /dev/null; then
        echo -e "${YELLOW}未找到 '$cmd'，正在安装...${NC}"
        INSTALL_SUCCESS=0
        
        # 使用临时变量存储安装命令
        INSTALL_CMD=""
        
        if [ -x "$(command -v apt-get)" ]; then
            # 尝试使用 apt-get 安装。注意：update也需要静默处理。
            $CMD_PREFIX apt-get update > /dev/null 2>&1
            INSTALL_CMD="$CMD_PREFIX apt-get install -y $cmd"
        elif [ -x "$(command -v yum)" ]; then
            # 尝试使用 yum 安装
            INSTALL_CMD="$CMD_PREFIX yum install -y $cmd"
        fi
        
        if [ -n "$INSTALL_CMD" ]; then
            # 设置超时，并将所有输出重定向到 /dev/null
            if command -v timeout &> /dev/null; then
                # 如果系统支持 timeout 命令，则使用它
                timeout $INSTALL_TIMEOUT $INSTALL_CMD > /dev/null 2>&1
                INSTALL_SUCCESS=$?
            else
                # 如果不支持 timeout，则仅静默安装
                $INSTALL_CMD > /dev/null 2>&1
                INSTALL_SUCCESS=$?
                # 注意：此处无法实现超时退出
            fi
        else
            # 如果没有找到包管理器，直接标记失败
            INSTALL_SUCCESS=1
        fi
        
        # 检查安装结果
        if [ $INSTALL_SUCCESS -eq 124 ]; then
            # 124 是 timeout 命令的退出码，表示命令超时
            echo -e "${RED}❌ 错误: '$cmd' 安装超时 (${INSTALL_TIMEOUT} 秒)。请检查网络或手动安装。${NC}"
            exit 1
        elif [ $INSTALL_SUCCESS -ne 0 ]; then
            # 检查是否有权限执行 sudo
            if [ -n "$CMD_PREFIX" ] && [ "$EUID" -ne 0 ]; then
                echo -e "${RED}错误: 无法自动安装 '$cmd' (退出码: $INSTALL_SUCCESS)。请确认您具有正确的 sudo 权限。${NC}"
            else
                echo -e "${RED}❌ 错误: 无法自动安装 '$cmd' (退出码: $INSTALL_SUCCESS)。请手动运行相应的安装命令。${NC}"
            fi
            exit 1
        fi
        
        echo -e "✅ '$cmd' 安装成功。"
    fi
done

# 2. 统一执行核心安装逻辑 (下载、解压、替换)
echo -e "${YELLOW} 正在安装...${NC}"
# 注意：首次安装时，目标目录可能不存在，core_install_logic会负责创建
core_install_logic
if [ $? -ne 0 ]; then
    echo -e "${RED}安装失败，退出。${NC}"
    exit 1
fi

# 5. 配置 Systemd 和控制脚本
echo -e "${YELLOW} 正在设置自启与控制脚本...${NC}"
ABS_DIR=$(cd "$INSTALL_DIR" && pwd)
CURRENT_USER=$(whoami)

# 清理旧日志
rm -f "$LOG_FILE"

# 生成 Systemd Service 文件
cat <<EOF > ${SERVICE_NAME}.service
[Unit]
Description=NodeTool Web Service
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$ABS_DIR
ExecStart=$ABS_DIR/$BINARY_NAME
Restart=always
RestartSec=5
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

[Install]
WantedBy=multi-user.target
EOF

# 如果有 root/sudo 权限，安装服务
if [ -n "$CMD_PREFIX" ] || [ "$EUID" -eq 0 ]; then
    # 安装服务
    $CMD_PREFIX mv ${SERVICE_NAME}.service /etc/systemd/system/${SERVICE_NAME}.service
    $CMD_PREFIX systemctl daemon-reload > /dev/null 2>&1
    $CMD_PREFIX systemctl enable ${SERVICE_NAME}
    $CMD_PREFIX systemctl restart ${SERVICE_NAME}
    echo "服务已安装并重启。"
    # 安装 nt 脚本
    install_control_script
else
    echo -e "${RED}警告: 无 root/sudo 权限。使用 nohup 后备模式启动。${NC}"
    pkill -f "./$BINARY_NAME" || true
    nohup ./$BINARY_NAME > "$LOG_FILE" 2>&1 &
fi

# 等待时间
echo "正在等待服务启动 (3秒)..."
sleep 3

# 6. 状态检查与调试
echo -e "${YELLOW} 正在执行健康检查...${NC}"

# 检查 1: 进程
if pgrep -f "./$BINARY_NAME" > /dev/null; then
    echo -e "✅ 进程正在运行 (PID: $(pgrep -f "./$BINARY_NAME"))"
else
    echo -e "${RED}❌ 进程未运行！${NC}"
    echo -e "${CYAN}--- 应用启动日志 ($LOG_FILE) ---${NC}"
    if [ -f "$LOG_FILE" ]; then
        tail -n 20 "$LOG_FILE"
    else
        echo "无日志文件生成。"
    fi
    echo -e "${CYAN}-------------------------------${NC}"
    exit 1
fi

# Systemd 状态诊断
echo -e "${YELLOW}--- Systemd 状态诊断 (获取崩溃原因) ---${NC}"
if command -v systemctl &> /dev/null; then
    $CMD_PREFIX systemctl status $SERVICE_NAME --no-pager
else
    echo "Systemctl 命令不完整或不可用，跳过详细状态检查。"
fi
echo "------------------------------"

# 检查 2 & 3: 端口监听和本地 HTTP 请求
if command -v netstat &> /dev/null; then
    PORT_CHECK_CMD="netstat -tuln"
elif command -v ss &> /dev/null; then
    PORT_CHECK_CMD="ss -tuln"
else
    PORT_CHECK_CMD=""
fi

if [ -n "$PORT_CHECK_CMD" ]; then
    if $PORT_CHECK_CMD | grep -q ":$PORT "; then
        echo -e "✅ 端口 $PORT 正在监听"
    else
        echo -e "${RED}❌ 进程正在运行，但端口 $PORT 未监听。${NC}"
    fi
fi

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$PORT)
if [ "$HTTP_CODE" -eq 200 ] || [ "$HTTP_CODE" -eq 302 ]; then
    echo -e "✅ 本地 HTTP 请求成功 (状态码: $HTTP_CODE)"
else
    echo -e "${RED}❌ 本地 HTTP 请求失败 (状态码: $HTTP_CODE)。${NC}"
    
    echo -e "${CYAN}--- 应用启动日志 ($LOG_FILE) ---${NC}"
    if [ -f "$LOG_FILE" ]; then
        tail -n 20 "$LOG_FILE"
    else
        echo -e "${RED}警告：日志文件 $LOG_FILE 未找到或为空。${NC}"
    fi
    echo -e "${CYAN}-------------------------------${NC}"
    
    # 额外调试：检查依赖库
    echo -e "${YELLOW}[调试] 检查二进制文件依赖:${NC}"
    if command -v ldd &> /dev/null; then
        ldd "$INSTALL_DIR/$BINARY_NAME" | grep "not found" # 修正了路径，确保不在 temp_update 目录
        if [ $? -eq 0 ]; then
            echo -e "${RED}发现缺失的系统库！${NC}"
        else
            echo "依赖库检查看起来正常。"
        fi
    fi
    
    exit 1
fi

# 7. 最终总结
echo -e "${YELLOW} 安装完成！${NC}"
IP=$(curl -s ifconfig.me)
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}🎉 NodeTool 正在运行！${NC}"
echo -e "---------------------------------------------"
echo -e "管理命令: ${CYAN}nt [start|stop|restart|status|update|uninstall|log|detailed]${NC}"
echo -e "日志查看: ${CYAN}${CMD_PREFIX} journalctl -u nodetool -f${NC}" # <-- 使用 CMD_PREFIX
echo -e "公网地址:   ${YELLOW}http://$IP:$PORT${NC}"
echo -e "${GREEN}=============================================${NC}"