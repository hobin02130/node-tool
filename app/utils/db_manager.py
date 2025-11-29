from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
# 🚨 [修改] 引入 text 用于执行原生 SQL，引入 IntegrityError 用于捕获主键冲突
from sqlalchemy import desc, func, case, BigInteger, literal_column, text
from sqlalchemy.exc import IntegrityError
from flask_login import UserMixin
import json
import os

# =========================================================
#  第一部分：基础初始化
# =========================================================
db = SQLAlchemy()

# =========================================================
#  第二部分：数据库模型定义 (Models)
# =========================================================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64)) 
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = password

    def check_password(self, password):
        if self.password_hash is None:
            return False
        return self.password_hash == password

class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)
    description = db.Column(db.String(255))


class Node(db.Model):
    __tablename__ = 'nodes'
    uuid = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(128))
    custom_name = db.Column(db.String(128))
    region = db.Column(db.String(16)) 
    expired_at = db.Column(db.DateTime)
    weight = db.Column(db.Integer, default=0)
    traffic_limit = db.Column(db.BigInteger)
    
    # 链接字段 (JSON) - 兼容 SQLite/PG 使用 Text
    links = db.Column(db.Text, default='{}')
    
    # 路由类型 (0:直连, 1:落地)
    routing_type = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    # cascade='all, delete-orphan' 确保删除 Node 时自动删除关联的 HistoryData
    history_data = db.relationship('HistoryData', backref='node', lazy='dynamic', cascade='all, delete-orphan')

    def get_links_dict(self):
        try:
            return json.loads(self.links) if self.links else {}
        except:
            return {}

class HistoryData(db.Model):
    __tablename__ = 'history_data'
    __table_args__ = (db.Index('idx_node_timestamp', 'uuid', 'timestamp'),)
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), db.ForeignKey('nodes.uuid'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)
    total_up = db.Column(db.BigInteger)
    total_down = db.Column(db.BigInteger)
    cpu_usage = db.Column(db.Float)


# =========================================================
#  第三部分：全局操作接口 (Operations / DAO)
# =========================================================

# --- 1. 配置相关操作 ---

def get_config(key, default=None):
    try:
        setting = AppSetting.query.get(key)
        return setting.value if setting else default
    except Exception as e:
        print(f"Error reading config {key}: {e}")
        return default

def set_config(key, value, description=None):
    try:
        setting = AppSetting.query.get(key)
        if not setting:
            setting = AppSetting(key=key)
            db.session.add(setting)
        setting.value = str(value)
        if description:
            setting.description = description
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error setting config {key}: {e}")
        return False

def get_all_configs():
    try:
        return AppSetting.query.all()
    except Exception as e:
        print(f"Error reading all configs: {e}")
        return []

def get_db_file_size():
    """
    [读] 获取数据库占用大小（MB）。
    自动判断是 SQLite 文件大小 还是 PostgreSQL 数据库占用。
    """
    try:
        # 获取驱动名称
        driver = db.engine.url.drivername
        
        # 情况 A: PostgreSQL
        if 'postgresql' in driver:
            # 使用 SQL 查询获取当前数据库大小
            sql = text("SELECT pg_database_size(current_database());")
            result = db.session.execute(sql).scalar()
            if result:
                size_mb = round(result / (1024 * 1024), 2)
                return f"{size_mb} MB"
                
        # 情况 B: SQLite
        elif 'sqlite' in driver:
            db_uri = db.engine.url.database
            if db_uri:
                # 处理相对路径
                from flask import current_app
                if not os.path.isabs(db_uri):
                    db_path = os.path.join(current_app.root_path, '..', db_uri)
                else:
                    db_path = db_uri
                
                db_path = os.path.abspath(db_path)
                
                if os.path.exists(db_path):
                    size_bytes = os.path.getsize(db_path)
                    return f"{round(size_bytes / (1024 * 1024), 2)} MB"
        
        return "0.00 MB"
    except Exception as e:
        print(f"Error getting database size: {e}")
        return "计算失败"

# --- 2. 节点相关操作 ---

