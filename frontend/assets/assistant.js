/**
 * assistant.js — AI 学习伴侣悬浮面板
 *
 * 功能：
 *   1. 悬浮机器人按钮（右下角）
 *   2. 多 Tab 面板：迷你对话 / 学情摘要 / 番茄钟
 *   3. 每日学习提醒弹窗（每天首次进入首页时显示）
 *   4. 随机气泡提示
 */

import { getUserId, isLoggedIn, getLearningAnalytics, getProfile,
         createChatSession, sendChatMessage } from './api.js';

// ============================================================
// 常量
// ============================================================

const MOTIVATIONS = [
    '坚持就是胜利，今天也要加油学习哦！💪',
    '每天进步一点点，日积月累成就大不同。✨',
    '学而不思则罔，思而不学则殆。📚',
    '今天的努力是明天的底气。🌟',
    '知识是最好的投资，开始今天的学习吧！🎯',
    '不积跬步，无以至千里。一起加油！🚀',
    '天道酬勤，越努力越幸运！🍀',
    '学习使人充实，坚持让你出众。💡',
];

const BUBBLE_MESSAGES = [
    '👋 有什么我可以帮你的吗？',
    '📖 今天复习了吗？别让知识溜走哦~',
    '🎯 试试番茄钟，保持专注！',
    '💡 点击我可以随时提问哦~',
    '🌟 你已经很棒了，继续保持！',
    '🍅 来个番茄钟，专注25分钟吧！',
];

const CHAT_SUGGESTIONS = [
    '帮我复习薄弱知识点',
    '今天应该学什么？',
    '解释一下这个概念',
    '给我出道题测试一下',
];

const GREETINGS = {
    morning: '早上好',
    afternoon: '下午好',
    evening: '晚上好',
    night: '夜深了',
};

// ============================================================
// 工具函数
// ============================================================

function getTimeGreeting() {
    const h = new Date().getHours();
    if (h >= 5 && h < 12) return GREETINGS.morning;
    if (h >= 12 && h < 18) return GREETINGS.afternoon;
    if (h >= 18 && h < 22) return GREETINGS.evening;
    return GREETINGS.night;
}

function getMotivation() {
    return MOTIVATIONS[Math.floor(Math.random() * MOTIVATIONS.length)];
}

function getTodayKey(userId) {
    const today = new Date().toISOString().slice(0, 10);
    return `softbei_daily_reminder_${userId}_${today}`;
}

// ============================================================
// 创建 DOM
// ============================================================

