from flask import Blueprint, render_template, jsonify, request, current_app
from flask_login import login_required
from datetime import datetime, timedelta
import traceback

# 导入 db_manager 模型和数据库对象
from app.utils.db_manager import db, HistoryData, get_all_nodes

bp = Blueprint('history', __name__, url_prefix='/history', template_folder='templates')

@bp.route('/')
@login_required
def view_history():
    """历史统计页面主页"""
    nodes = get_all_nodes()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('history.html', nodes=nodes, default_date=today)

@bp.route('/api/chart_data')
@login_required
def chart_data_api():
    """
    API: 获取图表数据 (包含每小时消耗 + 累计趋势) + 所有节点当日排名数据
    """
    uuid = request.args.get('uuid')
    date_str = request.args.get('date')
    
    if not uuid or not date_str:
        return jsonify({'status': 'error', 'message': '缺少参数'}), 400

    try:
        # 解析日期范围
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        start_time = datetime.combine(target_date, datetime.min.time())
        end_time = datetime.combine(target_date, datetime.max.time())

        # =================================================
        # 1. 查询选中节点的历史记录
        # =================================================
        # 确保 UUID 是字符串进行比较
        uuid = str(uuid)
        
        chart_records = HistoryData.query.filter(
            HistoryData.uuid == uuid,
            HistoryData.timestamp >= start_time,
            HistoryData.timestamp <= end_time
        ).order_by(HistoryData.timestamp.asc()).all()
        
        # 临时存储全量数据的列表
        raw_times = []
        raw_uploads = []
        raw_downloads = []
        raw_totals = [] 
        
        # 初始化24小时的数据桶
        hourly_stats = {h: {'up': 0.0, 'down': 0.0} for h in range(24)}
        
        if chart_records:
            # A. 计算累计趋势 (基于全量数据计算，保证准确性)
            base_up = chart_records[0].total_up
            base_down = chart_records[0].total_down
            
            prev_record = chart_records[0]

            for r in chart_records:
                # --- 1. 累计数据计算 ---
                raw_times.append(r.timestamp.strftime('%H:%M'))
                
                curr_up = r.total_up - base_up
                curr_down = r.total_down - base_down
                
                # 处理重启归零 (如果当前总流量小于基准，说明重启过，直接取当前值作为新基准的偏移)
                # 这种简单的处理方式在重启瞬间会有跳变，但能保证后续增量正确
                if curr_up < 0: curr_up = r.total_up
                if curr_down < 0: curr_down = r.total_down
                
                # 转换为 GB
                val_up = curr_up / 1024 / 1024 / 1024
                val_down = curr_down / 1024 / 1024 / 1024
                
                raw_uploads.append(val_up)
                raw_downloads.append(val_down)
                raw_totals.append(val_up + val_down)

                # --- 2. 每小时增量计算 ---
                if r != prev_record:
                    delta_up = r.total_up - prev_record.total_up
                    delta_down = r.total_down - prev_record.total_down
                    
                    if delta_up < 0: delta_up = r.total_up
                    if delta_down < 0: delta_down = r.total_down
                    
                    hour = r.timestamp.hour
                    hourly_stats[hour]['up'] += delta_up
                    hourly_stats[hour]['down'] += delta_down
                
                prev_record = r

        # 数据抽样 (Downsampling)
        # 如果数据点过多(例如超过200个)，前端渲染会非常卡顿甚至不显示
        # 我们在这里进行均匀抽样，只返回约 150 个点给前端
        MAX_POINTS = 150
        total_points = len(raw_times)
        
        if total_points > MAX_POINTS:
            step = total_points // MAX_POINTS
            # 使用切片进行抽样
            final_times = raw_times[::step]
            final_uploads = [round(x, 4) for x in raw_uploads[::step]]
            final_downloads = [round(x, 4) for x in raw_downloads[::step]]
            final_totals = [round(x, 4) for x in raw_totals[::step]]
            
            # 确保最后一个点总是包含在内，显示最新状态
            if total_points > 0 and (total_points - 1) % step != 0:
                final_times.append(raw_times[-1])
                final_uploads.append(round(raw_uploads[-1], 4))
                final_downloads.append(round(raw_downloads[-1], 4))
                final_totals.append(round(raw_totals[-1], 4))
        else:
            # 数据量不大，直接保留并取整
            final_times = raw_times
            final_uploads = [round(x, 4) for x in raw_uploads]
            final_downloads = [round(x, 4) for x in raw_downloads]
            final_totals = [round(x, 4) for x in raw_totals]

        # 格式化每小时数据
        bar_hours = [f"{h:02d}:00" for h in range(24)]
        bar_up = [round(hourly_stats[h]['up'] / 1024 / 1024 / 1024, 4) for h in range(24)]
        bar_down = [round(hourly_stats[h]['down'] / 1024 / 1024 / 1024, 4) for h in range(24)]

        # =================================================
        # 2. 生成所有节点的当日用量排名
        # =================================================
        all_nodes = get_all_nodes()
        ranking_data = []
        
        # 预先获取当前选择的节点 ID (确保是字符串)
        current_uuid_str = str(uuid)

        for node in all_nodes:
            node_uuid_str = str(node.uuid)
            try:
                # 优化查询：只查头尾，避免全表扫描
                # 注意：在 PG 中这里的查询如果数据量巨大可能会慢，但通常有索引 idx_node_timestamp 会很快
                first = HistoryData.query.filter(
                    HistoryData.uuid == node_uuid_str, 
                    HistoryData.timestamp >= start_time
                ).order_by(HistoryData.timestamp.asc()).first()
                
                last = HistoryData.query.filter(
                    HistoryData.uuid == node_uuid_str, 
                    HistoryData.timestamp <= end_time
                ).order_by(HistoryData.timestamp.desc()).first()
                
                usage_total = 0
                usage_up = 0
                usage_down = 0
                
                if first and last:
                    d_up = last.total_up - first.total_up
                    d_down = last.total_down - first.total_down
                    
                    if d_up < 0: d_up = last.total_up
                    if d_down < 0: d_down = last.total_down
                    
                    usage_up = round(d_up / 1024 / 1024 / 1024, 3)
                    usage_down = round(d_down / 1024 / 1024 / 1024, 3)
                    usage_total = round(usage_up + usage_down, 3)
                
                ranking_data.append({
                    'name': node.custom_name or node.name,
                    'uuid': node_uuid_str, 
                    'region': node.region,
                    'usage': usage_total,
                    'up': usage_up,
                    'down': usage_down,
                    'is_current': (node_uuid_str == current_uuid_str)
                })
            except Exception as e:
                # 捕获单个节点查询错误，防止整个接口崩溃
                print(f"Error processing node {node.name}: {e}")
                continue
            
        # 降序排列
        ranking_data.sort(key=lambda x: x['usage'], reverse=True)

        return jsonify({
            'status': 'success',
            'data': {
                'line': {
                    'times': final_times,
                    'uploads': final_uploads,
                    'downloads': final_downloads,
                    'totals': final_totals
                },
                'bar': {
                    'hours': bar_hours,
                    'up': bar_up,
                    'down': bar_down
                },
                'ranking': ranking_data
            }
        })

    except Exception as e:
        print(f"API Error: {e}")
        traceback.print_exc() # 打印完整堆栈信息到控制台，方便调试
        return jsonify({'status': 'error', 'message': str(e)}), 500
