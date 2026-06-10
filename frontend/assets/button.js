/* ============================================================
   button.js — 按钮状态机 + data-action 全局事件委托
   替代 onclick 散落 + window.handleXxx 模式

   用法1: smartButton(btnEl, asyncFn, options)
     自动管理 loading/success/error 状态
   用法2: HTML 中添加 data-action="xxx" data-id="..." 属性
     全局自动委托，不再需要 onclick
   ============================================================ */

import { showToast } from './toast.js';

// 保存按钮原始文本和图标
const _store = new WeakMap();

function saveState(btn) {
    if (!_store.has(btn)) {
        _store.set(btn, {
            html: btn.innerHTML,
            disabled: btn.disabled,
        });
    }
}

function restoreState(btn) {
    const state = _store.get(btn);
    if (state) {
        btn.innerHTML = state.html;
        btn.disabled = state.disabled;
        _store.delete(btn);
    }
    // re-init lucide for restored icon
    if (typeof lucide !== 'undefined') lucide.createIcons({ attrs: { 'data-lucide': '' } });
}

/**
 * @param {HTMLElement} btn  按钮元素
 * @param {() => Promise<any>} asyncFn  异步操作
 * @param {Object} opts
 * @param {string} opts.loadingText  加载中文字（默认"处理中..."）
 * @param {string} opts.successText  成功文字（默认"已完成"）
 * @param {number} opts.successDuration  成功态持续 ms（默认 1500）
 * @param {number} opts.errorDuration  错误态持续 ms（默认 3000）
 * @param {Function} opts.onSuccess  成功回调
 * @param {Function} opts.onError  失败回调
 * @param {boolean} opts.showToast  是否弹 Toast（默认 false）
 * @param {string} opts.toastMsg  自定义 Toast 消息
 */
export async function smartButton(btn, asyncFn, opts = {}) {
    const {
        loadingText = '处理中...',
        successText = '已完成',
        successDuration = 1500,
        errorDuration = 3000,
        onSuccess = null,
        onError = null,
        showToast: toast = false,
        toastMsg = '',
    } = opts;

    if (!btn || btn.disabled) return;

    saveState(btn);
    btn.disabled = true;

    // loading 态：spinner + 文字
    const origBg = btn.style.background || getComputedStyle(btn).background;
    btn.style.opacity = '0.7';
    btn.innerHTML = '<span class="spinner spinner-dark" style="width:16px;height:16px;border-width:1.5px;"></span> ' + loadingText;

    try {
        const result = await asyncFn();

        // success 态
        btn.style.opacity = '1';
        btn.style.background = '#10B981';
        btn.style.boxShadow = '0 2px 8px rgba(16,185,129,0.3)';
        btn.innerHTML = '<i data-lucide="check-circle" style="width:16px;height:16px;"></i> ' + successText;
        if (typeof lucide !== 'undefined') lucide.createIcons({ attrs: { 'data-lucide': '' } });

        if (toast) {
            showToast(toastMsg || successText, 'success');
        }
        if (onSuccess) onSuccess(result);

        setTimeout(() => {
            btn.style.background = origBg;
            btn.style.boxShadow = '';
            restoreState(btn);
        }, successDuration);

        return result;

    } catch (err) {
        // error 态
        btn.style.opacity = '1';
        btn.style.background = '#EF4444';
        btn.style.boxShadow = '0 2px 8px rgba(239,68,68,0.3)';
        const errMsg = err?.message || String(err);
        btn.innerHTML = '<i data-lucide="x-circle" style="width:16px;height:16px;"></i> ' + (errMsg.length > 20 ? '操作失败' : errMsg);
        if (typeof lucide !== 'undefined') lucide.createIcons({ attrs: { 'data-lucide': '' } });

        if (toast) {
            showToast(toastMsg || errMsg || '操作失败，请稍后重试', 'error');
        }
        if (onError) onError(err);

        setTimeout(() => {
            btn.style.background = origBg;
            btn.style.boxShadow = '';
            restoreState(btn);
        }, errorDuration);

        throw err;
    }
}

/* ============================================================
   data-action 全局事件委托
   所有带 data-action 属性的按钮自动获得事件处理
   页面通过 registerActions({ ... }) 注册处理函数
   ============================================================ */

const _registry = {};

/**
 * @param {Object<string, Function>} map  { actionName: handler(data, btn) }
 */
export function registerActions(map) {
    Object.assign(_registry, map);
}

// 全局委托
document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn || btn.disabled) return;

    const action = btn.dataset.action;
    const handler = _registry[action];
    if (!handler) return;

    e.preventDefault();

    // 收集所有 data-* 属性
    const data = Object.assign({}, btn.dataset);

    await smartButton(btn, () => handler(data, btn), {
        loadingText: btn.dataset.loading || '处理中...',
        successText: btn.dataset.success || '已完成',
    });
});

export default smartButton;