def upsert_node(node_info):
    """[写] 更新或插入节点信息 (通常由 Komari 同步任务调用)"""
    try:
        uuid = node_info.get('uuid')
        node = Node.query.get(uuid)
        
        if not node:
            node = Node(uuid=uuid)
            db.session.add(node)
        
        node.name = node_info.get('name')
        if 'custom_name' in node_info:
            node.custom_name = node_info.get('custom_name')
        elif not node.custom_name:
            node.custom_name = node_info.get('name')
            
        node.region = node_info.get('region')
        node.traffic_limit = node_info.get('traffic_limit', 0)
        
        expired_at_str = node_info.get('expired_at')
        if expired_at_str:
            try:
                # 兼容 ISO 格式的时间字符串
                if expired_at_str.endswith('Z'):
                    expired_at_str = expired_at_str[:-1]
                node.expired_at = datetime.fromisoformat(expired_at_str)
            except ValueError as ve:
                print(f"Warning: Failed to parse datetime string '{expired_at_str}': {ve}")
                node.expired_at = None
        else:
            node.expired_at = None
        
        node.weight = node_info.get('weight')
        
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error upserting node: {e}")
        return False

def get_total_nodes():
    try:
        return Node.query.count()
    except Exception as e:
        print(f"Error getting total nodes: {e}")
        return 0

def get_all_nodes():
    return Node.query.order_by(Node.weight.desc()).all()

def get_node(uuid):
    return Node.query.get(uuid)

def update_node_custom_name(uuid, custom_name):
    try:
        node = Node.query.get(uuid)
        if node:
            node.custom_name = custom_name
            db.session.commit()
            return True
        return False
    except Exception as e:
        db.session.rollback()
        print(f"Error updating custom name for node {uuid}: {e}")
        return False

def delete_node_by_uuid(uuid):
    try:
        node = Node.query.get(uuid)
        if node:
            db.session.delete(node)
            db.session.commit()
            return True
        return False
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting node {uuid}: {e}")
        return False

def get_nodes_with_latest_traffic():
    try:
        subquery = db.session.query(
            HistoryData.uuid,
            func.max(HistoryData.timestamp).label('max_timestamp')
        ).group_by(HistoryData.uuid).subquery()
        
        query = db.session.query(Node, HistoryData).outerjoin(
            subquery, Node.uuid == subquery.c.uuid
        ).outerjoin(
            HistoryData, 
            db.and_(
                HistoryData.uuid == subquery.c.uuid, 
                HistoryData.timestamp == subquery.c.max_timestamp
            )
        ).order_by(Node.weight.asc())
        
        return query.all()
    except Exception as e:
        print(f"Error fetching nodes with latest traffic: {e}")
        return []

def update_node_details(uuid, links_dict, routing_type, custom_name):
    try:
        node = Node.query.get(uuid)
        if node:
            node.links = json.dumps(links_dict, ensure_ascii=False)
            node.routing_type = int(routing_type)
            node.custom_name = custom_name
            
            db.session.commit()
            return True
        return False
    except Exception as e:
        db.session.rollback()
        print(f"Error updating node details {uuid}: {e}")
        return False

def get_total_consumed_traffic_summary(top_limit=5):
    try:
        total_nodes = Node.query.count()

        max_time_per_node = db.session.query(
            HistoryData.uuid,
            func.max(HistoryData.timestamp).label('max_timestamp')
        ).group_by(HistoryData.uuid).subquery()

        latest_history = db.session.query(
            HistoryData.uuid,
            (HistoryData.total_up + HistoryData.total_down).label('total_usage')
        ).join(
            max_time_per_node,
            db.and_(
                HistoryData.uuid == max_time_per_node.c.uuid,
                HistoryData.timestamp == max_time_per_node.c.max_timestamp
            )
        ).subquery()
        
        total_consumed_traffic = db.session.query(
            func.sum(latest_history.c.total_usage)
        ).scalar() or 0
        
        top_nodes_query = db.session.query(
            Node.custom_name,
            Node.name,
            latest_history.c.total_usage.label('total_usage')
        ).join(
            latest_history, Node.uuid == latest_history.c.uuid
        ).order_by(
            desc(literal_column('total_usage'))
        ).limit(top_limit)

        top_nodes_results = top_nodes_query.all()

        return {
            'total_nodes': total_nodes,
            'total_consumed_traffic': int(total_consumed_traffic),
            'top_traffic_nodes': [
                {
                    'name': result.custom_name or result.name,
                    'traffic': int(result.total_usage)
                } 
                for result in top_nodes_results
            ]
        }
    except Exception as e:
        db.session.rollback()
        print(f"Error fetching dashboard summary data: {e}")
        return {
            'total_nodes': 0,
            'total_consumed_traffic': 0,
            'top_traffic_nodes': []
        }

