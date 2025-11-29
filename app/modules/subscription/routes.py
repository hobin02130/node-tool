# routes.py

from flask import Blueprint, render_template, jsonify, Response, make_response, request, url_for, abort
from flask_login import login_required
# 引入 update_node_custom_name 用于 DB 节点改名
from app.utils.db_manager import get_all_nodes, update_node_details, get_config, set_config, update_node_custom_name
import os
import sys
# 引入创建的路径处理工具
from app.utils.path_helper import get_external_config_path
import json
import base64
import time
import urllib.parse
import uuid
from io import BytesIO

# 🚨 必须安装: pip install ruamel.yaml
from ruamel.yaml import YAML
from .link_parser import parse_proxy_link, get_emoji_flag

bp = Blueprint('subscription', __name__, url_prefix='/subscription', template_folder='templates')

# ---------------------------------------------------------
# 1. 配置与工具函数
# ---------------------------------------------------------
def get_nodes_dir():
    """
    获取节点配置文件存储目录
    🟢 [修改] 增加打包环境判断逻辑
    """
    if getattr(sys, 'frozen', False):
        # [打包环境]
        # 如果是 exe 运行，强制定向到 exe 同级目录下的 'nodes' 文件夹
        # 这样用户在 exe 旁边修改 yaml/json 才会生效
        nodes_dir = get_external_config_path('nodes')
    else:
        # [开发环境]
        # 保持原样，指向 app/subscription/nodes
        current_dir = os.path.dirname(os.path.abspath(__file__))
        nodes_dir = os.path.join(current_dir, 'nodes')

    # 如果目录不存在，尝试自动创建
    if not os.path.exists(nodes_dir):
        try: os.makedirs(nodes_dir)
        except OSError as e: print(f"Error creating nodes dir: {e}")
    
    return nodes_dir

# ---------------------------------------------------------
# 2. 本地节点管理工具 & 核心同步逻辑
# ---------------------------------------------------------
LOCAL_NODES_FILE = 'local_nodes.json'

def get_local_nodes_path():
    return os.path.join(get_nodes_dir(), LOCAL_NODES_FILE)

def load_local_nodes_raw():
    """
    [底层函数] 仅读取原始 JSON 数据，不进行业务逻辑处理
    """
    path = get_local_nodes_path()
    if not os.path.exists(path): return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return []

# 建立别名兼容旧代码调用
load_local_nodes = load_local_nodes_raw

