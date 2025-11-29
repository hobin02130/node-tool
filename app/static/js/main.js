// 功能：侧边栏收缩与状态持久化
document.addEventListener('DOMContentLoaded', function() {
    
    // 获取相关 DOM 元素
    const sidebar = document.getElementById('sidebar');
    const toggleBtn = document.getElementById('toggleSidebar');
    
    // 如果页面上没有侧边栏（例如在登录页），则不执行后续逻辑
    if (!sidebar || !toggleBtn) return;

    // 定义存储在 localStorage 中的键名
    const STORAGE_KEY = 'sidebar_collapsed';

    // 1. 初始化检查：页面加载时，读取用户之前的偏好
    const isCollapsed = localStorage.getItem(STORAGE_KEY) === 'true';
    if (isCollapsed) {
        sidebar.classList.add('collapsed');
    }

    // 2. 绑定点击事件
    toggleBtn.addEventListener('click', function() {
        // 切换 collapsed 类
        sidebar.classList.toggle('collapsed');
        
        // 判断当前状态
        const currentState = sidebar.classList.contains('collapsed');
        
        // 保存状态到 localStorage
        localStorage.setItem(STORAGE_KEY, currentState);
    });
});