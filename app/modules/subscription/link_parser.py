import urllib.parse
import base64
import json # 引入 json 库，虽然目前只是返回字典，但方便未来序列化

# ---------------------------------------------------------
# 1. 辅助工具函数
# ---------------------------------------------------------
# get_emoji_flag 函数：直接返回数据库存储的地区字符串 (通常是 Emoji)
# 如果为 None，返回默认图标
def get_emoji_flag(region_code):
    if region_code: 
        return region_code.strip()
    return '🌐'

# safe_base64_decode 函数：安全的 Base64 解码，自动补全 padding
# 用于处理不标准的 SS 链接
def safe_base64_decode(s):
    if not s: return None
    s = s.strip()
    # 补全 padding
    missing_padding = len(s) % 4
    if missing_padding:
        s += '=' * (4 - missing_padding)
    try:
        # 尝试 urlsafe (常见于 URL)
        return base64.urlsafe_b64decode(s).decode('utf-8')
    except:
        try:
            # 尝试标准 base64
            return base64.b64decode(s).decode('utf-8')
        except:
            return None

# ---------------------------------------------------------
# 2. 核心：解析原始链接为 Clash Meta 字典格式
# ---------------------------------------------------------
# parse_proxy_link 函数：解析各种协议链接 (Hysteria2, VLESS, SS, TUIC) 
# 并转换为 Clash Meta 配置字典
def parse_proxy_link(link, base_name, region_code):
    """
    解析各种协议链接 (Hysteria2, VLESS, SS, TUIC) 并转换为 Clash Meta 配置字典
    :param link: 原始链接字符串
    :param base_name: 节点基础名称
    :param region_code: 地区代码 (Emoji)
    """
    try:
        # 预处理
        link = link.strip()
        parsed = urllib.parse.urlparse(link)
        params = urllib.parse.parse_qs(parsed.query)
        
        # 构造节点名称
        flag = get_emoji_flag(region_code)
        clean_name = base_name.replace(flag, '').strip()
        proxy_name = f"{flag} {clean_name}"

        # ===========================
        # Hysteria2 解析逻辑
        # ===========================
        if link.startswith('hy2://') or link.startswith('hysteria2://'):
            server = parsed.hostname
            port = parsed.port if parsed.port else 443
            password = parsed.username if parsed.username else parsed.password
            
            # 兼容 hy2://password@host 格式
            if not password and '@' in parsed.netloc:
                userinfo = parsed.netloc.split('@')[0]
                password = userinfo
                
            if password: password = urllib.parse.unquote(password)
            else: password = ""

            proxy = {
                "name": proxy_name,
                "type": "hysteria2",
                "server": server,
                "port": port,
                "password": password,
                "sni": params.get('sni', [''])[0],
                "skip-cert-verify": True,
                "udp": True
            }
            
            alpn_str = params.get('alpn', [''])[0]
            proxy['alpn'] = alpn_str.split(',') if alpn_str else ['h3']

            if params.get('obfs'):
                proxy['obfs'] = params.get('obfs')[0]
                proxy['obfs-password'] = params.get('obfs-password', [''])[0]

            return proxy

        # ===========================
        # VLESS (Reality) 解析逻辑
        # ===========================
        elif link.startswith('vless://'):
            server = parsed.hostname
            port = parsed.port if parsed.port else 443
            uuid_str = parsed.username
            if uuid_str: uuid_str = urllib.parse.unquote(uuid_str)

            network = params.get('type', ['tcp'])[0]
            servername = params.get('sni', [''])[0]
            fingerprint = params.get('fp', ['chrome'])[0]
            flow = params.get('flow', [''])[0]

            proxy = {
                "name": proxy_name,
                "type": "vless",
                "server": server,
                "port": port,
                "uuid": uuid_str,
                "network": network,
                "tls": True,
                "udp": True,
                "servername": servername,
                "client-fingerprint": fingerprint
            }
            if flow: proxy['flow'] = flow
            if params.get('security', [''])[0] == 'reality':
                proxy['reality-opts'] = {
                    "public-key": params.get('pbk', [''])[0],
                    "short-id": params.get('sid', [''])[0]
                }
            return proxy
        
        # ===========================
        # VMess 解析逻辑
        # ===========================
        elif link.startswith('vmess://'):
            try:
                b64_part = link[8:]
                decoded = safe_base64_decode(b64_part)
                if not decoded: return None
                
                # VMess 链接通常是 JSON 格式
                v_data = json.loads(decoded)
                
                proxy = {
                    "name": proxy_name,
                    "type": "vmess",
                    "server": v_data.get('add'),
                    "port": int(v_data.get('port')),
                    "uuid": v_data.get('id'),
                    "alterId": int(v_data.get('aid', 0)),
                    "cipher": "auto",
                    "tls": False,
                    "udp": True,
                    "skip-cert-verify": True
                }
                
                # 传输方式
                net = v_data.get('net', 'tcp')
                proxy['network'] = net
                
                # TLS 设置
                if v_data.get('tls') in ['tls', True, 'true']:
                    proxy['tls'] = True
                    if v_data.get('sni'):
                        proxy['servername'] = v_data.get('sni')
                
                # WebSocket 设置
                if net == 'ws':
                    ws_opts = {}
                    if v_data.get('path'):
                        ws_opts['path'] = v_data.get('path')
                    if v_data.get('host'):
                        ws_opts['headers'] = {'Host': v_data.get('host')}
                    if ws_opts:
                        proxy['ws-opts'] = ws_opts
                        
                # Grpc 设置
                if net == 'grpc':
                    proxy['grpc-opts'] = {
                        'grpc-service-name': v_data.get('path', '')
                    }

                return proxy
            except Exception as e:
                print(f"VMess 解析错误: {e}")
                return None

        # ===========================
        # TUIC 解析逻辑 (新增)
        # 兼容 tuic://uuid:password@server:port?params 格式
        # ===========================
        elif link.startswith('tuic://'):
            server = parsed.hostname
            port = parsed.port if parsed.port else 443
            
            userinfo = parsed.username
            password = parsed.password
            uuid_str = ""

            if userinfo and password:
                uuid_str = urllib.parse.unquote(userinfo)
                password = urllib.parse.unquote(password)
            
            # TUIC 协议名称通常不带密码，而是用 UUID 和密码参数
            if not uuid_str and '@' in parsed.netloc:
                 # 尝试从 netloc 提取 uuid:password
                userinfo_part = parsed.netloc.split('@')[0]
                if ':' in userinfo_part:
                    uuid_str, password = userinfo_part.split(':', 1)
                    uuid_str = urllib.parse.unquote(uuid_str)
                    password = urllib.parse.unquote(password)

            # Clash Meta 配置
            proxy = {
                "name": proxy_name,
                "type": "tuic",
                "server": server,
                "port": port,
                "uuid": uuid_str,
                "password": password,
                "tls": True,
                "udp": True,
                "disable_sni": params.get('allow_insecure', ['0'])[0] == '1', # 如果允许不安全连接，则禁用SNI
                "alpn": params.get('alpn', ['h3'])[0].split(','),
                "congestion_controller": params.get('congestion_controller', ['bbr'])[0],
                "zero_rtt": params.get('zero_rtt', ['0'])[0] == '1'
            }
            
            # 可选参数
            if params.get('sni'):
                proxy['servername'] = params.get('sni')[0]
            if params.get('host'):
                proxy['host'] = params.get('host')[0]
            
            # 跳过证书校验
            if params.get('insecure', ['0'])[0] == '1':
                proxy['skip-cert-verify'] = True

            return proxy

        # ===========================
        # Shadowsocks (SS) 解析逻辑 (完善)
        # ===========================
        elif link.startswith('ss://'):
            # 格式1: ss://Base64(method:pass)@host:port
            # 格式2: ss://Base64(method:pass@host:port) (SIP002)
            # 格式3: ss://method:pass@host:port (Clash 常用)
            try:
                body = link[5:]
                if '#' in body: body, _ = body.split('#', 1) # 去掉锚点名称

                # 处理 SIP002 (整个部分都是 Base64)
                if '@' not in body:
                    decoded = safe_base64_decode(body)
                    if decoded: body = decoded # 解码后变成 method:pass@host:port
                
                # 无论是否是 SIP002，现在 body 应该形如 method:pass@host:port 或 Base64(method:pass)@host:port
                
                if '@' in body:
                    userinfo_part, host_part = body.rsplit('@', 1) # 从右边切分
                    
                    # userinfo_part 可能是 Base64 编码的 method:pass
                    if ':' not in userinfo_part:
                        decoded_user = safe_base64_decode(userinfo_part)
                        if decoded_user: userinfo_part = decoded_user
                    
                    # 确保是 method:pass
                    if ':' in userinfo_part and ':' in host_part:
                        method, password = userinfo_part.split(':', 1)
                        server, port = host_part.split(':', 1)
                        
                        proxy = {
                            "name": proxy_name,
                            "type": "ss",
                            "server": server,
                            "port": int(port),
                            "cipher": method,
                            "password": password,
                            "udp": True
                        }
                        
                        # SIP003 插件支持 (可选，Clash Meta 兼容)
                        if params.get('plugin'):
                            proxy['plugin'] = params.get('plugin')[0]
                            proxy['plugin-opts'] = {}
                            # 简单的插件参数处理
                            if params.get('plugin_opts'):
                                # 示例：plugin-opts: {"mode": "websocket"}
                                plugin_opts_str = params.get('plugin_opts')[0]
                                try:
                                    proxy['plugin-opts'] = json.loads(plugin_opts_str)
                                except json.JSONDecodeError:
                                    # 如果不是 JSON 格式，尝试作为纯文本
                                    proxy['plugin-opts'] = {"options": plugin_opts_str}

                        return proxy
                        
            except Exception as ss_e:
                print(f"SS 解析错误: {ss_e}") # 打印错误信息
                return None
            
    except Exception as e:
        print(f"解析链接通用错误: {link[:50]}... | Error: {e}") # 打印通用错误信息
        return None
    return None

