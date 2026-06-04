# Nginx 引入方案详解

## 一、为什么需要 Nginx

当前项目架构中，uvicorn 直接监听 8000 端口对外服务，承担了 API 处理、静态文件服务、CORS 等全部职责。引入 nginx 作为前端反向代理，能解决以下问题：

| 能力 | 当前状态 | Nginx 接管后 |
|------|----------|-------------|
| SSL/TLS 终端 | 无，纯 HTTP | nginx 统一处理 HTTPS |
| 静态文件服务 | FastAPI `StaticFiles`，占用 Python 进程 | nginx 直接返回，零 Python 开销 |
| 限流保护 | 无，LLM 接口无调用频率限制 | nginx `limit_req` 基于 IP/接口限流 |
| 请求体大小限制 | 无，文件上传无上限 | nginx `client_max_body_size` 拦截超大请求 |
| 安全响应头 | 无 | 统一注入 HSTS、CSP、X-Frame-Options 等 |
| Gzip 压缩 | FastAPI 无内置压缩 | nginx gzip 压缩文本响应，节省带宽 |
| 连接管理 | 依赖 uvicorn 自身 | nginx 缓冲慢客户端，保护后端连接池 |
| 灰度发布 | 不支持 | nginx 分流到不同端口/版本 |

简而言之：**nginx 让 uvicorn 回归本职（处理业务逻辑），将通用基础设施职责（加密、压缩、限流、静态文件）剥离到更高效的反向代理层。**

---

## 二、目标架构

```
                        HTTPS (443)
                     ┌───────────────┐
      浏览器          │               │
    (前端页面)  ────▶ │    Nginx      │
                      │  (反向代理)    │
                      │               │
                      └───────┬───────┘
                              │
                ┌─────────────┼─────────────┐
                │             │             │
           /app/*         /api/*         /* (其他)
          静态文件        API 路由       API 路由
         直接返回       proxy_pass     proxy_pass
         (html/css/js)     │               │
                           ▼               ▼
                      ┌────────────────────────┐
                      │   uvicorn (127.0.0.1)   │
                      │   端口 8000 (仅本地)     │
                      │   FastAPI 应用           │
                      └────────────────────────┘
```

**核心变化：**
- Nginx 监听 443 端口（HTTPS），对外暴露
- uvicorn 仅监听 `127.0.0.1:8000`，不再直接暴露公网
- `/app/*` 的静态文件由 nginx 直接从磁盘读取返回，不再经过 FastAPI
- 其余 API 请求由 nginx 代理到后端 uvicorn

---

## 三、Nginx 安装（Windows）

本项目开发环境为 Windows 11，以下为 Windows 下的安装方式。

### 方式一：直接下载（推荐）

