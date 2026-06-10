/* ============================================================
   command.js — Ctrl+K 命令面板
   全局搜索 + 页面导航 + 资源搜索 + 最近访问
   用法: import { initCommandPalette } from './assets/command.js';
         initCommandPalette({ recentItems: [...], onSearch: async (q) => [...] });
   ============================================================ */

let overlay = null;
let searchIndex = [];
let recentItems = [];
let onSearchFn = null;

function ensureOverlay() {
    if (!overlay || !document.body.contains(overlay)) {
        overlay = document.createElement('div');
        overlay.className = 'cmd-overlay';
        Object.assign(overlay.style, {
            position: 'fixed', inset: '0', zIndex: '10001',
            background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(3px)',
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            paddingTop: '15vh', opacity: '0', transition: 'opacity 0.15s ease',
        });
        document.body.appendChild(overlay);
    }
    return overlay;
}

const PAGE_COMMANDS = [
    { id: 'nav-home', label: '学习看板', desc: '首页', icon: 'home', action: () => { window.location.href = 'index.html'; } },
    { id: 'nav-chat', label: '智能对话', desc: 'Chat', icon: 'message-square', action: () => { window.location.href = 'chat.html'; } },
    { id: 'nav-generate', label: '资源生成', desc: 'Generate', icon: 'sparkles', action: () => { window.location.href = 'generate.html'; } },
    { id: 'nav-library', label: '资源库', desc: 'Library', icon: 'library', action: () => { window.location.href = 'library.html'; } },
    { id: 'nav-pathway', label: '学习路径', desc: 'Pathway', icon: 'share-2', action: () => { window.location.href = 'pathway.html'; } },
    { id: 'nav-evaluate', label: '学习评估', desc: 'Evaluate', icon: 'clipboard-check', action: () => { window.location.href = 'evaluate.html'; } },
    { id: 'nav-profile', label: '个人中心', desc: 'Profile', icon: 'circle-user', action: () => { window.location.href = 'profile.html'; } },
];

function buildIndex() {
    return [
        { section: '页面导航', items: PAGE_COMMANDS },
        ...(recentItems.length > 0 ? [{ section: '最近访问', items: recentItems }] : []),
    ];
}

function fuzzyMatch(text, query) {
    const t = text.toLowerCase();
    const q = query.toLowerCase();
    if (t.includes(q)) return 1;
    let qi = 0;
    for (let i = 0; i < t.length && qi < q.length; i++) {
        if (t[i] === q[qi]) qi++;
    }
    return qi === q.length ? 0.5 : 0;
}

function renderResults(query) {
    const container = document.getElementById('cmd-results');
    if (!container) return;

    let allItems = [];
    const index = buildIndex();
    for (const group of index) {
        for (const item of group.items) {
            const score = fuzzyMatch(item.label + ' ' + (item.desc || ''), query);
            if (score > 0) {
                allItems.push({ ...item, score, section: group.section });
            }
        }
    }

    if (!query && recentItems.length > 0) {
        allItems = [
            ...PAGE_COMMANDS.map(item => ({ ...item, score: 1, section: '页面导航' })),
            ...recentItems.map(item => ({ ...item, score: 1, section: '最近访问' })),
        ];
    } else if (!query) {
        allItems = PAGE_COMMANDS.map(item => ({ ...item, score: 1, section: '页面导航' }));
    }

    allItems.sort((a, b) => b.score - a.score);
    const unique = [];
    const seen = new Set();
    for (const item of allItems) {
        if (!seen.has(item.id || item.label)) {
            seen.add(item.id || item.label);
            unique.push(item);
        }
    }

    // Group by section
    const sections = {};
    for (const item of unique) {
        if (!sections[item.section]) sections[item.section] = [];
        sections[item.section].push(item);
    }

    let html = '';
    for (const [section, items] of Object.entries(sections)) {
        html += `<div class="cmd-section-title">${section}</div>`;
        for (let i = 0; i < Math.min(items.length, 8); i++) {
            const item = items[i];
            const icon = item.icon || 'circle';
            html += `
                <div class="cmd-item" data-cmd-id="${item.id || item.label}" data-cmd-action="${encodeURIComponent(JSON.stringify({ label: item.label, action: item.action ? 'fn' : 'nav' }))}">
                    <span class="cmd-item-icon"><i data-lucide="${icon}" style="width:16px;height:16px;"></i></span>
                    <span class="cmd-item-label">${highlightMatch(item.label, query)}</span>
                    ${item.desc ? `<span class="cmd-item-desc">${item.desc}</span>` : ''}
                </div>`;
        }
    }

    if (unique.length === 0) {
        html = '<div style="padding:24px;text-align:center;color:#9CA3AF;font-size:13px;">未找到匹配结果</div>';
    }

    container.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons({ attrs: { 'data-lucide': '' } });

    // Highlight first item
    const first = container.querySelector('.cmd-item');
    if (first) first.classList.add('active');

    // Store items for keyboard nav
    container._items = allItems;
}

