/**
 * shared/sidebar.js — 侧边栏组件
 *
 * 用法：
 *   <div id="sidebar-container"></div>
 *   <script type="module">
 *     import { initSidebar } from './assets/sidebar.js';
 *     initSidebar('chat'); // 高亮当前页面对应的 nav-item
 *   </script>
 *
 * initSidebar 会自动：
 *   1. 渲染侧边栏 HTML
 *   2. 高亮当前页面对应的导航项
 *   3. 在首页显示用户信息和退出登录按钮
 *   4. 调用 lucide.createIcons() 初始化图标
 */

const NAV_ITEMS = [
    { page: 'index',    href: 'index.html',    icon: 'home',            label: '首页' },
    { page: 'chat',     href: 'chat.html',     icon: 'message-circle',  label: '智能对话' },
    { page: 'profile',  href: 'profile.html',  icon: 'user',            label: '我的画像' },
    { page: 'generate', href: 'generate.html', icon: 'sparkles',        label: '生成资源' },
    { page: 'pathway',  href: 'pathway.html',  icon: 'map',             label: '学习路径' },
    { page: 'library',  href: 'library.html',  icon: 'book-open',       label: '资源库' },
    { page: 'evaluate', href: 'evaluate.html', icon: 'clipboard-check', label: '学习评估' },
];

function createSidebarHTML(currentPage) {
    const itemsHTML = NAV_ITEMS.map(item => {
        const activeClass = item.page === currentPage ? ' active' : '';
        return `<a href="${item.href}" class="nav-item${activeClass}"><span class="icon"><i data-lucide="${item.icon}"></i></span><span>${item.label}</span></a>`;
    }).join('\n            ');

    const showFooter = currentPage === 'index';

    return `
        <nav class="sidebar">
            <div class="sidebar-logo">个性化学习助手</div>
            ${itemsHTML}
            ${showFooter ? `
            <div class="sidebar-footer">
                <div class="user-info" id="user-info">加载中...</div>
                <button class="btn-logout" onclick="handleLogout()">退出登录</button>
            </div>` : ''}
        </nav>`;
}

export function initSidebar(currentPage) {
    const container = document.getElementById('sidebar-container');
    if (!container) {
        console.warn('[sidebar] 未找到 #sidebar-container 元素，跳过侧边栏初始化');
        return;
    }

    container.innerHTML = createSidebarHTML(currentPage);

    // 首页：加载用户信息
    if (currentPage === 'index') {
        import('./api.js').then(({ getUserId, isLoggedIn }) => {
            if (isLoggedIn()) {
                const userId = getUserId();
                const el = document.getElementById('user-info');
                if (el) el.textContent = `用户 ID：${userId}`;
            }
        }).catch(() => {
            const el = document.getElementById('user-info');
            if (el) el.textContent = '未登录';
        });
    }

    // 初始化图标
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

/**
 * 退出登录：清除认证信息并跳转到登录页。
 * 绑定到全局 window，供 onclick 调用。
 */
export function handleLogout() {
    import('./api.js').then(({ clearAuth }) => {
        clearAuth();
        window.location.href = 'auth.html';
    });
}

// 挂载到全局
if (typeof window !== 'undefined') {
    window.handleLogout = handleLogout;
}
