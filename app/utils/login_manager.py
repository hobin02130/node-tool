# 文件路径：./app/utils/login_manager.py

from flask_login import LoginManager
# 【更新导入】需要导入 db 实例才能执行现代 SQLAlchemy 查询
from app.utils.db_manager import User, db 
from sqlalchemy import select # 导入 select 函数用于构建查询

# 定义 login_manager：LoginManager 实例，用于管理用户登录状态
login_manager = LoginManager()
# 设置登录页面的端点名称，格式为 '蓝图名称.视图函数名'
login_manager.login_view = 'auth.login' 
# 设置未登录时的提示信息
login_manager.login_message = "请登录以访问此页面。"
# 设置提示信息的分类，以便在模板中显示
login_manager.login_message_category = 'warning' 

# 定义用户加载函数：用于从会话中存储的用户ID加载用户对象
@login_manager.user_loader
def load_user(user_id):
    """
    Flask-Login 需要此函数来从会话中获取用户ID并加载用户对象。
    """
    # 确保 user_id 可以转换为整数
    try:
        user_id_int = int(user_id)
    except ValueError:
        return None

    # 【重要修复】使用现代 SQLAlchemy 2.0 风格的查询方法
    # db.select(User) 构建查询，.filter_by(id=...) 添加条件
    # .scalar_one_or_none() 执行查询并返回结果或 None
    stmt = select(User).filter_by(id=user_id_int)
    return db.session.execute(stmt).scalar_one_or_none()