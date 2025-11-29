import sys
import os

def get_base_path():
    """
    获取资源的基础路径。
    如果程序被打包（Frozen），则返回临时解压目录。
    如果程序是直接运行（Live），则返回当前脚本所在目录。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的运行时临时目录
        return sys._MEIPASS
    else:
        # 开发环境：返回项目根目录 (假设此文件在 app/utils 下，根目录需往上两层)
        # 注意：这里根据你的实际目录结构可能需要调整 os.path.dirname 的层数
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_external_config_path(filename=None):
    """
    获取外部配置文件的路径（即不打包进 exe 的文件）。
    这些文件应该位于 exe 的同级目录下。
    """
    if getattr(sys, 'frozen', False):
        # 打包后：使用可执行文件所在的真实目录
        base_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境：使用项目根目录
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    if filename:
        return os.path.join(base_dir, filename)
    return base_dir

def get_internal_asset_path(relative_path):
    """
    获取内部资源路径（HTML, CSS, JS, 内部模板）。
    这些文件会被打包进 exe。
    Example: get_internal_asset_path('app/static/css/style.css')
    """
    base_path = get_base_path()
    return os.path.join(base_path, relative_path)

# 使用示例：
# 1. 读取 bundled 的 HTML (Flask 默认会自动处理 templates，但如果你有自定义读取):
#    path = get_internal_asset_path('app/templates/base.html')
#
# 2. 读取外部的 yaml 配置 (例如 app/subscription/nodes/clash_meta.yaml):
#    path = get_external_config_path('nodes/clash_meta.yaml') 
#    注意：打包后你需要手动把 nodes 文件夹放到 exe 旁边