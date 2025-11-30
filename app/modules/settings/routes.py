# app/modules/settings/routes.py

from flask import render_template, request, flash, redirect, url_for, current_app, jsonify
from flask_login import login_required, logout_user, current_user
from app.modules.settings import settings_bp
from app.utils.db_manager import get_all_configs, set_config, update_user_password, get_total_nodes, get_db_file_size 
import os
import json
import requests
from sqlalchemy import create_engine, text

# 区分数据库类型的估算常数
# SQLite 结构较紧凑，每条记录约 200 字节
EST_BYTES_PER_RECORD_SQLITE = 200
# PostgreSQL 包含 HeapTupleHeader(23B)、页对齐填充及索引开销，约 250 字节
EST_BYTES_PER_RECORD_PSQL = 250 

# 一天的总分钟数
MINUTES_PER_DAY = 24 * 60 

# 获取 db_config.json 的绝对路径
# --- 修改开始：增强路径获取逻辑 ---
def get_db_config_path():
    """
    获取 db_config.json 的绝对路径。
    优先检查 Docker 容器的标准挂载路径，防止因 root_path 偏移导致写入错误位置。
    """
    docker_std_path = '/app/db_config.json'
    if os.path.exists(docker_std_path):
        return docker_std_path

    return os.path.abspath(os.path.join(current_app.root_path, '..', 'db_config.json'))

# 读取数据库配置文件
def load_db_config_file():
    # 读取数据库配置文件
    config_path = get_db_config_path()
    default_config = {
        "db_mode": "sqlite",
        "sqlite_path": "app.db",
        "psql_config": {
            "host": "localhost", "port": "5432", "user": "postgres", "password": "", "database": "komari_db"
        }
    }
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading db_config.json: {e}")
    return default_config

# 写入数据库配置文件
def save_db_config_file(config_data):
    # 写入数据库配置文件
    config_path = get_db_config_path()
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
        return True
    except Exception as e:
        print(f"Error writing db_config.json: {e}")
        return False

# 通用 API URL 连通性测试接口
@settings_bp.route('/test_general_api_connectivity', methods=['POST'])
@login_required
def test_general_api_connectivity():
    """
    接收前端传来的 URL，后端尝试发起请求以检测连通性
    """
    data = request.json
    target_url = data.get('url', '').strip()
    
    if not target_url:
        return jsonify({'status': 'error', 'message': '❌ 未找到有效的 URL 地址，请检查输入框'})

    if not target_url.startswith(('http://', 'https://')):
        return jsonify({'status': 'error', 'message': '❌ URL 格式错误，必须以 http:// 或 https:// 开头'})

    try:
        # 设置超时时间为 5 秒，避免卡死
        response = requests.get(target_url, timeout=5)
        
        # 只要有响应（即使是 404 或 403），说明网络是通的，服务是活的
        # 如果需要严格检查状态码 200，可以改为 if response.status_code == 200:
        status_code = response.status_code
        
        if 200 <= status_code < 400:
             return jsonify({'status': 'success', 'message': f'✅ 连接成功 (状态码: {status_code})'})
        else:
             return jsonify({'status': 'warning', 'message': f'⚠️ 连接通畅但返回异常状态 (状态码: {status_code})'})
             
    except requests.exceptions.Timeout:
        return jsonify({'status': 'error', 'message': '❌ 连接超时 (5s)，目标服务器无响应'})
    except requests.exceptions.ConnectionError:
        return jsonify({'status': 'error', 'message': '❌ 连接失败，无法解析主机或目标拒绝连接'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'❌ 检测出错: {str(e)}'})