1. 访问 [nginx.org/en/download.html](https://nginx.org/en/download.html)
2. 下载最新稳定版（如 nginx-1.26.x.zip）
3. 解压到固定目录，如 `C:\nginx\`
4. 将 `C:\nginx` 添加到系统环境变量 PATH

```powershell
# 验证安装
nginx -v
# nginx version: nginx/1.26.x
```

### 方式二：通过包管理器

```powershell
# 使用 Scoop
scoop install nginx

# 或使用 Chocolatey
choco install nginx
```

### 基本命令

```powershell
nginx                    # 启动
nginx -s reload          # 热重载配置（不中断服务）
nginx -s stop            # 快速停止
nginx -s quit            # 优雅停止（处理完当前请求后退出）
nginx -t                 # 测试配置文件语法
```

---

## 四、Nginx 配置文件

以下为完整的 `nginx.conf`，基于本项目实际结构定制。将以下内容保存为配置文件（如 `deploy/nginx.conf`）。

```nginx
# ============================================================
# softbei 项目 Nginx 配置
# 适用场景：Windows 开发环境 / Linux 生产部署
# 配置文件路径：项目根目录 deploy/nginx.conf
# ============================================================

# ---- 全局工作进程配置 ----
worker_processes  auto;              # 自动匹配 CPU 核心数
worker_rlimit_nofile  65535;         # 每个 worker 最大文件句柄

events {
    worker_connections  4096;        # 每个 worker 最大连接数
    multi_accept        on;          # 一次接受所有新连接
    use                 epoll;       # Linux 用 epoll；Windows 自动忽略
}

http {
    # ---- 基础优化 ----
    include       mime.types;
    default_type  application/octet-stream;
    sendfile      on;                # 零拷贝发送静态文件
    tcp_nopush    on;                # 发送前打包，减少网络包
    tcp_nodelay   on;                # keep-alive 连接禁用 Nagle 算法
    keepalive_timeout  65;
    server_tokens off;               # 隐藏 nginx 版本号

    # ---- Gzip 压缩 ----
    gzip              on;
    gzip_vary         on;
    gzip_proxied      any;
    gzip_comp_level   6;
    gzip_min_length   256;
    gzip_types
        text/plain
        text/css
        text/javascript
        application/javascript
        application/json
        application/xml
        image/svg+xml;

    # ---- 日志格式（含 trace_id 透传） ----
    log_format main '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    'trace_id=$http_x_trace_id '
                    'rt=$request_time s';

    access_log  logs/access.log  main;
    error_log   logs/error.log   warn;

    # ---- 限流规则定义 ----
    # 通用 API 限流：每个 IP 每秒 30 请求，突发 20
    limit_req_zone $binary_remote_addr zone=api_zone:10m rate=30r/s;

    # 登录接口限流：每个 IP 每分钟 10 请求（防暴力破解）
    limit_req_zone $binary_remote_addr zone=login_zone:10m rate=10r/m;

    # 生成接口限流：每个 IP 每分钟 5 请求（LLM 调用有成本）
    limit_req_zone $binary_remote_addr zone=generate_zone:10m rate=5r/m;

    # 并发连接限制：每个 IP 最多 20 个并发连接
    limit_conn_zone $binary_remote_addr zone=conn_per_ip:10m;

    # ---- 后端 upstream 定义 ----
    upstream backend {
        # uvicorn 仅监听本地回环，不暴露公网
        server 127.0.0.1:8000;
        keepalive 32;  # 到后端的 keep-alive 连接池
    }

    # ============================================================
    # HTTP → HTTPS 重定向（开发阶段可选）
    # ============================================================
    server {
        listen       80;
        server_name  localhost;
        return 301   https://$host$request_uri;
    }

    # ============================================================
    # 主站点 — HTTPS
    # ============================================================
    server {
        listen              443 ssl;
        http2              on;
        server_name         localhost;

        # ---- SSL 证书 ----
        # 开发环境：使用自签名证书（见第五章生成方法）
        ssl_certificate      certs/softbei.crt;
        ssl_certificate_key  certs/softbei.key;

        # ---- SSL 安全配置 ----
        ssl_protocols             TLSv1.2 TLSv1.3;
        ssl_ciphers               HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;
        ssl_session_cache         shared:SSL:10m;
        ssl_session_timeout       10m;

        # ---- 安全响应头 ----
        add_header X-Frame-Options           "SAMEORIGIN"     always;
        add_header X-Content-Type-Options    "nosniff"         always;
        add_header X-XSS-Protection          "1; mode=block"   always;
        add_header Referrer-Policy           "strict-origin-when-cross-origin" always;
        add_header Strict-Transport-Security "max-age=63072000" always;

        # ---- 连接与请求体限制 ----
        limit_conn          conn_per_ip 20;
        client_max_body_size 50m;            # 文件上传上限 50MB
        client_body_timeout  60s;
        client_header_timeout 30s;

        # ========================================================
        # 静态文件 — /app/*
        # 前端 HTML/CSS/JS 由 nginx 直接返回，不经过 uvicorn
        # 注意：路径必须与项目 frontend/ 目录对应
        # ========================================================
        location /app {
            alias  "D:/PClearning/AgentProjects/softbei/frontend/";
            index  index.html;
            try_files $uri $uri/ /app/index.html;  # SPA 回退

            # 静态资源缓存策略
            location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?|ttf)$ {
                expires 7d;
                add_header Cache-Control "public, immutable";
            }

            # HTML 不缓存（确保更新后立即生效）
            location ~* \.html$ {
                expires -1;
                add_header Cache-Control "no-cache";
            }
        }

        # ---- SPA 页面入口映射 ----
        # 让用户可以通过 /app/auth、/app/chat 等短路径直接访问
        # （依赖前端已有的 SPA 路由，如果前端是多页面应用则无需此段）

        # ========================================================
        # API 代理 — 按接口类型分组限流
        # ========================================================

        # 登录/注册 — 严格限流
        location /auth/ {
            limit_req zone=login_zone burst=5 nodelay;
            proxy_pass http://backend;
            include    proxy_params;
        }

        # 生成接口 — LLM 调用成本高，严格限流
        location /generate {
            limit_req zone=generate_zone burst=3 nodelay;
            proxy_pass http://backend;
            include    proxy_params;
        }
        location /generate/ {
            limit_req zone=generate_zone burst=3 nodelay;
            proxy_pass http://backend;
            include    proxy_params;
        }

        # 文档导入 — 上传文件，增大超时
        location /documents/ {
            proxy_pass http://backend;
            include    proxy_params;
            proxy_read_timeout 180s;   # 导入+索引耗时较长
            proxy_send_timeout 180s;
        }

        # 知识图谱构建 — 长时间运行任务
        location /kg/build {
            proxy_pass http://backend;
            include    proxy_params;
            proxy_read_timeout 300s;
        }

        # 健康检查 — 不限流
        location /health {
            proxy_pass http://backend;
            include    proxy_params;
        }

        # 其余所有 API — 通用限流
        location / {
            limit_req zone=api_zone burst=20 nodelay;
            proxy_pass http://backend;
            include    proxy_params;
        }
    }
}
```

### 代理参数文件 `proxy_params`

在 nginx 的 `conf/` 目录下创建 `proxy_params` 文件（或在 `nginx.conf` 中直接引用一个 include 文件），内容如下：

```nginx
# ---- 代理通用参数 ----
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host  $host;
proxy_set_header X-Forwarded-Port  $server_port;