function highlightMatch(text, query) {
    if (!query) return escapeCmdHtml(text);
    const t = text.toLowerCase();
    const q = query.toLowerCase();
    const idx = t.indexOf(q);
    if (idx >= 0) {
        return escapeCmdHtml(text.slice(0, idx)) +
            '<mark style="background:#EEF1FE;color:#4F6EF7;border-radius:2px;">' +
            escapeCmdHtml(text.slice(idx, idx + q.length)) + '</mark>' +
            escapeCmdHtml(text.slice(idx + q.length));
    }
    return escapeCmdHtml(text);
}

function escapeCmdHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function selectItem(el) {
    if (!el) return;
    const actionData = el.dataset.cmdAction;
    if (!actionData) return;
    try {
        const data = JSON.parse(decodeURIComponent(actionData));
        // Find the actual item in PAGE_COMMANDS or recentItems
        const allItems = [...PAGE_COMMANDS, ...recentItems];
        const item = allItems.find(x => x.label === data.label);
        if (item && item.action) {
            close();
            setTimeout(() => item.action(), 50);
        }
    } catch (e) { /* ignore */ }
}

function close() {
    if (!overlay) return;
    overlay.style.opacity = '0';
    setTimeout(() => {
        if (overlay) overlay.innerHTML = '';
    }, 150);
    document.removeEventListener('keydown', onCmdKeydown);
}

function open() {
    const overlayEl = ensureOverlay();

    overlayEl.innerHTML = `
        <div class="cmd-panel" style="
            background:#fff; border-radius:16px; width:min(540px,92vw);
            box-shadow: 0 12px 60px rgba(0,0,0,0.2);
            display:flex; flex-direction:column; overflow:hidden;
            max-height: 70vh;
        ">
            <div class="cmd-input-wrap" style="
                display:flex; align-items:center; gap:10px;
                padding:16px 20px; border-bottom:1px solid #E5E7EB;
            ">
                <i data-lucide="search" style="width:18px;height:18px;color:#9CA3AF;flex-shrink:0;"></i>
                <input type="text" id="cmd-input" placeholder="输入命令或搜索..."
                    style="flex:1;border:none;outline:none;font-size:15px;font-family:inherit;background:transparent;color:#1E1E2E;">
                <span style="font-size:11px;color:#9CA3AF;background:#F0F1F5;padding:3px 7px;border-radius:5px;font-family:monospace;">Esc</span>
            </div>
            <div id="cmd-results" style="overflow-y:auto;padding:8px;"></div>
            <div style="padding:8px 20px;font-size:11px;color:#9CA3AF;border-top:1px solid #F0F1F5;display:flex;gap:16px;">
                <span><kbd style="background:#F0F1F5;padding:1px 5px;border-radius:3px;font-family:monospace;">↑↓</kbd> 导航</span>
                <span><kbd style="background:#F0F1F5;padding:1px 5px;border-radius:3px;font-family:monospace;">Enter</kbd> 选择</span>
                <span><kbd style="background:#F0F1F5;padding:1px 5px;border-radius:3px;font-family:monospace;">Esc</kbd> 关闭</span>
            </div>
        </div>
    `;

    overlayEl.style.opacity = '1';
    if (typeof lucide !== 'undefined') lucide.createIcons({ attrs: { 'data-lucide': '' } });

    const input = document.getElementById('cmd-input');
    const results = document.getElementById('cmd-results');

    input.addEventListener('input', () => {
        const q = input.value.trim();
        renderResults(q);
        // If there's a search function, use it
        if (onSearchFn && q.length >= 2) {
            onSearchFn(q).then(items => {
                if (items && items.length) {
                    recentItems = [...items];
                    renderResults(q);
                }
            }).catch(() => {});
        }
    });

    // Initial render
    renderResults('');

    // Click handlers
    results.addEventListener('click', (e) => {
        const item = e.target.closest('.cmd-item');
        if (item) selectItem(item);
    });

    // Click overlay to close
    overlayEl.onclick = (e) => {
        if (e.target === overlayEl) close();
    };

    document.addEventListener('keydown', onCmdKeydown);

    setTimeout(() => input.focus(), 100);
}

