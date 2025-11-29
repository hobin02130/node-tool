# 使用 Python 3.9 作为基础镜像
# 这是一个精简版的 Python 环境，适合打包
FROM python:3.9-slim-bullseye

# 设置容器内的工作目录
WORKDIR /app

# 🟢 [关键] 安装系统依赖
# PyInstaller 和 psycopg2 (即使是 binary 版) 在 Linux 下都需要这些库
# libpq-dev: 用于 PostgreSQL 支持
# binutils: PyInstaller 需要
# gcc/libc6-dev: 编译部分 Python 库可能需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    binutils \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 1. 先复制依赖文件并安装 (利用 Docker 缓存层加速构建)
COPY requirements.txt .

# 2. 安装 Python 依赖
# --no-cache-dir: 减小镜像体积
RUN pip install --no-cache-dir -r requirements.txt
# 单独安装 PyInstaller (因为它可能不在 requirements.txt 里，或者是构建工具而非运行依赖)
RUN pip install --no-cache-dir pyinstaller

# 3. 复制项目的所有代码文件到镜像中
COPY . .

# 4. 设置默认命令
# 当容器运行时，会自动执行这个命令来打包
CMD ["python", "build.py"]
