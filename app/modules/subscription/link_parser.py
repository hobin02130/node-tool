import urllib.parse
import base64
import json
import re

# ==============================================================================
# SECTION 1: 基础工具函数 (Utils)
# ==============================================================================

def safe_base64_decode(s):
    """安全 Base64 解码，自动处理 padding 和 URL Safe 字符"""
    if not s: return None
    s = s.strip()
    s = s.replace('-', '+').replace('_', '/')
    missing_padding = len(s) % 4
    if missing_padding:
        s += '=' * (4 - missing_padding)
    try:
        return base64.b64decode(s).decode('utf-8')
    except:
        return None

def get_emoji_flag(region_code):
    """根据地区代码获取 Emoji"""
    if region_code: 
        return region_code.strip()
    return '🌐'

def _get_param(params, key, default=''):
    """获取参数的第一个值"""
    return params.get(key, [default])[0]

def _get_bool(params, keys, default=False):
    """
    解析布尔值，支持多个备选键名 (如 insecure, allowInsecure)
    支持 '1', 'true', 'True' 等格式
    """
    if isinstance(keys, str): keys = [keys]
    
    val = None
    for k in keys:
        if k in params:
            val = params[k][0]
            break
    
    if val is None: return default
    
    val_str = str(val).lower()
    return val_str in ['1', 'true', 'on', 'yes']

def _get_int(params, key, default=None):
    """安全解析整数"""
    val = _get_param(params, key)
    try:
        return int(val)
    except:
        return default

def _get_list(params, key, sep=','):
    """解析列表字符串 (如 alpn=h3,h2)"""
    val = _get_param(params, key)
    if not val: return None
    return [x.strip() for x in val.split(sep) if x.strip()]

def parse_netloc_manual(netloc, default_port=443):
    """
    [核心工具] 手动解析 userinfo@host:port
    解决 Python 标准库无法正确解析不带 [] 的 IPv6 地址的问题
    """
    userinfo = ""
    if '@' in netloc:
        userinfo, host_part = netloc.rsplit('@', 1)
    else:
        host_part = netloc

    server = host_part
    port = default_port

    # 情况 A: [IPv6]:port 或 [IPv6]
    if '[' in host_part and ']' in host_part:
        if ']:' in host_part:
            try:
                server, port_str = host_part.rsplit(':', 1)
                port = int(port_str)
            except ValueError:
                server = host_part
        else:
            server = host_part
    
    # 情况 B: IPv6:port (无括号)
    elif host_part.count(':') >= 2:
        possible_host, possible_port = host_part.rsplit(':', 1)
        if possible_port.isdigit():
            server = f'[{possible_host}]'
            port = int(possible_port)
        else:
            server = f'[{host_part}]'

    # 情况 C: domain:port 或 ipv4:port
    elif ':' in host_part:
        try:
            server, port_str = host_part.rsplit(':', 1)
            port = int(port_str)
        except ValueError:
            server = host_part
    
    return userinfo, server, port

def fix_link_ipv6(link):
    """[链接修复] 强制标准化链接中的 IPv6 格式"""
    if not link: return link
    link = link.strip()

    # 1. VMess 特殊处理
    if link.lower().startswith('vmess://'):
        try:
            b64_part = link[8:]
            decoded = safe_base64_decode(b64_part)
            if not decoded: return link
            v_data = json.loads(decoded)
            addr = v_data.get('add', '')
            if addr and ':' in addr and not addr.startswith('['):
                v_data['add'] = f"[{addr}]"
                new_b64 = base64.b64encode(json.dumps(v_data).encode('utf-8')).decode('utf-8')
                return f"vmess://{new_b64}"
            return link
        except:
            return link

    # 2. 通用 URL 处理
    try:
        parsed = urllib.parse.urlparse(link)
        if not parsed.netloc: return link
        userinfo, server, port = parse_netloc_manual(parsed.netloc, 443)
        new_netloc = ""
        if userinfo: new_netloc += f"{userinfo}@"
        new_netloc += f"{server}:{port}"
        new_parsed = parsed._replace(netloc=new_netloc)
        return urllib.parse.urlunparse(new_parsed)
    except:
        return link

