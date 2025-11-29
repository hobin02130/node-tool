from flask import Blueprint

# 1. 先定义蓝图对象
settings_bp = Blueprint('settings', __name__, template_folder='templates')

# 2. 最后导入路由 (为了防止循环导入报错，必须放在底部)
from app.modules.settings import routes