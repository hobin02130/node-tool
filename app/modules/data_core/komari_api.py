import requests
import json
from datetime import datetime
from flask import Blueprint, jsonify, current_app

# ----------------------------------------------------
# 从 db_manager 导入所有需要的数据库操作接口
# ----------------------------------------------------
from app.utils.db_manager import (
    get_config,          # 用于读取 Komari URL/Token
    upsert_node,         # 用于同步节点列表
    get_all_nodes,       # 用于获取需要监控的节点UUID
    bulk_add_history     # 用于批量写入历史数据 (性能优化)
)

# [新增] 导入全局 scheduler 对象，用于获取绑定的 app 实例
from app.utils.scheduler import scheduler

# ----------------------------------------------------
# 基础配置和辅助函数
# ----------------------------------------------------

def _get_komari_base_url():
    """
    读取 Komari API 的基础 URL。（内部调用 get_config）
    """
    # 优先从配置中读取，如果不存在则返回默认值
    url = get_config('KOMARI_BASE_URL', 'http://127.0.0.1:8888')
    # 确保 URL 末尾没有斜杠
    return url.rstrip('/')

def _get_komari_headers():
    """
    构造 Komari API 请求所需的 HTTP Header (用于认证)。
    """
    # 假设 API Token 存储在配置中
    token = get_config('KOMARI_API_TOKEN', 'YOUR_DEFAULT_TOKEN')
    
    headers = {
        'Accept': 'application/json',
        # 如需认证请取消注释下行，并配置 Token
        # 'Authorization': f'Bearer {token}' 
    }
    return headers

def _extract_nested_value(data, keys, default=0.0):
    """
    辅助函数：安全地从嵌套字典中提取值 (例如 'cpu.usage')
    """
    try:
        # 逐层遍历字典获取值
        for key in keys.split('.'):
            data = data[key]
        return data
    except (KeyError, TypeError):
        return default

# =========================================================
# 核心功能实现
# =========================================================

def sync_node_list():
    """
    [功能一：同步节点列表]
    从远程 API 获取节点列表并更新到本地数据库。
    """
    base_url = _get_komari_base_url()
    url = f"{base_url}/api/nodes"
    headers = _get_komari_headers()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 尝试同步 Komari 节点列表...")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() 
        data = response.json()

        if data.get('status') == 'success':
            node_count = 0
            for node_info in data.get('data', []):
                upsert_node(node_info) # 数据库写操作
                node_count += 1
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 成功同步 {node_count} 个节点信息。")
            return True
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Komari API 返回错误: {data.get('message')}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 连接 Komari API 失败: {e}")
        return False
    except json.JSONDecodeError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 错误：无法解析 Komari API 返回的 JSON 数据。")
        return False
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 同步节点列表发生未知错误: {e}")
        return False

def fetch_and_save_snapshots():
    """
    [功能二：获取节点快照]
    遍历所有节点，获取实时状态并存入历史记录表。
    """
    base_url = _get_komari_base_url()
    
    # 1. 从数据库获取所有活动的节点 UUID
    nodes = get_all_nodes() 
    if not nodes:
        return

    records_to_save = []
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始获取 {len(nodes)} 个节点的快照数据...")

    for node in nodes:
        uuid = node.uuid
        url = f"{base_url}/api/recent/{uuid}"
        headers = _get_komari_headers()

        try:
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            snapshot_data = data.get('data', [])
            if not snapshot_data:
                continue

            # 取最新的一个快照点
            latest_snapshot = snapshot_data[-1] 

            record_info = {
                'uuid': uuid,
                'total_up': _extract_nested_value(latest_snapshot, 'network.totalUp'),
                'total_down': _extract_nested_value(latest_snapshot, 'network.totalDown'),
                'cpu_usage': _extract_nested_value(latest_snapshot, 'cpu.usage'),
            }
            records_to_save.append(record_info)

        except Exception as e:
            # 单个节点失败不影响其他节点
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 获取节点 {uuid} 快照失败: {e}")

    # 2. 批量写入数据库
    if records_to_save:
        bulk_add_history(records_to_save) 
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 成功批量写入 {len(records_to_save)} 条历史快照数据。")

# ----------------------------------------------------
# 定时/手动任务入口 (核心修改部分)
# ----------------------------------------------------

def run_periodic_static_sync():
    """
    [低频任务] 任务入口：仅执行节点静态信息同步 (APScheduler 调用)。
    修正：使用 scheduler.app 获取上下文，兼容 PostgreSQL (解决序列化问题)。
    """
    # 检查 scheduler 是否绑定了 app
    if hasattr(scheduler, 'app') and scheduler.app:
        with scheduler.app.app_context():
            sync_node_list()
    else:
        print(">>> [Error] Scheduler 未绑定 app 实例，无法运行静态同步任务。")

def run_periodic_snapshot_sync():
    """
    [高频任务] 任务入口：仅执行节点快照数据获取 (APScheduler 调用)。
    修正：使用 scheduler.app 获取上下文，兼容 PostgreSQL (解决序列化问题)。
    """
    if hasattr(scheduler, 'app') and scheduler.app:
        with scheduler.app.app_context():
            fetch_and_save_snapshots()
    else:
        print(">>> [Error] Scheduler 未绑定 app 实例，无法运行快照同步任务。")

def run_manual_trigger_task():
    """
    [手动任务] 任务入口：同时执行静态同步和快照获取。
    """
    # 直接调用上述无参函数，它们会自动通过 scheduler.app 获取上下文
    run_periodic_static_sync()
    run_periodic_snapshot_sync()


# =========================================================
# Flask 蓝图和 API 路由定义
# =========================================================

# 定义蓝图
bp = Blueprint('komari_api_bp', __name__, url_prefix='/api/komari')

@bp.route('/manual-refresh', methods=['POST'])
def manual_refresh_api():
    """
    API 接口：触发手动数据同步和快照获取任务。
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 接收到手动刷新 API 请求...")
    try:
        # 调用核心任务函数 (无需传递 app 实例)
        run_manual_trigger_task()
        
        # 返回成功响应
        return jsonify({
            'status': 'success',
            'message': '手动刷新任务已成功触发。'
        }), 200
            
    except Exception as e:
        # 捕获异常，返回错误信息
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 手动刷新任务出错: {e}")
        return jsonify({
            'status': 'error',
            'message': f'手动刷新任务出错: {str(e)}'
        }), 500