# ==============================================================================
# SECTION 2: 独立协议处理器 (Protocol Handlers)
# ==============================================================================

def _parse_hysteria2(parsed, params, proxy_name):
    """
    处理 Hysteria2 / Hy2 协议
    """
    userinfo, server, port = parse_netloc_manual(parsed.netloc, 443)
    
    password = parsed.username if parsed.username else parsed.password
    if userinfo: password = urllib.parse.unquote(userinfo)
    
    # 兼容非常规格式 (hy2://pass@host)
    if not password and not userinfo and '@' in parsed.netloc:
            try:
                raw_userinfo, _ = parsed.netloc.rsplit('@', 1)
                password = urllib.parse.unquote(raw_userinfo)
            except: pass
    
    # 如果 URL 没密码，尝试 auth 参数
    if not password:
        password = _get_param(params, 'auth')

    proxy = {
        "name": proxy_name,
        "type": "hysteria2",
        "server": server,
        "port": port,
        "password": password,
        "sni": _get_param(params, 'sni', _get_param(params, 'peer')),
        "skip-cert-verify": _get_bool(params, ['insecure', 'skip-cert-verify', 'allowInsecure']),
        "udp": True
    }
    
    # ALPN
    alpn = _get_list(params, 'alpn')
    if alpn: proxy['alpn'] = alpn

    # Obfs
    if _get_param(params, 'obfs'):
        proxy['obfs'] = _get_param(params, 'obfs')
        proxy['obfs-password'] = _get_param(params, 'obfs-password')

    # Bandwidth (参考 JS: up ?? upmbps)
    up = _get_int(params, 'up') or _get_int(params, 'upmbps')
    down = _get_int(params, 'down') or _get_int(params, 'downmbps')
    if up: proxy['up'] = up
    if down: proxy['down'] = down

    # Advanced params
    if _get_param(params, 'ports'):
        proxy['ports'] = _get_param(params, 'ports')
    
    if _get_param(params, 'hop-interval'):
        proxy['hop-interval'] = _get_int(params, 'hop-interval')

    return proxy

def _parse_vless(parsed, params, proxy_name):
    """
    处理 VLESS 协议
    """
    userinfo, server, port = parse_netloc_manual(parsed.netloc, 443)
    
    uuid_str = parsed.username
    if userinfo: uuid_str = urllib.parse.unquote(userinfo)
    elif uuid_str: uuid_str = urllib.parse.unquote(uuid_str)

    network = _get_param(params, 'type', 'tcp')
    security = _get_param(params, 'security', 'none')
    
    proxy = {
        "name": proxy_name,
        "type": "vless",
        "server": server,
        "port": port,
        "uuid": uuid_str,
        "network": network,
        "udp": True,
        "tfo": _get_bool(params, 'fast-open'),
        "skip-cert-verify": _get_bool(params, ['insecure', 'skip-cert-verify']),
        "servername": _get_param(params, 'sni')
    }
    
    # Flow
    flow = _get_param(params, 'flow')
    if flow: proxy['flow'] = flow

    # ALPN
    alpn = _get_list(params, 'alpn')
    if alpn: proxy['alpn'] = alpn

    # Packet Encoding
    pkt_encoding = _get_param(params, 'packet_encoding') or _get_param(params, 'packet-encoding')
    if pkt_encoding: proxy['packet-encoding'] = pkt_encoding

    # TLS / Reality
    if security == 'reality':
        proxy['tls'] = True
        proxy['reality-opts'] = {
            "public-key": _get_param(params, 'pbk'),
            "short-id": _get_param(params, 'sid')
        }
        fp = _get_param(params, 'fp')
        proxy['client-fingerprint'] = fp if fp else 'chrome'
        
    elif security == 'tls' or _get_bool(params, 'tls'):
        proxy['tls'] = True
        fp = _get_param(params, 'fp')
        if fp: proxy['client-fingerprint'] = fp
    
    # Transport Options (ws, grpc, http/h2)
    if network == 'ws':
        proxy['ws-opts'] = {
            "path": _get_param(params, 'path', '/'),
            "headers": {}
        }
        host = _get_param(params, 'host')
        if host: proxy['ws-opts']['headers']['Host'] = host
    
    elif network == 'grpc':
        proxy['grpc-opts'] = {
            "grpc-service-name": _get_param(params, 'serviceName', '')
        }
    
    elif network == 'h2': # HTTP/2
        proxy['h2-opts'] = {
            "path": _get_param(params, 'path', '/').split(','),
            "host": _get_list(params, 'host')
        }

    elif network == 'http': # HTTPUpgrade (TCP+HTTP伪装)
        proxy['http-opts'] = {
            "method": "GET",
            "path": _get_param(params, 'path', '/').split(','),
        }
        headers = {}
        host = _get_param(params, 'host')
        if host: headers['Host'] = host.split(',')
        if headers: proxy['http-opts']['headers'] = headers

    return proxy

