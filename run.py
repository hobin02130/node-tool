from app import create_app

# 创建应用实例
app = create_app()

if __name__ == '__main__':
    # 启动开发服务器
    # 🚨 关键修改: 设置 use_reloader=False
    # 这样可以禁用 Werkzeug 重载器，确保只有一个进程启动 APScheduler。
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)