def save_local_nodes(nodes):
    """保存节点列表到 JSON"""
    try:
        # 保存前按 sort_index 排序，保持文件整洁
        nodes.sort(key=lambda x: x.get('sort_index', 9999))
        with open(get_local_nodes_path(), 'w', encoding='utf-8') as f:
            json.dump(nodes, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error saving local nodes: {e}")
        return False

def merge_db_to_local_json():
    """
    🟢 [核心函数] 将数据库节点同步到本地 JSON
    修改点：将 DB 节点的 is_fixed 改为 False，允许前端拖拽改变分组
    """
    db_nodes = get_all_nodes()
    local_nodes = load_local_nodes_raw()
    
    local_map = {n['uuid']: n for n in local_nodes}
    active_db_uuids = set()
    has_changes = False

    # --- 1. 同步 DB 节点 ---
    for db_node in db_nodes:
        uuid_str = str(db_node.uuid)
        active_db_uuids.add(uuid_str)
        
        # 获取 DB 权威数据
        db_name = db_node.custom_name or db_node.name
        links = db_node.get_links_dict()
        r_type = db_node.routing_type if db_node.routing_type is not None else -1
        region = db_node.region or 'DB'

        if uuid_str in local_map:
            # [更新]
            node = local_map[uuid_str]
            
            updates = {
                'name': db_name,
                'links': links,
                'routing_type': r_type,
                'region': region,
                'origin': 'db',
                'is_fixed': False  # 🟢 [修改] 允许 DB 节点被拖拽移动
            }
            
            for k, v in updates.items():
                if node.get(k) != v:
                    node[k] = v
                    has_changes = True
            
            if 'sort_index' not in node:
                node['sort_index'] = 9999
                has_changes = True
                
        else:
            # [新增]
            new_node = {
                "uuid": uuid_str,
                "name": db_name,
                "links": links,
                "routing_type": r_type,
                "region": region,
                "origin": "db",
                "is_fixed": False, # 🟢 [修改] 允许 DB 节点被拖拽移动
                "sort_index": 99999
            }
            local_nodes.append(new_node)
            has_changes = True

    # --- 2. 清理失效节点 ---
    final_nodes = []
    for node in local_nodes:
        is_db_node = node.get('origin') == 'db'
        
        if is_db_node and node['uuid'] not in active_db_uuids:
            has_changes = True
            continue 
            
        if not is_db_node:
            if node.get('origin') != 'local':
                node['origin'] = 'local'
                node['is_fixed'] = False 
                has_changes = True

        final_nodes.append(node)
    
    if has_changes:
        save_local_nodes(final_nodes)
        return final_nodes
    
    return final_nodes
# ---------------------------------------------------------
# 3. 配置文件生成逻辑 (读取统一数据源)
# ---------------------------------------------------------
def sync_nodes_to_files():
    """
    生成 0.yaml 和 1.yaml
    🟢 修复：强制将 YAML 中的 name 字段重写为 'Flag Proto-Name' 格式
    """
    # 1. 获取最新合并后的节点列表
    all_nodes = merge_db_to_local_json()
    
    # 2. 按 sort_index 排序
    all_nodes.sort(key=lambda x: x.get('sort_index', 0))

    proxies_map = {0: [], 1: []}
    count_summary = {0: 0, 1: 0}

    for node in all_nodes:
        r_type = node.get('routing_type', -1)
        if r_type not in proxies_map: continue
        
        links = node.get('links', {})
        node_name = node.get('name', 'Unknown')
        origin = node.get('origin', 'local')
        region = node.get('region')
        
        for proto, link in links.items():
            if link and link.strip():
                # --- [核心修改] 命名格式强制调整 ---
                # 1. 确定国旗
                flag = get_emoji_flag(region) if origin == 'db' else '📝'
                
                # 2. 构造强制名称：Flag Protocol-Name (例如: 🇸🇬 hy2-SG-NAT1)
                # proto.lower() 确保协议名为小写
                display_name = f"{flag} {proto.lower()}-{node_name}".strip()
                
                # 3. 调用解析器
                # 注意：虽然传入了 display_name，但解析器可能会优先读取 link 中的 #hash
                proxy_dict = parse_proxy_link(link.strip(), display_name, region)
                
                if proxy_dict:
                    # 🟢 [Bug 修复关键点] 
                    # 无论 parse_proxy_link 返回的 name 是什么（可能是旧的后缀格式），
                    # 这里强制将其覆盖为我们刚刚构造的前缀格式。
                    proxy_dict['name'] = display_name
                    
                    proxies_map[r_type].append(proxy_dict)
                    count_summary[r_type] += 1

    # --- 写入 YAML ---
    nodes_dir = get_nodes_dir()
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096

    try:
        with open(os.path.join(nodes_dir, '0.yaml'), 'w', encoding='utf-8') as f:
            yaml.dump({'proxies': proxies_map[0]}, f)
        with open(os.path.join(nodes_dir, '1.yaml'), 'w', encoding='utf-8') as f:
            yaml.dump({'proxies': proxies_map[1]}, f)  
        return True, f"同步成功: 直连 {count_summary[0]}, 落地 {count_summary[1]}"
    except Exception as e:
        return False, f"写入失败: {str(e)}"

# ---------------------------------------------------------
# 4. 统计逻辑
# ---------------------------------------------------------
def get_stats_data():
    """获取统计信息：🟢 修改为统一从合并列表获取"""
    # 触发同步，获取全量数据
    all_nodes = merge_db_to_local_json()

    stats = {
        "total": len(all_nodes),
        "direct": 0,
        "land": 0,
        "blocked": 0,
        "protocols": {}
    }

    PROTOCOL_NORMALIZE_MAP = {
        'hy2': 'Hysteria2', 'hysteria2': 'Hysteria2',
        'ss': 'Shadowsocks', 'shadowsocks': 'Shadowsocks',
        'vless': 'VLESS', 'vmess': 'VMess',
        'trojan': 'Trojan', 'tuic': 'TUIC', 'socks5': 'Socks5'
    }

    for node in all_nodes:
        r_type = node.get('routing_type', -1)
        if r_type == 0: stats['direct'] += 1
        elif r_type == 1: stats['land'] += 1
        else: stats['blocked'] += 1
        
        links = node.get('links', {})
        for proto, link in links.items():
            if link and link.strip():
                key = proto.lower()
                normalized = PROTOCOL_NORMALIZE_MAP.get(key, proto)
                stats['protocols'][normalized] = stats['protocols'].get(normalized, 0) + 1
    
    return stats

# ---------------------------------------------------------
# 数据库存储并处理订阅设置 (辅助函数保持不变)
# ---------------------------------------------------------
def get_sub_settings():
    return {
        'fixed_domain': get_config('fixed_domain', default=''),
        'api_token': get_config('api_token', default='default')
    }

def verify_request_token():
    token = request.args.get('token')
    settings = get_sub_settings()
    if token != settings.get('api_token', 'default'):
        abort(403, description="Invalid Access Token")

def get_base_url():
    settings = get_sub_settings()
    fixed = settings.get('fixed_domain', '').strip()
    if fixed: return fixed.rstrip('/')
    
    scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
    host = request.headers.get('X-Forwarded-Host') or request.headers.get('Host') or request.host
    if ':' not in host and request.headers.get('X-Forwarded-Port'):
        host = f"{host}:{request.headers.get('X-Forwarded-Port')}"
    return f"{scheme}://{host}"

# ---------------------------------------------------------
# 5. 路由视图函数
# ---------------------------------------------------------
@bp.route('/')
@login_required
def manager():
    """订阅管理主页"""
    stats = get_stats_data()
    settings = get_sub_settings()
    base_url = get_base_url()
    token = settings.get('api_token', 'default')
    
    clash_url = f"{base_url}/subscription/clash?token={token}"
    v2ray_url = f"{base_url}/subscription/base64/all?token={token}"
    script_url = f"{base_url}{url_for('subscription.download_singbox_script')}"
    callback_url = f"{base_url}{url_for('subscription.add_node_callback')}"
    
    return render_template('sub_manager.html', stats=stats, clash_url=clash_url, 
                           v2ray_url=v2ray_url, script_url=script_url, 
                           callback_url=callback_url, token=token, 
                           settings=settings, current_base_url=base_url)

@bp.route('/api/settings/update', methods=['POST'])
@login_required
def update_settings_api():
    """API: 更新设置"""
    data = request.get_json()
    is_saved = False
    if 'domain' in data:
        domain = data.get('domain', '').strip()
        if domain and not domain.startswith('http'): domain = 'http://' + domain
        if set_config('fixed_domain', domain, description='订阅管理-固定域名'): is_saved = True
    if 'api_token' in data:
        if set_config('api_token', data.get('api_token', '').strip(), description='订阅管理-安全Token'): is_saved = True
    return jsonify({'status': 'success' if is_saved else 'error', 'message': '设置已保存' if is_saved else '保存失败'})

@bp.route('/api/token/refresh', methods=['POST'])
@login_required
def refresh_token_api():
    """API: 刷新 Token"""
    new_token = str(uuid.uuid4()).replace('-', '')[:16]
    if set_config('api_token', new_token, description='订阅管理-安全Token'):
        return jsonify({'status': 'success', 'token': new_token, 'message': 'Token 已刷新'})
    return jsonify({'status': 'error', 'message': '刷新失败'}), 500

@bp.route('/clash')
def download_clash_config():
    """下载 Clash 配置文件"""
    verify_request_token()
    sync_nodes_to_files() # 🟢 触发同步
    
    try:
        base_url = get_base_url()
        token = get_sub_settings().get('api_token', 'default')
        timestamp = int(time.time())
        path = os.path.join(get_nodes_dir(), 'clash_meta.yaml')
        
        if not os.path.exists(path): return "Error: Template not found.", 404
        
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        with open(path, 'r', encoding='utf-8') as f: config_data = yaml.load(f)
        
        # 更新 Provider URL
        if 'proxy-providers' in config_data:
            for name, p in config_data['proxy-providers'].items():
                if '0.yaml' in p.get('path', '') or '/raw/0' in p.get('url', '') or '中转' in name:
                    p['url'] = f"{base_url}/subscription/raw/0?token={token}&t={timestamp}"
                    p['interval'] = 300
                elif '1.yaml' in p.get('path', '') or '/raw/1' in p.get('url', '') or '落地' in name:
                    p['url'] = f"{base_url}/subscription/raw/1?token={token}&t={timestamp}"
                    p['interval'] = 300
        
        if 'rule-providers' in config_data:
            for name, p in config_data['rule-providers'].items():
                if 'direct' in name or 'direct' in p.get('path', ''):
                    p['url'] = f"{base_url}/subscription/list/direct?token={token}&t={timestamp}"
                elif 'customize' in name or 'customize' in p.get('path', ''):
                    p['url'] = f"{base_url}/subscription/list/customize?token={token}&t={timestamp}"

        out = BytesIO()
        yaml.dump(config_data, out)
        resp = make_response(out.getvalue())
        resp.headers["Content-Disposition"] = "attachment; filename=clash_meta_config.yaml"
        resp.mimetype = "text/yaml; charset=utf-8"
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp
    except Exception as e: return f"Error: {str(e)}", 500

@bp.route('/install-singbox.sh')
def download_singbox_script():
    path = os.path.join(get_nodes_dir(), 'install-singbox.sh')
    if not os.path.exists(path): return Response("echo 'Error not found.'", mimetype='text/plain')
    with open(path, 'r', encoding='utf-8') as f: return Response(f.read(), mimetype='text/plain')

@bp.route('/api/stats')
@login_required
def get_stats_api():
    """API: 获取最新统计数据 (🟢 内部触发同步)"""
    try:
        # 这一步会执行：DB/Local -> local_nodes.json -> 0.yaml/1.yaml
        success, message = sync_nodes_to_files() 
        
        # 即使文件同步成功或失败，我们仍然获取统计数据更新前端UI
        stats = get_stats_data()
        
        # 可以在返回消息中带上同步结果，但为了兼容前端，我们只返回 stats
        return jsonify({'status': 'success', 'stats': stats})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/api/sync_files', methods=['POST'])
@login_required
def sync_files_api():
    """API: 手动触发同步"""
    success, message = sync_nodes_to_files()
    return jsonify({'status': 'success' if success else 'error', 'message': message})

# ---------------------------------------------------------
# 节点管理 API (🟢 统一管理 DB 和 Local)
# ---------------------------------------------------------

@bp.route('/api/nodes/list', methods=['GET'])
@login_required
def get_nodes_list_api():
    """
    API: 获取节点列表
    🟢 修改：调用 merge_db_to_local_json 获取统一列表并按 sort_index 排序
    """
    try:
        nodes = merge_db_to_local_json() # 获取最新同步数据
        nodes.sort(key=lambda x: x.get('sort_index', 0)) # 排序
        
        # 补充前端需要的辅助字段
        for node in nodes:
            # is_db 字段方便前端判断图标
            node['is_db'] = (node.get('origin') == 'db')
            node['is_local'] = (node.get('origin') == 'local')
            # 协议列表
            node['protocols'] = list(node.get('links', {}).keys())
            
        return jsonify({'status': 'success', 'nodes': nodes})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/api/local_nodes/add', methods=['POST'])
@login_required
def add_local_node_api():
    """API: 添加本地节点"""
    try:
        data = request.get_json()
        name, proto, link = data.get('name'), data.get('protocol'), data.get('link')
        if not all([name, proto, link]): return jsonify({'status': 'error', 'message': '参数不完整'}), 400
        
        local_nodes = load_local_nodes_raw()
        # 查找是否存在同名本地节点 (排除 DB 节点)
        target = next((n for n in local_nodes if n['name'] == name and n.get('origin') != 'db'), None)
        
        if target:
            target.setdefault('links', {})[proto] = link
            msg = f"协议 {proto} 已合并到本地节点 {name}"
        else:
            local_nodes.append({
                "uuid": str(uuid.uuid4()),
                "name": name,
                "links": {proto: link},
                "routing_type": -1, # 默认屏蔽
                "origin": "local",
                "is_fixed": False,
                "sort_index": 99999
            })
            msg = f"本地节点 {name} 已创建"
            
        save_local_nodes(local_nodes)
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/api/local_nodes/rename', methods=['POST'])
@login_required
def rename_local_node_api():
    """
    API: 重命名节点
    🟢 修改：根据 origin 判断调用 DB 函数还是修改本地 JSON
    """
    try:
        data = request.get_json()
        target_uuid = data.get('uuid')
        new_name = data.get('name')
        if not target_uuid or not new_name: return jsonify({'status': 'error', 'message': '参数不完整'}), 400
            
        local_nodes = load_local_nodes_raw()
        target_node = next((n for n in local_nodes if n['uuid'] == target_uuid), None)
        
        if not target_node: return jsonify({'status': 'error', 'message': '未找到节点'}), 404
            
        if target_node.get('origin') == 'db':
            # 🟢 DB 节点：调用数据库更新
            success = update_node_custom_name(target_uuid, new_name)
            if not success: return jsonify({'status': 'error', 'message': '数据库更新失败'}), 500
        else:
            # 🟢 Local 节点：直接更新 JSON
            target_node['name'] = new_name
            save_local_nodes(local_nodes)
            
        sync_nodes_to_files() # 重新同步以刷新配置
        return jsonify({'status': 'success', 'message': '重命名成功'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/api/local_nodes/update_links', methods=['POST'])
@login_required
def update_local_node_links_api():
    """API: 更新链接 (仅限本地节点)"""
    try:
        data = request.get_json()
        uuid_val, links = data.get('uuid'), data.get('links')
        local_nodes = load_local_nodes_raw()
        node = next((n for n in local_nodes if n['uuid'] == uuid_val), None)
        
        if not node: return jsonify({'status': 'error', 'message': '节点不存在'}), 404
        # 🟢 防止修改 DB 节点链接
        if node.get('origin') == 'db': return jsonify({'status': 'error', 'message': '数据库节点链接不可在此修改'}), 403
        
        cleaned = {k: v for k, v in links.items() if v and v.strip()}
        if not cleaned:
            local_nodes.remove(node)
            msg = '节点已清空并删除'
        else:
            node['links'] = cleaned
            msg = '链接已更新'
            
        save_local_nodes(local_nodes)
        sync_nodes_to_files()
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/api/local_nodes/delete', methods=['POST'])
@login_required
def delete_local_node_api():
    """API: 删除节点 (仅限本地节点)"""
    try:
        uuid_val = request.get_json().get('uuid')
        local_nodes = load_local_nodes_raw()
        node = next((n for n in local_nodes if n['uuid'] == uuid_val), None)
        
        if not node: return jsonify({'status': 'error', 'message': '节点不存在'}), 404
        if node.get('origin') == 'db': return jsonify({'status': 'error', 'message': '无法删除数据库同步节点'}), 403
        
        local_nodes.remove(node)
        save_local_nodes(local_nodes)
        sync_nodes_to_files()
        return jsonify({'status': 'success', 'message': '节点已删除'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/api/local_nodes/delete_protocol', methods=['POST'])
@login_required
def delete_local_node_protocol_api():
    """API: 删除协议 (仅限本地节点)"""
    try:
        data = request.get_json()
        uuid_val, proto = data.get('uuid'), data.get('protocol')
        local_nodes = load_local_nodes_raw()
        node = next((n for n in local_nodes if n['uuid'] == uuid_val), None)
        
        if not node: return jsonify({'status': 'error', 'message': '节点不存在'}), 404
        if node.get('origin') == 'db': return jsonify({'status': 'error', 'message': '无法修改数据库节点'}), 403
        
        if 'links' in node and proto in node['links']:
            del node['links'][proto]
            msg = '协议已删除'
            if not node['links']:
                local_nodes.remove(node)
                msg += '，节点为空已清理'
            save_local_nodes(local_nodes)
            sync_nodes_to_files()
            return jsonify({'status': 'success', 'message': msg})
        return jsonify({'status': 'error', 'message': '协议不存在'}), 404
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/api/nodes/update_routing', methods=['POST'])
@login_required
def update_nodes_routing_api():
    """
    API: 更新节点排序和分组
    🟢 修改：支持 DB 节点的分组修改。
    如果检测到 DB 节点的分组(routing_type)发生变化，自动同步回数据库。
    """
    try:
        data = request.get_json()
        local_nodes = load_local_nodes_raw()
        node_map = {n['uuid']: n for n in local_nodes}
        
        groups = [('direct', 0), ('land', 1), ('blocked', -1)]
        current_index = 0
        
        for group_name, type_code in groups:
            uuid_list = data.get(group_name, [])
            for uuid_val in uuid_list:
                if uuid_val in node_map:
                    node = node_map[uuid_val]
                    
                    # 1. 更新排序索引 (所有节点)
                    node['sort_index'] = current_index
                    current_index += 1
                    
                    # 2. 更新分组 (路由类型)
                    old_type = node.get('routing_type', -1)
                    
                    # 如果分组发生了变化
                    if old_type != type_code:
                        if node.get('origin') == 'db':
                            # 🟢 [核心修改] DB 节点：调用数据库函数更新 routing_type
                            # update_node_details 需要完整信息，我们从 local_nodes 中读取当前的 links 和 name
                            success = update_node_details(
                                uuid_val, 
                                node.get('links', {}), 
                                type_code, # 新的路由类型
                                node.get('name') 
                            )
                            if success:
                                node['routing_type'] = type_code
                            else:
                                print(f"Failed to update DB node routing: {uuid_val}")
                        else:
                            # Local 节点：直接更新 JSON
                            node['routing_type'] = type_code
        
        # 保存 JSON 并生成配置文件
        save_local_nodes(local_nodes)
        sync_nodes_to_files()
        
        return jsonify({'status': 'success', 'message': '排序与分组已更新 (DB已同步)'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/base64/all')
def download_v2ray_base64():
    """下载 Base64 订阅"""
    verify_request_token()
    # 🟢 统一从 merged 列表获取，确保顺序正确
    nodes = merge_db_to_local_json()
    nodes.sort(key=lambda x: x.get('sort_index', 0))
    
    links = []
    for node in nodes:
        links_dict = node.get('links', {})
        name = node.get('name', 'Unknown')
        origin = node.get('origin', 'local')
        region = node.get('region', 'LOC')
        
        flag = get_emoji_flag(region) if origin == 'db' else '📝'
        
        for proto, link in links_dict.items():
            if link and link.strip():
                # --- [修改开始] 命名格式调整: 国旗 hy2-名称 ---
                full_name = f"{flag} {proto}-{name}".strip()
                # --- [修改结束] ---
                
                safe_name = urllib.parse.quote(full_name)
                if '#' in link: link = link.split('#')[0]
                links.append(f"{link}#{safe_name}")

    b64 = base64.b64encode("\n".join(links).encode('utf-8')).decode('utf-8')
    return Response(b64, mimetype='text/plain')

@bp.route('/api/callback/add_node', methods=['POST'])
def add_node_callback():
    """API: 脚本回调自动添加节点 (视为 Local 节点)"""
    try:
        data = request.get_json()
        name, proto, link = data.get('name'), data.get('protocol'), data.get('link')
        if not all([name, proto, link]): return jsonify({'status': 'error', 'message': 'Missing data'}), 400
        
        local_nodes = load_local_nodes_raw()
        target = next((n for n in local_nodes if n['name'] == name and n.get('origin') == 'local'), None)
        
        if target:
            target.setdefault('links', {})[proto] = link
            msg = f"已合并到节点 {name}"
        else:
            local_nodes.append({
                "uuid": str(uuid.uuid4()),
                "name": name,
                "links": {proto: link},
                "routing_type": 1,
                "origin": "local",
                "is_fixed": False,
                "sort_index": 99999
            })
            msg = f"自动添加节点 {name}"
        save_local_nodes(local_nodes)
        sync_nodes_to_files()
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/raw/<int:routing_type>')
def download_raw_subscription(routing_type):
    verify_request_token()
    filename = '0.yaml' if routing_type == 0 else '1.yaml'
    path = os.path.join(get_nodes_dir(), filename)
    if not os.path.exists(path): sync_nodes_to_files()
    content = "proxies: []"
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f: content = f.read()
    resp = make_response(content)
    resp.mimetype = "text/yaml; charset=utf-8"
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp

@bp.route('/list/<list_type>')
def download_rule_list(list_type):
    verify_request_token()
    filename = 'direct.list' if list_type == 'direct' else 'customize.list'
    path = os.path.join(get_nodes_dir(), filename)
    if not os.path.exists(path): path += '.txt'
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f: return Response(f.read(), mimetype='text/plain')
    return "", 404

@bp.route('/api/rules', methods=['GET', 'POST'])
@login_required
def handle_rules():
    filename = request.args.get('file')
    if filename not in ['direct.list', 'customize.list', 'install-singbox.sh']: return jsonify({'error': 'invalid'}), 400
    path = os.path.join(get_nodes_dir(), filename)
    if request.method == 'GET':
        if not os.path.exists(path): return jsonify({'content': ''})
        with open(path, 'r', encoding='utf-8') as f: return jsonify({'status': 'success', 'content': f.read()})
    else:
        content = request.get_json().get('content', '')
        if filename.endswith('.sh'): content = content.replace('\r\n', '\n')
        with open(path, 'w', encoding='utf-8') as f: f.write(content)
        return jsonify({'status': 'success'})

@bp.route('/api/rule_template', methods=['GET', 'POST'])
@login_required
def handle_rule_template():
    path = os.path.join(get_nodes_dir(), 'clash_meta.yaml')
    if request.method == 'GET':
        if not os.path.exists(path): return jsonify({'content': ''})
        with open(path, 'r', encoding='utf-8') as f: return jsonify({'status': 'success', 'content': f.read()})
    else:
        with open(path, 'w', encoding='utf-8') as f: f.write(request.get_json().get('content', ''))
        return jsonify({'status': 'success'})