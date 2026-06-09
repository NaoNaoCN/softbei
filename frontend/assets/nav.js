/* ============================================================
   nav.js — 持久化侧栏导航（全站共享外壳）v4

   架构：sidebar 是 body 的直接子元素，位于 #view 之外。
   页面切换时 sidebar 保持不动，仅 #view 内容通过 fetch + DOM
   swap 原地替换，配合 document.startViewTransition() 实现
   同文档平滑过渡。

   用法:
     <script type="module">
       import { registerPage, initSidebar } from './assets/nav.js';

       registerPage('index',
         async () => { ... },
         () => { ... }
       );
       initSidebar('index');
     </script>
   ============================================================ */

const NAV = [
    { key: 'index',    href: 'index.html',    icon: 'layout-dashboard', label: '主页' },
    { key: 'chat',     href: 'chat.html',     icon: 'sparkles',         label: 'AI 对话' },
    { key: 'generate', href: 'generate.html', icon: 'wand-2',           label: '资源生成' },
    { key: 'library',  href: 'library.html',  icon: 'library',          label: '资源库' },
    { key: 'pathway',  href: 'pathway.html',  icon: 'route',            label: '知识图谱' },
    { key: 'evaluate', href: 'evaluate.html', icon: 'clipboard-check',  label: '学习评估' },
    { key: 'history',  href: 'history.html',  icon: 'scroll-text',      label: '历史记录' },
    { key: 'profile',  href: 'profile.html',  icon: 'circle-user',      label: '个人中心' },
];

// ============================================================
// 页面注册表
// ============================================================
const _registry = new Map();
let _currentKey = null;

export function registerPage(key, init, destroy) {
    _registry.set(key, { init, destroy });
}

// ============================================================
// 页面 HTML 缓存
// ============================================================
const _pageCache = new Map();

// ============================================================
// 导航核心：fetch → parse → swap → VT
// ============================================================
async function navigateTo(href, pushState = true) {
    const pageName = href.split('/').pop().replace('.html', '');

    if (!_registry.has(pageName)) {
        window.location.href = href;
        return;
    }

    let html = _pageCache.get(href);
    if (!html) {
        try {
            const resp = await fetch(href);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            html = await resp.text();
            _pageCache.set(href, html);
        } catch (err) {
            console.error('[Nav] fetch failed:', err);
            window.location.href = href;
            return;
        }
    }

    const doc = new DOMParser().parseFromString(html, 'text/html');
    const newView = doc.querySelector('#view');
    if (!newView) { window.location.href = href; return; }

    // Destroy current page
    if (_currentKey && _registry.has(_currentKey)) {
        try { await _registry.get(_currentKey).destroy?.(); } catch (e) {
            console.error('[Nav] destroy error:', e);
        }
    }

    const viewEl = document.getElementById('view');
    const newTitle = doc.querySelector('title')?.textContent;

    const update = () => {
        viewEl.innerHTML = newView.innerHTML;
        if (newTitle) document.title = newTitle;
        if (typeof lucide !== 'undefined') lucide.createIcons();
    };

    if (document.startViewTransition) {
        try { await document.startViewTransition(() => update()).finished; } catch (_) { update(); }
    } else {
        update();
    }

    _currentKey = pageName;
    if (pushState) history.pushState({ key: pageName }, '', href);

    if (_registry.has(pageName)) {
        try { await _registry.get(pageName).init?.(); } catch (e) {
            console.error('[Nav] init error:', e);
        }
    }

    window.scrollTo({ top: 0, behavior: 'instant' });
    // Update sidebar active state
    updateSidebarActive(pageName);
}

// ============================================================
// 构建侧栏 HTML
// ============================================================
function buildSidebar(current) {
    const links = NAV.map(n => `
        <a href="${n.href}" class="sidebar-link${n.key === current ? ' active' : ''}" data-key="${n.key}">
            <i data-lucide="${n.icon}"></i><span>${n.label}</span>
        </a>`).join('');

    return `
        <aside class="sidebar">
            <a href="index.html" class="sidebar-brand">
                <span class="sidebar-brand-mark"><i data-lucide="atom"></i></span>
                <span>智学实验室</span>
            </a>
            <nav class="sidebar-nav">${links}</nav>
        </aside>`;
}

function updateSidebarActive(current) {
    const el = document.querySelector('.sidebar');
    if (!el) return;
    el.querySelectorAll('.sidebar-link').forEach(a => {
        a.classList.toggle('active', a.dataset.key === current);
    });
}

// ============================================================
// 入口
// ============================================================
let _sidebarEl = null;

export function initSidebar(current) {
    if (_sidebarEl) {
        updateSidebarActive(current);
        _currentKey = current;
        history.replaceState({ key: current }, '', window.location.href);
        return _sidebarEl;
    }

    const host = document.createElement('div');
    host.innerHTML = buildSidebar(current);
    _sidebarEl = host.firstElementChild;
    document.body.insertBefore(_sidebarEl, document.body.firstChild);

    // Intercept clicks
    _sidebarEl.addEventListener('click', (e) => {
        const link = e.target.closest('a[href]');
        if (!link) return;
        const href = link.getAttribute('href');
        if (!href || /^(https?:|#|javascript:)/.test(href)) return;
        e.preventDefault();
        navigateTo(href);
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();

    _currentKey = current;
    history.replaceState({ key: current }, '', window.location.href);

    window.addEventListener('popstate', (e) => {
        if (e.state?.key) navigateTo(e.state.key + '.html', false);
    });

    return _sidebarEl;
}

// Backward compatibility
export { initSidebar as initCapNav };
export default initSidebar;
