from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

# 导入 db_manager 中用于查询用户的函数
from app.utils.db_manager import get_user_by_username

# 定义蓝图
# url_prefix='/auth' 表示该模块所有路由都以 /auth 开头
bp = Blueprint('auth', __name__, url_prefix='/auth', template_folder='templates')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    用户登录视图
    GET: 显示登录页面
    POST: 处理登录请求
    """
    # 1. 如果用户已经登录，访问此页面直接跳到仪表盘，防止重复登录
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # 处理 "记住我" 复选框
        remember = request.form.get('remember') == 'on' 

        # 2. 通过 db_manager 接口查询用户
        user = get_user_by_username(username)

        # 3. 验证用户是否存在，以及密码哈希是否匹配
        if user and user.check_password(password):
            # 登录成功，写入 Flask-Login Session
            login_user(user, remember=remember)
            
            flash('登录成功', 'success')
            
            # 【关键修改】
            # 强制重定向到 dashboard.index (仪表盘主页)
            # 忽略 next 参数，防止因 next=/auth/login 导致的循环跳转问题
            return redirect(url_for('dashboard.index'))
            
        else:
            # 登录失败
            flash('用户名或密码错误', 'danger')

    # GET 请求或登录失败后，返回登录模板
    return render_template('login.html')

@bp.route('/logout')
@login_required # 只有已登录用户才能访问
def logout():
    """
    用户登出视图
    """
    logout_user()
    flash('您已退出登录', 'info')
    # 登出后跳转回登录页
    return redirect(url_for('auth.login'))