def _parse_trojan(parsed, params, proxy_name):
    """
    处理 Trojan 协议
    """
    userinfo, server, port = parse_netloc_manual(parsed.netloc, 443)
    
    password = parsed.username
    if userinfo: password = urllib.parse.unquote(userinfo)
    elif password: password = urllib.parse.unquote(password)

    # Trojan 的参数逻辑与 VLESS 高度相似
    network = _get_param(params, 'type', 'tcp')
    security = _get_param(params, 'security', 'tls') # Trojan 默认通常是 TLS
    
    proxy = {
        "name": proxy_name,
        "type": "trojan",
        "server": server,
        "port": port,
        "password": password,
        "network": network,
        "udp": True,
        "tfo": _get_bool(params, 'fast-open'),
        "skip-cert-verify": _get_bool(params, ['insecure', 'skip-cert-verify']),
        "sni": _get_param(params, 'sni')
    }

    # ALPN
    alpn = _get_list(params, 'alpn')
    if alpn: proxy['alpn'] = alpn
    
    # Client Fingerprint (JS: tls.utls.fingerprint)
    fp = _get_param(params, 'fp')
    if fp: proxy['client-fingerprint'] = fp
    
    # Reality (虽然 Trojan 较少用 Reality，但 JS 代码里有支持)
    if security == 'reality':
        proxy['reality-opts'] = {
            "public-key": _get_param(params, 'pbk'),
            "short-id": _get_param(params, 'sid')
        }

    # Transport Options (ws, grpc)
    if network == 'ws':
        proxy['ws-opts'] = {
            "path": _get_param(params, 'path', '/'),
            "headers": {}
        }
        host = _get_param(params, 'host')
        if host: proxy['ws-opts']['headers']['Host'] = host
    
    elif network == 'grpc':
        proxy['grpc-opts'] = {
            "grpc-service-name": _get_param(params, 'serviceName', '')
        }

    return proxy

def _parse_tuic(parsed, params, proxy_name):
    """
    处理 TUIC 协议
    """
    userinfo_str, server, port = parse_netloc_manual(parsed.netloc, 443)
    
    uuid_str = ""
    password = ""
    if userinfo_str:
        if ':' in userinfo_str:
            uuid_raw, pass_raw = userinfo_str.split(':', 1)
            uuid_str = urllib.parse.unquote(uuid_raw)
            password = urllib.parse.unquote(pass_raw)
        else:
            uuid_str = urllib.parse.unquote(userinfo_str)
    if not password: password = parsed.password
    skip_cert_verify_value = _get_bool(
    params, 
    keys=['insecure', 'skip-cert-verify', 'allowInsecure'], 
    default=True # TUIC 默认跳过证书验证
)

    proxy = {
        "name": proxy_name,
        "type": "tuic",
        "server": server,
        "port": port,
        "uuid": uuid_str,
        "password": password,
        "tls": True,
        "udp": True,
        "disable-sni": _get_bool(params, 'disable-sni'),
        "skip-cert-verify": skip_cert_verify_value,
        "congestion-controller": _get_param(params, 'congestion_controller', 'bbr'),
        "udp-relay-mode": _get_param(params, 'udp-relay-mode', 'native'),
        "reduce-rtt": _get_bool(params, 'reduce-rtt'),
        "zero-rtt": _get_bool(params, 'zero-rtt')
    }
    
    alpn = _get_list(params, 'alpn')
    if alpn: proxy['alpn'] = alpn
    else: proxy['alpn'] = ['h3']
    sni_value = _get_param(params, 'sni')
    if sni_value:
        proxy['sni'] = sni_value
        proxy['servername'] = sni_value # 保持兼容性

    return proxy