function onCmdKeydown(e) {
    if (e.key === 'Escape') {
        e.preventDefault();
        close();
        return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const results = document.getElementById('cmd-results');
        if (!results) return;
        const items = results.querySelectorAll('.cmd-item');
        const active = results.querySelector('.cmd-item.active');
        let idx = -1;
        items.forEach((item, i) => { if (item === active) idx = i; });
        if (e.key === 'ArrowDown') idx = (idx + 1) % items.length;
        else idx = (idx - 1 + items.length) % items.length;
        items.forEach(item => item.classList.remove('active'));
        if (items[idx]) {
            items[idx].classList.add('active');
            items[idx].scrollIntoView({ block: 'nearest' });
        }
        return;
    }
    if (e.key === 'Enter') {
        e.preventDefault();
        const results = document.getElementById('cmd-results');
        if (!results) return;
        const active = results.querySelector('.cmd-item.active');
        if (active) selectItem(active);
        return;
    }
}

/**
 * @param {Object} opts
 * @param {Array<{id:string, label:string, desc:string, icon:string, action:Function}>} opts.recentItems
 * @param {(query:string) => Promise<Array>} opts.onSearch
 */
export function initCommandPalette(opts = {}) {
    if (opts.recentItems) recentItems = opts.recentItems;
    if (opts.onSearch) onSearchFn = opts.onSearch;

    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            open();
        }
    });
}

export function addRecentItem(item) {
    recentItems.unshift(item);
    if (recentItems.length > 10) recentItems.pop();
}

export default initCommandPalette;

// Add basic styles for cmd items
const cmdStyle = document.createElement('style');
cmdStyle.textContent = `
    .cmd-item {
        display: flex; align-items: center; gap: 10px;
        padding: 10px 14px; border-radius: 8px; cursor: pointer;
        transition: background 0.1s; margin: 0 4px;
    }
    .cmd-item:hover, .cmd-item.active { background: #F0F4FF; }
    .cmd-item-icon { width: 32px; height: 32px; border-radius: 8px; background: #F0F1F5; display: flex; align-items: center; justify-content: center; color: #4F6EF7; flex-shrink: 0; }
    .cmd-item.active .cmd-item-icon { background: #EEF1FE; }
    .cmd-item-label { font-size: 14px; color: #1E1E2E; font-weight: 500; }
    .cmd-item-desc { font-size: 12px; color: #9CA3AF; margin-left: auto; }
    .cmd-section-title { font-size: 11px; font-weight: 600; color: #9CA3AF; text-transform: uppercase; letter-spacing: 0.04em; padding: 8px 14px 4px; }
`;
document.head.appendChild(cmdStyle);