# 透传原始 trace_id（若前端已生成则保留，否则由后端中间件生成）
proxy_set_header X-Trace-ID        $http_x_trace_id;

# 代理超时
proxy_connect_timeout   10s;
proxy_read_timeout      120s;   # LLM 调用可能较长
proxy_send_timeout      30s;

# 代理缓冲
proxy_buffering         on;
proxy_buffer_size       16k;
proxy_buffers           8 16k;
proxy_busy_buffers_size 32k;

# HTTP 版本与连接复用
proxy_http_version      1.1;
proxy_set_header        Connection "";
```

---

## 五、自签名证书生成（开发环境）

### Windows（PowerShell）

```powershell
# 创建 certs 目录
mkdir D:\PClearning\AgentProjects\softbei\deploy\certs

# 生成自签名证书 + 私钥（有效期 365 天）
openssl req -x509 -nodes -days 365 -newkey rsa:2048 `
  -keyout D:\PClearning\AgentProjects\softbei\deploy\certs\softbei.key `
  -out D:\PClearning\AgentProjects\softbei\deploy\certs\softbei.crt `
  -subj "/CN=localhost"

# 如果没有 openssl，用 PowerShell 原生方式：
$cert = New-SelfSignedCertificate -DnsName "localhost" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -NotAfter (Get-Date).AddYears(1)
# 然后从证书管理器中导出 .pfx 再转换
```

### 浏览器信任自签名证书

开发时浏览器会提示"不安全"，可双击 `.crt` 文件导入到"受信任的根证书颁发机构"。

---

## 六、FastAPI 侧配合修改

引入 nginx 后，FastAPI 侧需要做少量调整：

### 6.1 启动命令调整

```bash
# 之前：监听所有接口，直接对外
# uvicorn backend.main:app --reload --port 8000

# 之后：仅监听本地回环，由 nginx 代理访问
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 6.2 CORS 收紧（`configs/config.yaml`）

```yaml
server:
  version: "0.1.0"
  # 当前为 ["*"]，nginx 接入后可改为具体域名
  cors_origins:
    - "https://localhost"
    - "https://your-domain.com"
```

> 开发阶段可暂保留 `["*"]`，但生产环境务必收紧。

### 6.3 信任代理头

在 `backend/main.py` 中添加对转发头的信任（让 `request.client.host` 能拿到真实 IP）：

```python
from fastapi.middleware.trustedhost import TrustedHostMiddleware

# 信任 nginx 转发的头信息
# （仅当 uvicorn 不直接暴露时才安全）
```

或者使用 `--proxy-headers` 启动参数：

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --proxy-headers
```

