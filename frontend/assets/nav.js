/* ============================================================
   nav.js — 悬浮胶囊导航（全站共享）
   用法:
     <script type="module">
       import { initCapNav } from './assets/nav.js';
       initCapNav('index');   // 传入当前页 key 以高亮
     </script>
   依赖: lucide (createIcons)，api.js (getUserId/clearAuth)
   ============================================================ */

const NAV = [
    { key: 'index',    href: 'index.html',    icon: 'layout-dashboard', label: '看板' },
    { key: 'chat',     href: 'chat.html',     icon: 'sparkles',         label: '智能对话' },
    { key: 'generate', href: 'generate.html', icon: 'wand-2',           label: '资源生成' },
    { key: 'library',  href: 'library.html',  icon: 'library',          label: '资源库' },
    { key: 'pathway',  href: 'pathway.html',  icon: 'route',            label: '学习路径' },
    { key: 'evaluate', href: 'evaluate.html', icon: 'clipboard-check',  label: '学习评估' },
    { key: 'profile',  href: 'profile.html',  icon: 'circle-user',      label: '个人中心' },
];

function buildNav(current, userId) {
    const links = NAV.map(n => `
        <a href="${n.href}" class="cap-link${n.key === current ? ' active' : ''}" title="${n.label}">
            <i data-lucide="${n.icon}"></i><span class="cap-label">${n.label}</span>
        </a>`).join('');

    const initial = userId ? userId.charAt(0).toUpperCase() : '?';

    return `
        <nav class="cap-nav" aria-label="主导航">
            <a href="index.html" class="cap-brand">
                <span class="cap-brand-mark"><i data-lucide="atom"></i></span>
                <span>智学实验室</span>
            </a>
            ${links}
            <span class="cap-user">
                <span class="cap-avatar" data-cap-logout title="点击退出登录">${initial}</span>
            </span>
        </nav>`;
}

/**
 * 渲染悬浮胶囊导航。会自动注入到 body 顶部。
 * @param {string} current 当前页 key（index/chat/...）
 */
export function initCapNav(current) {
    let userId = null;
    try { userId = localStorage.getItem('user_id'); } catch (e) { /* ignore */ }

    const host = document.createElement('div');
    host.innerHTML = buildNav(current, userId);
    const navEl = host.firstElementChild;
    document.body.appendChild(navEl);

    // 退出登录
    const avatar = navEl.querySelector('[data-cap-logout]');
    if (avatar) {
        avatar.addEventListener('click', () => {
            try {
                localStorage.removeItem('user_id');
                localStorage.removeItem('access_token');
                localStorage.removeItem('session_id');
            } catch (e) { /* ignore */ }
            window.location.href = 'auth.html';
        });
    }

    if (typeof lucide !== 'undefined') lucide.createIcons();
    return navEl;
}

export default initCapNav;