# --- 3. 历史数据相关操作 ---

def get_node_history_by_time_range(uuid, start_time):
    try:
        return HistoryData.query.filter(
            HistoryData.uuid == uuid,
            HistoryData.timestamp >= start_time
        ).order_by(HistoryData.timestamp.asc()).all()
    except Exception as e:
        print(f"Error fetching history for node {uuid}: {e}")
        return []

def get_history_by_date(target_date):
    try:
        if isinstance(target_date, str):
            target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
            
        start_time = datetime.combine(target_date, datetime.min.time())
        end_time = datetime.combine(target_date, datetime.max.time())
        
        records = db.session.query(HistoryData, Node.name, Node.custom_name).join(
            Node, HistoryData.uuid == Node.uuid
        ).filter(
            HistoryData.timestamp >= start_time,
            HistoryData.timestamp <= end_time
        ).order_by(HistoryData.timestamp.asc()).all()
        
        return records
    except Exception as e:
        print(f"Error fetching history by date {target_date}: {e}")
        return []

def add_history_snapshot(uuid, total_up, total_down, cpu):
    try:
        record = HistoryData(
            uuid=uuid,
            total_up=total_up,
            total_down=total_down,
            cpu_usage=cpu,
            timestamp=datetime.now()
        )
        db.session.add(record)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error adding history: {e}")

# 🚨 [关键修复] 增强版批量写入函数
def bulk_add_history(records_list):
    """
    [写] 批量写入历史数据。
    功能：
    1. 手动补充 timestamp，解决 bulk_insert 忽略 default 问题。
    2. [PostgreSQL] 自动捕获 Sequence 不同步错误并修复，防止 ID 冲突。
    """
    try:
        current_time = datetime.now()
        # 遍历列表，确保每条数据都有 timestamp
        for record in records_list:
            if 'timestamp' not in record:
                record['timestamp'] = current_time
        
        db.session.bulk_insert_mappings(HistoryData, records_list)
        db.session.commit()
    
    except IntegrityError as e:
        # 专门捕获完整性错误 (IntegrityError)
        db.session.rollback()
        
        # 检查是否是 PostgreSQL 的 "duplicate key" 错误
        # e.orig 是原始的 DBAPI 异常对象
        err_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
        
        if 'duplicate key value' in err_msg and 'history_data_pkey' in err_msg:
            print(">>> [DB Fix] 检测到 ID 序列不同步，正在自动修复 PostgreSQL 序列...")
            try:
                # 仅针对 PostgreSQL 执行修复
                # 逻辑：将序列值重置为 (当前表中最大ID + 1)
                if 'postgresql' in db.engine.url.drivername:
                    sql_fix = text("SELECT setval(pg_get_serial_sequence('history_data', 'id'), (SELECT COALESCE(MAX(id), 0) + 1 FROM history_data), false);")
                    db.session.execute(sql_fix)
                    db.session.commit()
                    
                    print(">>> [DB Fix] 序列已重置，正在重试写入...")
                    # 修复后立即重试一次
                    db.session.bulk_insert_mappings(HistoryData, records_list)
                    db.session.commit()
                    print(">>> [DB Fix] 重试写入成功！")
                    return
            except Exception as fix_e:
                print(f">>> [DB Fix] 自动修复失败: {fix_e}")
                # 修复失败则抛出原始异常，避免掩盖问题
        
        print(f"Error bulk adding history (IntegrityError): {e}")

    except Exception as e:
        db.session.rollback()
        print(f"Error bulk adding history: {e}")

def get_latest_history(uuid, limit=10):
    return HistoryData.query.filter_by(uuid=uuid)\
        .order_by(desc(HistoryData.timestamp))\
        .limit(limit).all()

# --- 4. 用户相关操作 ---

def get_user_by_username(username):
    try:
        return User.query.filter_by(username=username).first()
    except Exception as e:
        print(f"Error getting user by username: {e}")
        return None

def get_user_by_id(user_id):
    try:
        if user_id is None:
            return None
        return User.query.get(int(user_id))
    except Exception as e:
        print(f"Error getting user by id: {e}")
        return None

def update_user_password(user_id, new_password):
    try:
        user = User.query.get(int(user_id))
        if user:
            user.set_password(new_password)
            db.session.commit()
            return True
        return False
    except Exception as e:
        db.session.rollback()
        print(f"Error updating password: {e}")
        return False