function createAssistantDOM() {
    // 悬浮按钮
    const fab = document.createElement('button');
    fab.className = 'ai-bot-fab';
    fab.id = 'aiBotFab';
    fab.innerHTML = `
        <span class="bot-avatar">🤖</span>
        <span class="bot-close">✕</span>
        <span class="bot-badge" id="aiBotBadge"></span>
    `;

    // 气泡
    const bubble = document.createElement('div');
    bubble.className = 'ai-bot-bubble';
    bubble.id = 'aiBotBubble';

    // 主面板
    const panel = document.createElement('div');
    panel.className = 'ai-bot-panel';
    panel.id = 'aiBotPanel';
    panel.innerHTML = `
        <div class="ai-panel-header">
            <span class="panel-bot-icon">🤖</span>
            <div>
                <div class="panel-title">学习小助手</div>
                <div class="panel-subtitle">你的专属学习伴侣</div>
            </div>
            <div class="ai-panel-today-time">
                <span class="today-time-icon">⏱️</span>
                <span class="today-time-value" id="aiTodayTime">0分钟</span>
                <span class="today-time-label">今日已学习</span>
            </div>
        </div>
        <div class="ai-panel-tabs">
            <div class="ai-panel-tab active" data-tab="chat">
                <span class="tab-icon">💬</span>
                <span>对话</span>
            </div>
            <div class="ai-panel-tab" data-tab="stats">
                <span class="tab-icon">📊</span>
                <span>学情</span>
            </div>
            <div class="ai-panel-tab" data-tab="pomodoro">
                <span class="tab-icon">🍅</span>
                <span>番茄钟</span>
            </div>
        </div>
        <div class="ai-panel-content">
            <!-- Tab: 对话 -->
            <div class="ai-tab-pane active" id="aiTabChat">
                <div class="ai-chat-container">
                    <div class="ai-chat-suggestions" id="aiChatSuggestions"></div>
                    <div class="ai-chat-messages" id="aiChatMessages">
                        <div class="ai-chat-msg bot">你好！我是你的学习小助手 🤖 有什么问题随时问我～</div>
                    </div>
                    <div class="ai-chat-input-area">
                        <input class="ai-chat-input" id="aiChatInput" placeholder="输入你的问题..." maxlength="500">
                        <button class="ai-chat-send-btn" id="aiChatSend">➤</button>
                    </div>
                </div>
            </div>
            <!-- Tab: 学情 -->
            <div class="ai-tab-pane" id="aiTabStats">
                <div id="aiStatsContent">
                    <div class="ai-empty-state">加载中...</div>
                </div>
            </div>
            <!-- Tab: 番茄钟 -->
            <div class="ai-tab-pane" id="aiTabPomodoro">
                <div class="ai-pomodoro">
                    <div class="ai-pomo-circle" id="aiPomoCircle">
                        <div class="ai-pomo-time" id="aiPomoTime">25:00</div>
                        <div class="ai-pomo-label" id="aiPomoLabel">专注时间</div>
                    </div>
                    <div class="ai-pomo-controls" id="aiPomoControls">
                        <button class="ai-pomo-btn primary" id="aiPomoStart">开始专注</button>
                    </div>
                    <div class="ai-pomo-stats">
                        <span>🍅 今日完成 <span class="pomo-count" id="aiPomoCount">0</span> 个</span>
                        <span>⏱️ 共 <span class="pomo-count" id="aiPomoMinutes">0</span> 分钟</span>
                    </div>
                    <div class="ai-pomo-settings">
                        <div class="ai-pomo-setting-row">
                            <span>专注时长（分钟）</span>
                            <input type="number" id="aiPomoWorkMin" value="25" min="5" max="60">
                        </div>
                        <div class="ai-pomo-setting-row">
                            <span>休息时长（分钟）</span>
                            <input type="number" id="aiPomoBreakMin" value="5" min="1" max="30">
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // 每日提醒弹窗
    const reminder = document.createElement('div');
    reminder.className = 'daily-reminder-overlay';
    reminder.id = 'dailyReminder';
    reminder.innerHTML = `
        <div class="daily-reminder-card">
            <div class="daily-reminder-icon" id="reminderIcon">🌅</div>
            <div class="daily-reminder-greeting" id="reminderGreeting">早上好！</div>
            <div class="daily-reminder-time" id="reminderTime"></div>
            <div id="reminderContent"></div>
            <div class="daily-reminder-tip" id="reminderTip"></div>
            <div class="daily-reminder-actions">
                <button class="daily-reminder-btn primary" id="reminderStartBtn">开始学习</button>
                <button class="daily-reminder-btn secondary" id="reminderDismissBtn">稍后再说</button>
            </div>
            <div class="daily-motivation" id="reminderMotivation"></div>
        </div>
    `;

    document.body.appendChild(fab);
    document.body.appendChild(bubble);
    document.body.appendChild(panel);
    document.body.appendChild(reminder);
}

// ============================================================
// 面板 & Tab 交互
// ============================================================

let panelOpen = false;
let bubbleTimeout = null;
let currentTab = 'chat';

function togglePanel() {
    const fab = document.getElementById('aiBotFab');
    const panel = document.getElementById('aiBotPanel');
    const bubble = document.getElementById('aiBotBubble');

    panelOpen = !panelOpen;

    if (panelOpen) {
        fab.classList.add('open');
        panel.classList.add('open');
        bubble.classList.remove('show');
        // 首次打开学情 tab 时加载数据
        if (currentTab === 'stats') loadStatsData();
    } else {
        fab.classList.remove('open');
        panel.classList.remove('open');
    }
}

function switchTab(tabName) {
    currentTab = tabName;
    document.querySelectorAll('.ai-panel-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tabName));
    document.querySelectorAll('.ai-tab-pane').forEach(p => p.classList.remove('active'));
    const targetPane = document.getElementById(tabName === 'chat' ? 'aiTabChat' : tabName === 'stats' ? 'aiTabStats' : 'aiTabPomodoro');
    if (targetPane) targetPane.classList.add('active');

    if (tabName === 'stats') loadStatsData();
}

function showBubble(msg) {
    const bubble = document.getElementById('aiBotBubble');
    if (!bubble || panelOpen) return;
    bubble.textContent = msg;
    bubble.classList.add('show');
    clearTimeout(bubbleTimeout);
    bubbleTimeout = setTimeout(() => bubble.classList.remove('show'), 5000);
}

function scheduleBubbles() {
    setTimeout(() => {
        if (!panelOpen) showBubble(BUBBLE_MESSAGES[Math.floor(Math.random() * BUBBLE_MESSAGES.length)]);
    }, 6000);

    setInterval(() => {
        if (!panelOpen && Math.random() > 0.5) {
            showBubble(BUBBLE_MESSAGES[Math.floor(Math.random() * BUBBLE_MESSAGES.length)]);
        }
    }, 90000);
}

// ============================================================
// Tab1: 迷你对话
// ============================================================

let chatSessionId = null;
let chatSending = false;

function renderSuggestions() {
    const container = document.getElementById('aiChatSuggestions');
    if (!container) return;
    container.innerHTML = CHAT_SUGGESTIONS.map(s =>
        `<span class="ai-chat-suggestion">${s}</span>`
    ).join('');
}

async function ensureChatSession() {
    if (chatSessionId) return chatSessionId;
    const userId = getUserId();
    try {
        const session = await createChatSession(userId);
        chatSessionId = session?.id || session?.session_id;
        return chatSessionId;
    } catch (e) {
        console.warn('[assistant] 创建会话失败', e);
        return null;
    }
}

function appendChatMsg(text, role) {
    const container = document.getElementById('aiChatMessages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = `ai-chat-msg ${role}`;
    div.textContent = text;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function showTyping() {
    const container = document.getElementById('aiChatMessages');
    const div = document.createElement('div');
    div.className = 'ai-chat-msg bot typing';
    div.id = 'aiTypingMsg';
    div.textContent = '思考中...';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function removeTyping() {
    const el = document.getElementById('aiTypingMsg');
    if (el) el.remove();
}

async function handleSendMessage() {
    if (chatSending) return;
    const input = document.getElementById('aiChatInput');
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    appendChatMsg(msg, 'user');

    // 隐藏快捷建议
    const suggestions = document.getElementById('aiChatSuggestions');
    if (suggestions) suggestions.style.display = 'none';

    chatSending = true;
    const sendBtn = document.getElementById('aiChatSend');
    sendBtn.disabled = true;

    showTyping();

    try {
        const sessionId = await ensureChatSession();
        if (!sessionId) {
            removeTyping();
            appendChatMsg('抱歉，连接失败，请稍后重试。', 'bot');
            return;
        }

        const userId = getUserId();
        const resp = await sendChatMessage(sessionId, userId, msg);
        removeTyping();

        if (resp && resp.content) {
            appendChatMsg(resp.content, 'bot');
        } else if (resp && resp.reply) {
            appendChatMsg(resp.reply, 'bot');
        } else {
            appendChatMsg('收到！不过我暂时无法回复，请稍后再试。', 'bot');
        }
    } catch (e) {
        removeTyping();
        appendChatMsg('网络错误，请检查连接后重试。', 'bot');
        console.warn('[assistant] 发送消息失败', e);
    } finally {
        chatSending = false;
        sendBtn.disabled = false;
    }
}

// ============================================================
// Tab2: 学情摘要
// ============================================================

let statsLoaded = false;

async function loadStatsData() {
    if (statsLoaded) return;
    const userId = getUserId();
    if (!userId) return;

    const container = document.getElementById('aiStatsContent');
    if (!container) return;

    try {
        const data = await getLearningAnalytics(userId);
        if (!data) {
            container.innerHTML = '<div class="ai-empty-state">暂无学习数据，快去学习吧！📚</div>';
            statsLoaded = true;
            return;
        }

        const behavior = data.learning_behavior || {};
        const forgetting = (data.forgetting_curve || []).filter(i => i.needs_review);
        const mastery = data.quiz_mastery || [];

        // 统计卡片
        let html = `<div class="ai-stats-grid">
            <div class="ai-stat-card">
                <div class="ai-stat-value">${behavior.streak_days || 0}</div>
                <div class="ai-stat-label">🔥 连续学习天数</div>
            </div>
            <div class="ai-stat-card">
                <div class="ai-stat-value">${behavior.total_actions || 0}</div>
                <div class="ai-stat-label">📝 总学习次数</div>
            </div>
            <div class="ai-stat-card">
                <div class="ai-stat-value">${Math.round(behavior.total_minutes || 0)}</div>
                <div class="ai-stat-label">⏱️ 总学习(分钟)</div>
            </div>
            <div class="ai-stat-card">
                <div class="ai-stat-value">${behavior.active_days || 0}</div>
                <div class="ai-stat-label">📅 活跃天数</div>
            </div>
        </div>`;

        // 掌握度 Top 5
        if (mastery.length > 0) {
            html += `<div class="ai-section-title">🎯 知识掌握度</div>`;
            const top5 = mastery.sort((a, b) => b.mastery_score - a.mastery_score).slice(0, 5);
            html += top5.map(m => {
                const pct = m.mastery_score;
                const color = pct >= 80 ? '#43A047' : pct >= 60 ? '#F57C00' : '#E53935';
                return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:12px;">
                    <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${m.kp_name}</span>
                    <div style="width:80px;height:6px;background:#E0E6ED;border-radius:3px;overflow:hidden;">
                        <div style="width:${pct}%;height:100%;background:${color};border-radius:3px;"></div>
                    </div>
                    <span style="width:30px;text-align:right;color:${color};font-weight:600;">${pct}%</span>
                </div>`;
            }).join('');
        }

        // 遗忘提醒
        if (forgetting.length > 0) {
            html += `<div class="ai-section-title">⚠️ 需要复习 (${forgetting.length})</div>`;
            html += '<div class="ai-review-list">';
            html += forgetting.slice(0, 5).map(item => `
                <div class="ai-review-item urgency-${item.urgency}" 
                     onclick="window.location.href='generate.html?kp=${encodeURIComponent(item.kp_id || item.kp_name)}&type=doc'"
                     title="点击去复习">
                    <span class="review-name">${item.kp_name}</span>
                    <span class="review-days">${item.days_since_last}天前</span>
                </div>
            `).join('');
            html += '</div>';
        } else {
            html += '<div class="ai-section-title">✅ 所有知识点都很新鲜，继续保持！</div>';
        }

        container.innerHTML = html;
        statsLoaded = true;
    } catch (e) {
        console.warn('[assistant] 加载学情数据失败', e);
        container.innerHTML = '<div class="ai-empty-state">加载失败，请稍后重试</div>';
    }
}