def _parse_vmess(link, proxy_name):
    """
    处理 VMess 协议 (基于 Base64 JSON)
    """
    try:
        b64_part = link[8:]
        # 支持 vmess://BASE64#Name 格式
        if '#' in b64_part:
            b64_part = b64_part.split('#')[0]

        decoded = safe_base64_decode(b64_part)
        if not decoded: return None
        
        v = json.loads(decoded)
        
        server_addr = v.get('add')
        # IPv6 格式修复
        if server_addr and ':' in server_addr and not server_addr.startswith('['):
            server_addr = f'[{server_addr}]'

        # 基础配置
        proxy = {
            "name": proxy_name,
            "type": "vmess",
            "server": server_addr,
            "port": int(v.get('port', 443)),
            "uuid": v.get('id'),
            "alterId": int(v.get('aid', 0)),
            "cipher": v.get('scy', 'auto'),
            "udp": True,
            "skip-cert-verify": False,
            "tls": False
        }

        # TLS 判断
        tls_val = v.get('tls', '')
        if tls_val and str(tls_val).lower() != 'none':
            proxy['tls'] = True
            proxy['servername'] = v.get('sni', '')
            # 兼容 skip-cert-verify
            if v.get('skip-cert-verify') or v.get('insecure'):
                 proxy['skip-cert-verify'] = True

        # Network / Transport 解析
        net = v.get('net', 'tcp')
        type_field = v.get('type', net) # 有些链接用 type 表示伪装类型

        proxy['network'] = net
        
        # 1. WebSocket
        if net == 'ws':
            proxy['ws-opts'] = {
                "path": v.get('path', '/'),
                "headers": {}
            }
            # Host 优先级: host > sni
            host = v.get('host')
            if not host and v.get('sni'): host = v.get('sni')
            if host: proxy['ws-opts']['headers']['Host'] = host
            
        # 2. HTTP (TCP + HTTP伪装)
        elif net == 'http' or (net == 'tcp' and type_field == 'http'):
            proxy['network'] = 'http'
            http_opts = {
                "method": "GET",
                "path": [v.get('path', '/')]
            }
            # 处理 Headers
            headers = {}
            host = v.get('host')
            if host: headers['Host'] = [host] # Clash Meta要求Host是列表
            if headers: http_opts['headers'] = headers
            proxy['http-opts'] = http_opts

        # 3. gRPC
        elif net == 'grpc':
            proxy['grpc-opts'] = {
                'grpc-service-name': v.get('path', '') or v.get('serviceName', '')
            }

        # 4. H2 (HTTP/2)
        elif net == 'h2':
             proxy['h2-opts'] = {
                 "path": [v.get('path', '/')],
                 "host": [v.get('host', '')]
             }

        # Packet Encoding
        if v.get('packet_encoding') or v.get('packet-encoding'):
            proxy['packet-encoding'] = v.get('packet_encoding') or v.get('packet-encoding')

        return proxy
    except Exception as e:
        print(f"VMess Parsing Error: {e}")
        return None

