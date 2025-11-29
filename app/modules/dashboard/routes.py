from flask import Blueprint, render_template, current_app, request, jsonify
from flask_login import login_required
from datetime import datetime

# 导入 db_manager 中封装的函数
from app.utils.db_manager import (
    get_nodes_with_latest_traffic,
    get_total_consumed_traffic_summary,
    update_node_details,
    delete_node_by_uuid, 
    get_config
)

bp = Blueprint('dashboard', __name__, url_prefix='/dashboard', template_folder='templates')

@bp.route('/')
@login_required
def index():
    """仪表盘主页"""
    
    # 🚨 修正逻辑：
    # 因为数据库直接存储了 Emoji 图标，不需要再进行代码转图标的映射。
    # 直接返回 region_code 即可。
    def get_emoji_flag(region_code):
        if region_code and region_code.strip():
            return region_code.strip()
        # 如果数据库该字段为空，返回默认地球图标
        return '🌐'
        
    current_app.jinja_env.filters['flag'] = get_emoji_flag
    
    nodes_with_history = get_nodes_with_latest_traffic()
    
    total_limit_bytes = 0
    for node, _ in nodes_with_history:
        total_limit_bytes += node.traffic_limit
        
    summary = get_total_consumed_traffic_summary(top_limit=5)
    summary['total_traffic_limit'] = total_limit_bytes
    
    komari_url = get_config('KOMARI_BASE_URL', '#')
    
    return render_template('dashboard.html', 
                           nodes=nodes_with_history, 
                           summary=summary,
                           komari_url=komari_url,
                           now=datetime.now())

# 🚨 API: 删除节点
@bp.route('/api/delete_node', methods=['POST'])
@login_required
def delete_node_api():
    try:
        data = request.get_json()
        uuid = data.get('uuid')
        
        if not uuid:
            return jsonify({'status': 'error', 'message': '缺少 UUID'}), 400
            
        success = delete_node_by_uuid(uuid)
        
        if success:
            return jsonify({'status': 'success', 'message': '节点及历史数据已删除'})
        else:
            return jsonify({'status': 'error', 'message': '删除失败或节点不存在'}), 500
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 🚨 API：更新节点详情
@bp.route('/api/update_node', methods=['POST'])
@login_required
def update_node_api():
    try:
        data = request.get_json()
        uuid = data.get('uuid')
        links = data.get('links', {})
        if not isinstance(links, dict): links = {}
        try: routing_type = int(data.get('routing_type', 0))
        except: routing_type = 0
        custom_name = data.get('custom_name', '').strip()
        
        if not uuid: return jsonify({'status': 'error', 'message': '缺少 UUID'}), 400
            
        success = update_node_details(uuid, links, routing_type, custom_name)
        
        if success:
            return jsonify({'status': 'success', 'message': '节点更新成功'})
        else:
            return jsonify({'status': 'error', 'message': '数据库更新失败'}), 500
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500