// ============================================================
// Tab3: 番茄钟
// ============================================================

let pomoState = 'idle'; // idle | running | paused | resting
let pomoInterval = null;
let pomoRemaining = 25 * 60; // seconds
let pomoWorkMin = 25;
let pomoBreakMin = 5;
let pomoCount = 0;
let pomoTotalMin = 0;

function updatePomoDisplay() {
    const timeEl = document.getElementById('aiPomoTime');
    const labelEl = document.getElementById('aiPomoLabel');
    const circleEl = document.getElementById('aiPomoCircle');
    const controlsEl = document.getElementById('aiPomoControls');

    if (!timeEl) return;

    const min = Math.floor(pomoRemaining / 60);
    const sec = pomoRemaining % 60;
    timeEl.textContent = `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;

    circleEl.className = 'ai-pomo-circle' + (pomoState === 'running' ? ' running' : pomoState === 'resting' ? ' resting' : '');

    if (pomoState === 'resting') {
        labelEl.textContent = '休息时间 ☕';
    } else if (pomoState === 'running') {
        labelEl.textContent = '专注中...';
    } else if (pomoState === 'paused') {
        labelEl.textContent = '已暂停';
    } else {
        labelEl.textContent = '专注时间';
    }

    // 按钮
    if (pomoState === 'idle') {
        controlsEl.innerHTML = `<button class="ai-pomo-btn primary" id="aiPomoStart">开始专注</button>`;
    } else if (pomoState === 'running') {
        controlsEl.innerHTML = `
            <button class="ai-pomo-btn secondary" id="aiPomoPause">暂停</button>
            <button class="ai-pomo-btn danger" id="aiPomoStop">放弃</button>
        `;
    } else if (pomoState === 'paused') {
        controlsEl.innerHTML = `
            <button class="ai-pomo-btn primary" id="aiPomoResume">继续</button>
            <button class="ai-pomo-btn danger" id="aiPomoStop">放弃</button>
        `;
    } else if (pomoState === 'resting') {
        controlsEl.innerHTML = `<button class="ai-pomo-btn secondary" id="aiPomoSkipRest">跳过休息</button>`;
    }

    // 绑定事件
    const startBtn = document.getElementById('aiPomoStart');
    const pauseBtn = document.getElementById('aiPomoPause');
    const resumeBtn = document.getElementById('aiPomoResume');
    const stopBtn = document.getElementById('aiPomoStop');
    const skipBtn = document.getElementById('aiPomoSkipRest');

    if (startBtn) startBtn.onclick = startPomodoro;
    if (pauseBtn) pauseBtn.onclick = pausePomodoro;
    if (resumeBtn) resumeBtn.onclick = resumePomodoro;
    if (stopBtn) stopBtn.onclick = stopPomodoro;
    if (skipBtn) skipBtn.onclick = skipRest;

    // 统计
    document.getElementById('aiPomoCount').textContent = pomoCount;
    document.getElementById('aiPomoMinutes').textContent = pomoTotalMin;
}

function startPomodoro() {
    pomoWorkMin = parseInt(document.getElementById('aiPomoWorkMin')?.value) || 25;
    pomoBreakMin = parseInt(document.getElementById('aiPomoBreakMin')?.value) || 5;
    pomoRemaining = pomoWorkMin * 60;
    pomoState = 'running';
    updatePomoDisplay();
    pomoInterval = setInterval(pomoTick, 1000);
}

function pausePomodoro() {
    pomoState = 'paused';
    clearInterval(pomoInterval);
    updatePomoDisplay();
}

function resumePomodoro() {
    pomoState = 'running';
    updatePomoDisplay();
    pomoInterval = setInterval(pomoTick, 1000);
}

function stopPomodoro() {
    pomoState = 'idle';
    clearInterval(pomoInterval);
    pomoRemaining = pomoWorkMin * 60;
    updatePomoDisplay();
}

function skipRest() {
    clearInterval(pomoInterval);
    pomoState = 'idle';
    pomoRemaining = pomoWorkMin * 60;
    updatePomoDisplay();
}

function pomoTick() {
    pomoRemaining--;
    if (pomoRemaining <= 0) {
        clearInterval(pomoInterval);
        if (pomoState === 'running') {
            // 专注结束
            pomoCount++;
            pomoTotalMin += pomoWorkMin;
            savePomodoroStats();
            showBubble('🎉 太棒了！一个番茄钟完成！休息一下吧～');
            // 进入休息
            pomoState = 'resting';
            pomoRemaining = pomoBreakMin * 60;
            updatePomoDisplay();
            pomoInterval = setInterval(pomoTick, 1000);
            // 尝试通知
            tryNotification('番茄钟完成！', '你已经专注了 ' + pomoWorkMin + ' 分钟，休息一下吧 ☕');
        } else if (pomoState === 'resting') {
            // 休息结束
            pomoState = 'idle';
            pomoRemaining = pomoWorkMin * 60;
            updatePomoDisplay();
            showBubble('⏰ 休息结束，准备好开始下一轮了吗？');
            tryNotification('休息结束！', '该开始下一个番茄钟了 🍅');
        }
    }
    updatePomoDisplay();
}

function savePomodoroStats() {
    const userId = getUserId();
    const today = new Date().toISOString().slice(0, 10);
    const key = `softbei_pomo_${userId}_${today}`;
    const stored = JSON.parse(localStorage.getItem(key) || '{"count":0,"minutes":0}');
    stored.count++;
    stored.minutes += pomoWorkMin;
    localStorage.setItem(key, JSON.stringify(stored));
}

function loadPomodoroStats() {
    const userId = getUserId();
    const today = new Date().toISOString().slice(0, 10);
    const key = `softbei_pomo_${userId}_${today}`;
    const stored = JSON.parse(localStorage.getItem(key) || '{"count":0,"minutes":0}');
    pomoCount = stored.count;
    pomoTotalMin = stored.minutes;
}

function tryNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body, icon: '🍅' });
    }
}

// ============================================================
// 每日学习提醒
// ============================================================

async function showDailyReminder() {
    console.log('[daily-reminder] 开始执行');
    const userId = getUserId();
    if (!userId) { console.log('[daily-reminder] 无userId，退出'); return; }

    const path = window.location.pathname;
    console.log('[daily-reminder] pathname:', path);
    const isIndex = path.endsWith('index.html') || path.endsWith('/') || path === '' || path.endsWith('/frontend/');
    if (!isIndex) { console.log('[daily-reminder] 非首页，退出'); return; }

    // 引导正在展示或即将开始，不弹每日提醒
    const guideVisible = document.querySelector('.guide-pending') || document.querySelector('.guide-welcome') || document.querySelector('.guide-overlay');
    if (guideVisible) { console.log('[daily-reminder] 引导展示中，退出'); return; }

    // 本次登录会话已经弹过，不再重复弹
    if (sessionStorage.getItem('softbei_daily_shown')) { console.log('[daily-reminder] 本次会话已弹过，退出'); return; }

    console.log('[daily-reminder] 条件检查通过，准备获取数据');

    let forgettingItems = [];
    let streakDays = 0;

    try {
        const analytics = await getLearningAnalytics(userId);
        if (analytics) {
            forgettingItems = (analytics.forgetting_curve || []).filter(i => i.needs_review);
            streakDays = analytics.learning_behavior?.streak_days || 0;
        }
    } catch (e) {
        console.warn('[daily-reminder] 获取提醒数据失败', e);
    }

    console.log('[daily-reminder] 数据获取完成，准备显示弹窗');

    const overlay = document.getElementById('dailyReminder');
    if (!overlay) { console.log('[daily-reminder] overlay元素不存在！'); return; }
    const greeting = document.getElementById('reminderGreeting');
    const timeEl = document.getElementById('reminderTime');
    const content = document.getElementById('reminderContent');
    const tip = document.getElementById('reminderTip');
    const motivation = document.getElementById('reminderMotivation');
    const iconEl = document.getElementById('reminderIcon');

    const now = new Date();
    const hour = now.getHours();
    const timeIcon = hour < 12 ? '🌅' : (hour < 18 ? '☀️' : '🌙');
    if (iconEl) iconEl.textContent = timeIcon;
    greeting.textContent = `${getTimeGreeting()}！`;
    timeEl.textContent = `${now.getFullYear()}年${now.getMonth()+1}月${now.getDate()}日 星期${['日','一','二','三','四','五','六'][now.getDay()]}`;

    let streakHTML = '';
    if (streakDays > 0) {
        streakHTML = `<div class="daily-reminder-section">
            <div class="daily-reminder-section-title">🔥 连续学习 ${streakDays} 天，真棒！</div>
        </div>`;
    }

    let reviewHTML = '';
    if (forgettingItems.length > 0) {
        const tags = forgettingItems.slice(0, 6).map(item => {
            const cls = item.urgency === 'high' ? 'urgent' : (item.urgency === 'medium' ? 'medium' : 'normal');
            return `<span class="daily-reminder-tag ${cls}" style="cursor:pointer;" onclick="window.location.href='generate.html?kp=${encodeURIComponent(item.kp_id || item.kp_name)}&type=doc'">${item.kp_name}</span>`;
        }).join('');
        reviewHTML = `<div class="daily-reminder-section">
            <div class="daily-reminder-section-title">📋 以下知识点需要复习：</div>
            <div class="daily-reminder-tags">${tags}</div>
        </div>`;
    }

    content.innerHTML = streakHTML + reviewHTML;

    let tipText = '';
    if (forgettingItems.length > 0) {
        tipText = `💡 根据艾宾浩斯遗忘曲线，你有 ${forgettingItems.length} 个知识点即将遗忘，建议今天花 10-15 分钟进行针对性复习。`;
    } else if (hour < 12) {
        tipText = '💡 早上是记忆力最好的时段，适合学习新知识。试试开启番茄钟，专注25分钟！';
    } else if (hour < 18) {
        tipText = '💡 下午适合做练习和复习。试试做几道测验题保持手感吧！';
    } else {
        tipText = '💡 晚间适合轻度复习和总结。回顾今天的学习内容，巩固记忆。';
    }
    tip.textContent = tipText;
    motivation.textContent = `"${getMotivation()}"`;

    // 弹窗显示前再次检查引导是否在展示（因为上面有 await，引导可能在等待期间已开始）
    if (document.querySelector('.guide-pending') || document.querySelector('.guide-welcome') || document.querySelector('.guide-overlay')) return;

    // 标记本次会话已弹过
    sessionStorage.setItem('softbei_daily_shown', '1');

    overlay.classList.add('show');

    document.getElementById('reminderStartBtn').onclick = () => {
        overlay.classList.remove('show');
    };
    document.getElementById('reminderDismissBtn').onclick = () => {
        overlay.classList.remove('show');
    };
}

// ============================================================
// 初始化
// ============================================================

function init() {
    if (!isLoggedIn()) return;

    createAssistantDOM();

    // 悬浮按钮
    document.getElementById('aiBotFab').addEventListener('click', togglePanel);

    // 点击面板外关闭
    document.addEventListener('click', (e) => {
        if (!panelOpen) return;
        const panel = document.getElementById('aiBotPanel');
        const fab = document.getElementById('aiBotFab');
        if (!panel.contains(e.target) && !fab.contains(e.target)) {
            togglePanel();
        }
    });

    // Tab 切换
    document.querySelectorAll('.ai-panel-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // 对话：快捷建议
    renderSuggestions();
    document.getElementById('aiChatSuggestions').addEventListener('click', (e) => {
        if (e.target.classList.contains('ai-chat-suggestion')) {
            document.getElementById('aiChatInput').value = e.target.textContent;
            handleSendMessage();
        }
    });

    // 对话：发送
    document.getElementById('aiChatSend').addEventListener('click', handleSendMessage);
    document.getElementById('aiChatInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    });

    // 番茄钟：加载今日统计
    loadPomodoroStats();
    updatePomoDisplay();

    // 请求通知权限
    if ('Notification' in window && Notification.permission === 'default') {
        // 延迟请求，不打扰用户
        setTimeout(() => Notification.requestPermission(), 30000);
    }

    // 气泡
    scheduleBubbles();

    // 今日已学习时长计时
    initTodayTimer();

    // 每日提醒（仅首页）
    showDailyReminder();

    // 如果有遗忘知识点，显示红点提示
    checkBadge();
}

// ============================================================
// 今日已学习时长
// ============================================================

let todayTimerInterval = null;
let lastSavedSessionSec = 0; // 上次已保存到 localStorage 的本次会话秒数
const SESSION_START = Date.now();

function getTodayOnlineKey(userId) {
    const today = new Date().toISOString().slice(0, 10);
    return `softbei_online_${userId}_${today}`;
}

function getStoredTodaySeconds() {
    const userId = getUserId();
    if (!userId) return 0;
    const key = getTodayOnlineKey(userId);
    return parseInt(localStorage.getItem(key) || '0', 10);
}

function saveTodaySeconds(totalSec) {
    const userId = getUserId();
    if (!userId) return;
    const key = getTodayOnlineKey(userId);
    localStorage.setItem(key, String(totalSec));
}

function getCurrentSessionSeconds() {
    return Math.floor((Date.now() - SESSION_START) / 1000);
}

function formatOnlineTime(totalSec) {
    const totalMin = Math.floor(totalSec / 60);
    if (totalMin < 60) return `${totalMin}分钟`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return `${h}小时${m}分`;
}

function updateTodayTimeDisplay() {
    const el = document.getElementById('aiTodayTime');
    if (!el) return;
    const stored = getStoredTodaySeconds();
    const sessionDelta = getCurrentSessionSeconds() - lastSavedSessionSec;
    const total = stored + sessionDelta;
    el.textContent = formatOnlineTime(total);
}

function initTodayTimer() {
    // 立即更新一次
    updateTodayTimeDisplay();
    // 每 30 秒更新显示 + 增量保存
    todayTimerInterval = setInterval(() => {
        const sessionNow = getCurrentSessionSeconds();
        const delta = sessionNow - lastSavedSessionSec;
        if (delta > 0) {
            const stored = getStoredTodaySeconds();
            saveTodaySeconds(stored + delta);
            lastSavedSessionSec = sessionNow;
        }
        updateTodayTimeDisplay();
    }, 30000);

    // 页面关闭时保存增量
    window.addEventListener('beforeunload', () => {
        const sessionNow = getCurrentSessionSeconds();
        const delta = sessionNow - lastSavedSessionSec;
        if (delta > 0) {
            const stored = getStoredTodaySeconds();
            saveTodaySeconds(stored + delta);
        }
    });

    // 每小时休息提醒
    initHourlyRestReminder();
}

// ============================================================
// 每小时休息提醒
// ============================================================

let restReminderCreated = false;
let lastRestReminderHour = 0; // 上次弹出提醒时的小时数

function getRestReminderKey(userId) {
    const today = new Date().toISOString().slice(0, 10);
    return `softbei_rest_reminded_${userId}_${today}`;
}

function createRestReminderDOM() {
    if (restReminderCreated) return;
    restReminderCreated = true;
    const overlay = document.createElement('div');
    overlay.className = 'rest-reminder-overlay';
    overlay.id = 'restReminderOverlay';
    overlay.innerHTML = `
        <div class="rest-reminder-card">
            <div class="rest-reminder-icon">☕</div>
            <div class="rest-reminder-title">该休息一下啦！</div>
            <div class="rest-reminder-hours-label">今日已学习</div>
            <div class="rest-reminder-hours" id="restReminderHours">1<span class="rest-reminder-hours-unit">小时</span></div>
            <div class="rest-reminder-desc">连续学习时间较长，让眼睛和大脑休息一下吧！<br>起来走动走动、看看远处，身体好才能学习好 💪</div>
            <button class="rest-reminder-btn" id="restReminderBtn">好的，我去休息</button>
        </div>
    `;
    document.body.appendChild(overlay);
    document.getElementById('restReminderBtn').addEventListener('click', () => {
        overlay.classList.remove('show');
    });
}

function showRestReminder(hours) {
    createRestReminderDOM();
    const hoursEl = document.getElementById('restReminderHours');
    if (hoursEl) hoursEl.textContent = hours;
    const overlay = document.getElementById('restReminderOverlay');
    if (overlay) {
        setTimeout(() => overlay.classList.add('show'), 200);
    }
}

function initHourlyRestReminder() {
    const userId = getUserId();
    if (!userId) return;

    // 读取今天已提醒过的小时数
    const key = getRestReminderKey(userId);
    lastRestReminderHour = parseInt(localStorage.getItem(key) || '0', 10);

    // 每 60 秒检测一次是否达到新的整小时
    setInterval(() => {
        const stored = getStoredTodaySeconds();
        const sessionDelta = getCurrentSessionSeconds() - lastSavedSessionSec;
        const totalSec = stored + sessionDelta;
        const totalHours = Math.floor(totalSec / 3600);

        // 如果达到了新的整小时且未提醒过
        if (totalHours > 0 && totalHours > lastRestReminderHour) {
            lastRestReminderHour = totalHours;
            localStorage.setItem(key, String(totalHours));
            showRestReminder(totalHours);
        }
    }, 60000); // 每分钟检测一次
}

async function checkBadge() {
    try {
        const userId = getUserId();
        const data = await getLearningAnalytics(userId);
        if (data && data.forgetting_curve) {
            const needsReview = data.forgetting_curve.filter(i => i.needs_review);
            if (needsReview.length > 0) {
                const badge = document.getElementById('aiBotBadge');
                if (badge) badge.classList.add('show');
            }
        }
    } catch (e) { /* ignore */ }
}

// 页面加载后初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