@settings_bp.route('/general', methods=['GET', 'POST'])
@login_required
def general_settings():
    """
    通用设置页面。
    功能：处理设置保存，并计算存储估算数据。
    """
    
    # 1. 获取数据库中所有的配置项 (AppSetting 对象列表)
    all_configs = get_all_configs() # 获取所有配置项
    
    # === 处理通用设置表单提交 (POST) ===
    if request.method == 'POST':
        # 遍历数据库中已知的配置项
        for config in all_configs:
            key = config.key
            # 检查表单中是否提交了这个 Key 的数据
            if key in request.form:
                value = request.form.get(key)
                cleaned_value = value.strip() if value is not None else ''
                
                # 简单的类型与健壮性判断 (此处逻辑保持不变，确保文本字段能保存空值)
                is_text_field = False
                key_upper = key.upper()
                # 即使不需要判断类型，我们也需要确保保存逻辑对所有字段都兼容
                if any(x in key_upper for x in ['URL', 'TITLE', 'NAME', 'LINK', 'API_TOKEN', 'FIXED_DOMAIN']):
                    is_text_field = True

                # 保存逻辑
                if is_text_field or cleaned_value:
                    set_config(key, cleaned_value)

        flash('通用系统设置已保存', 'success')
        return redirect(url_for('settings.general_settings'))

    # === 处理页面显示 (GET) ===
    
    config_items = []
    acquisition_interval = 15
    
    for config in all_configs:
        key = config.key
        
        # 保持对采集间隔的特殊处理，用于后端的计算，但前端仍将显示为 text
        if key == 'ACQUISITION_INTERVAL_MINUTES':
            try:
                # 确保获取采集间隔的值用于下面的计算
                val = int(config.value)
                if val > 0: acquisition_interval = val
            except (ValueError, TypeError):
                acquisition_interval = 15 
        
        # 核心修改：将所有字段的 input_type 强制设置为 'text'
        input_type = 'text' 
        
        # 移除所有类型判断，所有字段（包括采集间隔）在前端都将是 text 类型。
        
        config_items.append({
            'key': key,
            'description': config.description if config.description else key, 
            'value': config.value, # 确保这里的 value 字段包含了数据库中的值
            'input_type': input_type # 传入修正后的输入类型 'text'
        })
    
    # 2. 【存储空间计算】
    total_nodes = get_total_nodes() 
    if acquisition_interval == 0:
        acquisitions_per_day = 0
    else:
        acquisitions_per_day = MINUTES_PER_DAY // acquisition_interval
        
    total_records_per_day = total_nodes * acquisitions_per_day
    
    # 根据当前运行的数据库类型选择估算因子
    current_db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'postgresql' in current_db_uri:
        bytes_per_record = EST_BYTES_PER_RECORD_PSQL
    else:
        bytes_per_record = EST_BYTES_PER_RECORD_SQLITE

    # 使用选定的因子进行计算
    total_bytes_per_day = total_records_per_day * bytes_per_record
    total_mb_per_day = total_bytes_per_day / (1024 * 1024)
    actual_db_size = get_db_file_size()
    
    storage_stats = {
        'total_nodes': total_nodes,
        'interval_minutes': acquisition_interval,
        'acquisitions_per_day': acquisitions_per_day,
        'records_per_day': total_records_per_day,
        'mb_per_day': f"{total_mb_per_day:.2f}",
        'actual_db_size': actual_db_size,
    }

    # 3. 读取当前的数据库文件配置，传递给前端
    current_db_config = load_db_config_file()

    # 4. 渲染模板
    return render_template('settings.html', 
                           config_items=config_items,
                           storage_stats=storage_stats,
                           db_config=current_db_config)

# 测试数据库连接的 API
@settings_bp.route('/test_db_connection', methods=['POST'])
@login_required
def test_db_connection_api():
    # 测试数据库连接的 API
    data = request.json
    db_mode = data.get('db_mode')
    
    if db_mode != 'psql':
        return jsonify({'status': 'success', 'message': 'SQLite 模式无需测试连接'})

    host = data.get('pg_host', 'localhost')
    port = data.get('pg_port', '5432')
    user = data.get('pg_user', 'postgres')
    password = data.get('pg_password', '')
    dbname = data.get('pg_db', 'komari_db')

    # 构建连接字符串
    uri = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    
    try:
        # 尝试建立短连接
        engine = create_engine(uri, connect_args={'connect_timeout': 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({'status': 'success', 'message': '✅ 连接成功！数据库配置有效。'})
    except Exception as e:
        error_msg = str(e)
        if 'password' in error_msg: error_msg = "密码认证失败"
        elif 'database' in error_msg: error_msg = f"数据库 '{dbname}' 不存在，请先手动创建"
        elif 'Connection refused' in error_msg: error_msg = "连接被拒绝 (请检查主机和端口)"
        return jsonify({'status': 'error', 'message': f'❌ 连接失败: {error_msg}'})

# 保存配置前增加强制检测
@settings_bp.route('/save_db_settings', methods=['POST'])
@login_required
def save_database_settings():
    """
    处理 db_config.json 的保存 (带连通性检查)
    """
    db_mode = request.form.get('db_mode', 'sqlite')
    
    # 提取 PostgreSQL 配置
    pg_host = request.form.get('pg_host', 'localhost')
    pg_port = request.form.get('pg_port', '5432')
    pg_user = request.form.get('pg_user', 'postgres')
    pg_password = request.form.get('pg_password', '')
    pg_db = request.form.get('pg_db', 'komari_db')

    # --- 关键逻辑：如果是 PSQL 模式，保存前必须通过连接测试 ---
    if db_mode == 'psql':
        uri = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
        try:
            engine = create_engine(uri, connect_args={'connect_timeout': 5})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            # 测试通过，继续保存
        except Exception as e:
            print(f"DB Connection Check Failed: {e}")
            flash('❌ 保存失败：无法连接到 PostgreSQL 数据库。请检查参数或先点击“测试连接”。', 'error')
            return redirect(url_for('settings.general_settings'))

    # 构建新的配置字典
    new_config = {
        "db_mode": db_mode,
        "sqlite_path": "app.db", 
        "psql_config": {
            "host": pg_host,
            "port": pg_port,
            "user": pg_user,
            "password": pg_password,
            "database": pg_db
        }
    }

    # 写入文件
    if save_db_config_file(new_config):
        flash('✅ 数据库配置已保存！请重启程序以使更改生效。', 'success')
    else:
        flash('配置文件写入失败，请检查文件权限', 'error')
        
    return redirect(url_for('settings.general_settings'))


@settings_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """
    处理修改密码请求
    """
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if not new_password or not confirm_password:
        flash('密码不能为空', 'error')
        return redirect(url_for('settings.general_settings'))
    
    if new_password != confirm_password:
        flash('两次输入的密码不一致', 'error')
        return redirect(url_for('settings.general_settings'))

    if update_user_password(current_user.id, new_password):
        logout_user()
        flash('密码修改成功，请使用新密码重新登录', 'success')
        return redirect(url_for('auth.login'))
    else:
        flash('修改密码失败，请重试', 'error')
        return redirect(url_for('settings.general_settings'))