# ---------------------------------------------------------
# 从订阅内容提取节点信息 (用于保存到 local_nodes.json)
# ---------------------------------------------------------
def extract_nodes_from_content(content):
    """
    解析订阅文本（可能是 Base64 编码），提取节点基本信息。
    返回列表: [{'name': '...', 'protocol': '...', 'link': '...'}]
    """
    nodes = []
    
    # 1. 尝试 Base64 解码
    decoded = safe_base64_decode(content)
    text_content = decoded if decoded else content
    
    # 2. 按行分割
    lines = text_content.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # 3. 提取协议
        protocol = None
        if '://' in line:
            protocol = line.split('://')[0].lower()
            
        # 映射常见协议到标准简写
        if protocol in ['hysteria2', 'hy2']: protocol = 'hy2'
        elif protocol in ['shadowsocks']: protocol = 'ss'
        elif protocol in ['vmess', 'VMESS']: protocol = 'vm'
        elif protocol in ['vless', 'tuic', 'trojan', 'socks5']: pass
        else: continue # 跳过不支持的协议
        
        # 4. 提取名称 (从 URL Fragment #)
        name = "Unknown Node"
        if '#' in line:
            try:
                raw_name = line.split('#')[-1]
                name = urllib.parse.unquote(raw_name).strip()
            except: pass
        else:
            # 如果没有名称，尝试用服务器地址+端口作为临时名称
            try:
                parsed = urllib.parse.urlparse(line)
                name = f"{parsed.hostname}:{parsed.port}"
            except: pass

        nodes.append({
            'name': name,
            'protocol': protocol,
            'link': line
        })
        
    return nodes