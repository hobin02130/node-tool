from app import create_app

# 创建应用实例
app = create_app()

if __name__ == '__main__':
    # 启动开发服务器

    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
