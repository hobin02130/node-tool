from flask_apscheduler import APScheduler

# 初始化全局调度器实例
# 所有的定时任务都通过这个对象管理，确保它独立于 HTTP 请求周期运行。
# 这个实例会被 app/__init__.py 导入并初始化。
scheduler = APScheduler()