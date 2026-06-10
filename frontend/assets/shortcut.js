/* ============================================================
   shortcut.js — 键盘快捷键管理系统
   支持全局快捷键和页面级快捷键，冲突检测

   用法:
   import { registerShortcut, registerPageShortcuts, enableShortcuts } from './assets/shortcut.js';
   registerShortcut('Ctrl+1', () => { window.location.href = 'index.html'; }, 'global');
   registerPageShortcuts('chat', { 'Enter': handleSend, 'Ctrl+N': handleNewChat });
   ============================================================ */

const _shortcuts = [];
let _enabled = true;

const PAGE_NAMES = {
    index: 1, chat: 2, generate: 3, library: 4, pathway: 5, evaluate: 6, profile: 7,
};

const DEFAULT_GLOBAL = {
    'Ctrl+1': () => { window.location.href = 'index.html'; },
    'Ctrl+2': () => { window.location.href = 'chat.html'; },
    'Ctrl+3': () => { window.location.href = 'generate.html'; },
    'Ctrl+4': () => { window.location.href = 'library.html'; },
    'Ctrl+5': () => { window.location.href = 'pathway.html'; },
    'Ctrl+6': () => { window.location.href = 'evaluate.html'; },
    'Ctrl+7': () => { window.location.href = 'profile.html'; },
    'Escape': () => { /* dismiss modal/multi-select — handled by individual components */ },
};

function detectCurrentPage() {
    const path = window.location.pathname;
    const match = path.match(/\/([a-z]+)\.html$/);
    return match ? match[1] : 'index';
}

function parseCombo(combo) {
    const parts = combo.toLowerCase().split('+').map(s => s.trim());
    const result = { ctrl: false, alt: false, shift: false, meta: false, key: '' };
    for (const p of parts) {
        if (p === 'ctrl') result.ctrl = true;
        else if (p === 'alt') result.alt = true;
        else if (p === 'shift') result.shift = true;
        else if (p === 'meta' || p === 'cmd') result.meta = true;
        else result.key = p;
    }
    return result;
}

function comboMatches(parsed, e) {
    if (parsed.ctrl !== e.ctrlKey && parsed.ctrl !== e.metaKey) return false;
    if (parsed.meta !== e.metaKey) return false;
    if (parsed.alt !== e.altKey) return false;
    if (parsed.shift !== e.shiftKey) return false;

    const key = e.key.toLowerCase();
    if (parsed.key === 'enter' && key === 'enter') return true;
    if (parsed.key === 'escape' && key === 'escape') return true;
    if (parsed.key === 'delete' && (key === 'delete' || key === 'backspace')) return true;
    if (parsed.key.length === 1 && key === parsed.key) return true;
    // Function keys
    if (parsed.key === key) return true;

    return false;
}

function isInputFocused() {
    const tag = document.activeElement?.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || document.activeElement?.isContentEditable;
}

/**
 * @param {string} combo  e.g. 'Ctrl+Enter', 'Shift+?', 'Escape'
 * @param {Function} fn
 * @param {string} scope  'global' | 'chat' | 'generate' | null (current page)
 * @param {Object} opts
 * @param {boolean} opts.allowInInput  allow when input/textarea is focused
 */
export function registerShortcut(combo, fn, scope = null, opts = {}) {
    _shortcuts.push({ combo, fn, scope: scope || detectCurrentPage(), parsed: parseCombo(combo), opts });
}

/**
 * Register multiple page-level shortcuts at once
 * @param {string} page  page name
 * @param {Object<string, Function>} map  { 'Enter': fn, 'Ctrl+N': fn }
 */
export function registerPageShortcuts(page, map) {
    for (const [combo, fn] of Object.entries(map)) {
        registerShortcut(combo, fn, page);
    }
}

export function enableShortcuts(enable) {
    _enabled = enable;
}

// Install listener
document.addEventListener('keydown', (e) => {
    if (!_enabled) return;

    const currentPage = detectCurrentPage();

    // Only handle non-input shortcuts when input is focused
    const inInput = isInputFocused();

    for (const sc of _shortcuts) {
        // Skip if scope doesn't match (global shortcuts always match)
        if (sc.scope !== 'global' && sc.scope !== currentPage) continue;
        if (!comboMatches(sc.parsed, e)) continue;

        // For Enter/Escape in inputs, only fire if explicitly allowed
        if (inInput && !sc.opts.allowInInput) {
            // Allow navigation shortcuts even in inputs
            if (sc.scope !== 'global') continue;
            // Allow Ctrl+1~7 even in inputs
            if (!sc.combo.toLowerCase().startsWith('ctrl+')) continue;
        }

        e.preventDefault();
        e.stopPropagation();
        try {
            sc.fn(e);
        } catch (err) {
            console.error('[shortcut] Error in handler for', sc.combo, err);
        }
        return;
    }
});

// Register default global shortcuts
for (const [combo, fn] of Object.entries(DEFAULT_GLOBAL)) {
    registerShortcut(combo, fn, 'global');
}

export default { registerShortcut, registerPageShortcuts, enableShortcuts };