### 6.4 无需修改的部分

- **前端代码**：`api.js` 中 `API_BASE = window.location.origin`，通过 nginx 代理后 origin 不变，无需修改。
- **鉴权逻辑**：JWT 通过 `Authorization` 头传递，nginx 默认透传，无需修改。
- **WebSocket/SSE**：nginx HTTP/2 默认支持，聊天流式接口可正常工作。

---

## 七、部署步骤

### 7.1 开发环境部署流程

```powershell
# 1. 启动后端（仅监听本地）
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# 2. 测试 nginx 配置
nginx -t -c D:\PClearning\AgentProjects\softbei\deploy\nginx.conf

# 3. 启动 nginx
nginx -c D:\PClearning\AgentProjects\softbei\deploy\nginx.conf

# 4. 浏览器访问
# https://localhost/app        → 前端页面
# https://localhost/health     → API 健康检查
```

### 7.2 修改配置后热重载

```powershell
nginx -s reload
```

### 7.3 生产环境部署（Linux）

```bash
# 1. 安装 nginx
sudo apt install nginx  # Ubuntu/Debian

# 2. 复制配置文件
sudo cp deploy/nginx.conf /etc/nginx/sites-available/softbei
sudo ln -s /etc/nginx/sites-available/softbei /etc/nginx/sites-enabled/

# 3. 替换证书路径为正式 CA 签发的证书（如 Let's Encrypt）
# ssl_certificate     /etc/letsencrypt/live/your-domain/fullchain.pem
# ssl_certificate_key /etc/letsencrypt/live/your-domain/privkey.pem

# 4. 启动
sudo systemctl enable nginx
sudo systemctl start nginx
sudo systemctl start softbei-backend  # uvicorn 的 systemd 服务
```

---

## 八、验证清单

部署完成后按以下步骤验证：

| # | 验证项 | 预期结果 |
|---|--------|---------|
| 1 | `nginx -t` | 配置文件语法通过 |
| 2 | 访问 `https://localhost/health` | 返回 `{"status": "ok"}` |
| 3 | 访问 `https://localhost/app` | 显示前端首页 |
| 4 | 访问 `https://localhost/app/chat.html` | 显示聊天页面 |
| 5 | 登录接口正常 | 能正常注册/登录 |
| 6 | 文件上传 `POST /documents/import/async` | 50MB 以内文件正常上传 |
| 7 | 访问 `http://localhost` | 自动 301 重定向到 HTTPS |
| 8 | 快速连续请求 `/auth/login` 超过 10 次/分钟 | 返回 503（触发限流） |
| 9 | 检查响应头 | 包含安全头（X-Frame-Options 等） |
| 10 | 检查 nginx access.log | 包含 `trace_id` 字段 |

---

## 九、常见问题

### Q1：Nginx 启动报错 "bind() to 0.0.0.0:443 failed"

443 端口被占用。检查是否有其他进程占用：

```powershell
netstat -ano | findstr :443
```

### Q2：静态文件 404

检查 `nginx.conf` 中 `alias` 路径与项目实际路径一致。Windows 下路径注意使用正斜杠 `/`，如 `D:/PClearning/AgentProjects/softbei/frontend/`。

### Q3：API 返回 502 Bad Gateway

后端 uvicorn 未启动或端口不正确。确认：
```powershell
netstat -ano | findstr :8000
```

### Q4：WebSocket 连接失败

确保 `proxy_params` 中包含：
```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

### Q5：前端上传大文件超时

在对应的 location 块中增大 `proxy_read_timeout` 和 `client_body_timeout`。

---

## 十、文件清单

引入 nginx 后项目新增/修改的文件：

```
softbei/
├── deploy/
│   ├── nginx.conf                 # [新增] Nginx 主配置文件
│   ├── proxy_params               # [新增] 代理通用参数
│   └── certs/
│       ├── softbei.crt            # [新增] SSL 证书（不提交到 Git）
│       └── softbei.key            # [新增] SSL 私钥（不提交到 Git，加入 .gitignore）
├── configs/
│   └── config.yaml                # [修改] cors_origins 从 ["*"] 改为具体域名
├── .gitignore                     # [修改] 添加 deploy/certs/*
└── README.md                      # [修改] 更新启动命令
```