def _parse_ss(link, proxy_name, params=None):
    """处理 Shadowsocks 协议"""
    try:
        body = link[5:]
        if '#' in body: body, _ = body.split('#', 1)

        if '@' not in body:
            decoded = safe_base64_decode(body)
            if decoded: body = decoded
        
        if '@' in body:
            userinfo_part, host_part = body.rsplit('@', 1)
            
            if ':' not in userinfo_part:
                decoded_user = safe_base64_decode(userinfo_part)
                if decoded_user: userinfo_part = decoded_user
            
            if ':' in userinfo_part:
                method, password = userinfo_part.split(':', 1)
                server, port = host_part.rsplit(':', 1)
                
                if ':' in server and not (server.startswith('[') and server.endswith(']')):
                    server = f'[{server}]'
                
                proxy = {
                    "name": proxy_name,
                    "type": "ss",
                    "server": server,
                    "port": int(port),
                    "cipher": method,
                    "password": password,
                    "udp": True,
                    "tfo": _get_bool(params, 'fast-open') if params else False
                }
                
                if params and _get_param(params, 'plugin'):
                    proxy['plugin'] = _get_param(params, 'plugin')
                    proxy['plugin-opts'] = {}
                    opts = _get_param(params, 'plugin_opts')
                    if opts:
                        try:
                            proxy['plugin-opts'] = json.loads(opts)
                        except:
                            proxy['plugin-opts'] = {"options": opts}
                return proxy
    except Exception as e:
        print(f"SS Parsing Error: {e}")
        return None
    return None

# ==============================================================================
# SECTION 3: 主分发入口 (Main Entry Point)
# ==============================================================================

def parse_proxy_link(link, base_name, region_code):
    """
    [主函数] 解析各种协议链接并转换为 Clash Meta 配置字典
    路由文件 (routes.py) 调用此函数。
    """
    try:
        link = link.strip()
        
        # 1. 构造标准名称
        flag = get_emoji_flag(region_code)
        clean_name = base_name.replace(flag, '').strip()
        proxy_name = f"{flag} {clean_name}"

        # 2. 协议分发
        lower_link = link.lower()

        # [特殊处理] VMess
        if lower_link.startswith('vmess://'):
            return _parse_vmess(link, proxy_name)

        # [标准 URL 协议] 解析 URL 和参数
        parsed = urllib.parse.urlparse(link)
        params = urllib.parse.parse_qs(parsed.query)

        if lower_link.startswith('vless://'):
            return _parse_vless(parsed, params, proxy_name)
        
        elif lower_link.startswith('trojan://'):
            return _parse_trojan(parsed, params, proxy_name)
            
        elif lower_link.startswith(('hy2://', 'hysteria2://')):
            return _parse_hysteria2(parsed, params, proxy_name)
            
        elif lower_link.startswith('tuic://'):
            return _parse_tuic(parsed, params, proxy_name)
            
        elif lower_link.startswith('ss://'):
            return _parse_ss(link, proxy_name, params)
            
    except Exception as e:
        print(f"Link Parse Error [{link[:30]}...]: {e}")
        return None
    
    return None

# ==============================================================================
# SECTION 4: 订阅内容解析 (Subscription Helper)
# ==============================================================================

def extract_nodes_from_content(content):
    """
    [订阅辅助] 从订阅文本（可能是 Base64 编码的）中提取每行链接
    用于 routes.py 中的 fetch_from_sub_api
    """
    nodes = []
    
    decoded = safe_base64_decode(content)
    text_content = decoded if decoded else content
    
    lines = text_content.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        protocol = None
        if '://' in line:
            protocol = line.split('://')[0].lower()
        
        if protocol in ['hysteria2', 'hy2']: protocol = 'hy2'
        elif protocol in ['shadowsocks']: protocol = 'ss'
        elif protocol in ['vmess', 'VMESS']: protocol = 'vmess'
        elif protocol in ['vless', 'tuic', 'trojan', 'socks5']: pass
        else: continue 
        
        name = "Unknown Node"
        if '#' in line:
            try:
                raw_name = line.split('#')[-1]
                name = urllib.parse.unquote(raw_name).strip()
            except: pass
        else:
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