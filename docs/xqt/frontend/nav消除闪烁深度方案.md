# 导航消除闪烁 — 深度方案

> **状态：已实施。** 本文描述的 Turbo-lite 方案已在 `nav.js` 中实现为 SPA 侧边栏导航系统（`registerPage` + `navigateTo` + fetch + DOM swap + `startViewTransition`），侧边栏（而非顶栏）作为持久化导航外壳。

## 为什么 View Transition API 不够

`<meta name="view-transition">` 依然走完整页面重载流程：卸载旧页 → 网络请求 → 解析 HTML → 构建 DOM → 加载 CSS/JS → 首次渲染 → VT 动画。中间的网络延迟和渲染管线是无法用 CSS 消除的。

## 已实施方案：拦截导航 + 原地换内容（Turbo-lite）

### 原理（当前 nav.js 实现）

```
┌─────────────────────────────────────────────┐
│  sidebar (position: fixed, 永不刷新)         │
├─────────────────────────────────────────────┤
│                                             │
│  <div id="view">                            │
│     点击导航 → fetch 目标页 → 原地替换内容     │
│  </div>                                     │
│                                             │
└─────────────────────────────────────────────┘
```

1. `nav.js` 拦截侧边栏内 `<a>` 的 click 事件
2. `fetch()` 获取目标页面 HTML（带缓存 `_pageCache`）
3. 用 `DOMParser` 解析，提取 `#view` 内的 HTML
4. `document.startViewTransition()` 包裹 DOM 替换（同文档 VT，无卸载）
5. `history.pushState()` 更新 URL
6. 通过 `registerPage(key, init, destroy)` 管理页面生命周期（清理 ECharts 实例、定时器）

### 页面结构约定

每个页面使用 `<div id="view">` 作为内容容器，侧边栏由 `nav.js` 注入到 `<body>` 中，不在各页面 HTML 中重复定义。

### 页面注册接口

```javascript
// 每个页面注册 init/destroy 生命周期函数
registerPage('index', init, destroy);
```

## 效果

- 点击侧边栏导航 → fetch 目标页（命中缓存则 0ms）→ 同文档 VT cross-fade → 完成
- 侧边栏 DOM 节点永不销毁，零闪烁
- 浏览器前进/后退通过 `popstate` 正确处理
