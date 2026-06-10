# 邮件服务设计方案

## 1. 概述

### 1.1 背景

当前系统仅支持用户名+密码注册，缺少邮箱验证、密码重置和学习报告邮件推送等功能。本方案为系统引入完整的邮件服务。

### 1.2 目标

- 用户注册时绑定邮箱，支持邮箱验证
- 支持通过邮箱重置密码
- 支持向用户发送学习报告等通知邮件
- 架构简洁，与现有异步 FastAPI + PostgreSQL 技术栈一致

### 1.3 非目标

- 不做邮件营销/批量群发系统
- 不做邮件模板的可视化编辑器
- 不做邮件追踪（打开率、点击率等）

---

## 2. 技术方案

### 2.1 技术选型

| 组件 | 选型 | 原因 |
|------|------|------|
| 邮件库 | `aiosmtplib` | 纯异步，无需额外依赖，与项目 async 风格一致 |
| 模板引擎 | `Jinja2` | FastAPI 默认模板引擎，支持 HTML 邮件模板 |
| 序列化/反序列化 | 现有 `PyJWT` | 生成有时限的验证 token，无需引入新库 |

`aiosmtplib` 是目前最成熟的 Python 异步 SMTP 库，Starlette（FastAPI 的底层框架）官方文档推荐使用。

### 2.2 新增依赖

```
# requirements.txt 新增
aiosmtplib>=4.0.0
```

`Jinja2` FastAPI 已自带，无需额外添加。

---

## 3. 数据库变更

### 3.1 User 表新增字段

```sql
ALTER TABLE "user" ADD COLUMN email VARCHAR(256);
ALTER TABLE "user" ADD COLUMN email_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE "user" ADD COLUMN email_verified_at TIMESTAMP;
```

`email` 添加唯一索引（允许 NULL，因存量用户无邮箱）：

```sql
CREATE UNIQUE INDEX idx_user_email ON "user" (email) WHERE email IS NOT NULL;
```

### 3.2 新增 email_verification 表

```sql
CREATE TABLE email_verification (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    token VARCHAR(256) NOT NULL UNIQUE,
    purpose VARCHAR(32) NOT NULL,   -- 'email_verify' | 'password_reset'
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_email_verification_token ON email_verification (token);
```

### 3.3 ORM 模型变更（`backend/db/models.py`）

User 模型新增字段：

```python
class User(Base):
    __tablename__ = "user"
    # ... 现有字段 ...
    email: Mapped[Optional[str]] = mapped_column(String(256), unique=True, nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

新增 EmailVerification 模型：

```python
class EmailVerification(Base):
    __tablename__ = "email_verification"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

---

## 4. 配置设计

### 4.1 `configs/config.yaml` 新增

```yaml
email:
  smtp_host: "${SMTP_HOST}"
  smtp_port: "${SMTP_PORT}"
  smtp_username: "${SMTP_USERNAME}"
  smtp_password: "${SMTP_PASSWORD}"
  smtp_from: "${SMTP_FROM}"            # 发件人地址，如 "学习系统 <noreply@example.com>"
  smtp_use_tls: true
  smtp_timeout: 30                      # SMTP 连接超时（秒）
  max_retries: 3                        # 发送失败重试次数
  verification_expire_minutes: 30       # 邮箱验证链接有效期
  password_reset_expire_minutes: 15     # 密码重置链接有效期
  rate_limit_send_per_hour: 5           # 每用户每小时最大发送次数
```

### 4.2 `.env.example` 新增

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_FROM=学习系统 <noreply@example.com>
```

### 4.3 SMTP 配置参数说明

这些参数需要填入**实际使用的邮件服务商**提供的 SMTP 信息。以下是字段释义和常见服务商的填写指引。

#### 字段释义

| 参数 | 说明 |
|------|------|
| `SMTP_HOST` | 邮件服务商的 SMTP 服务器地址 |
| `SMTP_PORT` | SMTP 端口，一般为 `587`（STARTTLS）或 `465`（SSL） |
| `SMTP_USERNAME` | SMTP 认证用户名，通常为你的完整邮箱地址 |
| `SMTP_PASSWORD` | SMTP 认证密码，通常是邮箱服务商提供的**授权码**（非邮箱登录密码） |
| `SMTP_FROM` | 发件人显示名称和地址，格式为 `显示名 <地址>`，地址需与 `SMTP_USERNAME` 一致 |

#### 国内常见邮件服务商

| 服务商 | SMTP_HOST | SMTP_PORT | SMTP_USERNAME | 说明 |
|--------|-----------|-----------|---------------|------|
| **QQ邮箱** | `smtp.qq.com` | 587 | 你的QQ邮箱地址 | 需在QQ邮箱设置中开启SMTP服务，获取**授权码** |
| **163邮箱** | `smtp.163.com` | 465 | 你的163邮箱地址 | 同上，需开启SMTP获取授权码 |
| **126邮箱** | `smtp.126.com` | 465 | 你的126邮箱地址 | 同上 |
| **阿里云邮箱** | `smtp.aliyun.com` | 465 | 你的阿里云邮箱 | 同上 |
| **企业微信** | `smtp.exmail.qq.com` | 587 | 企业邮箱地址 | 企业管理员需开启SMTP |
| **Outlook** | `smtp-mail.outlook.com` | 587 | 你的Outlook邮箱 | 需在微软账户安全设置中开启 |
| **Gmail** | `smtp.gmail.com` | 587 | 你的Gmail地址 | 需开启两步验证并生成**应用专用密码** |

#### 推荐：QQ邮箱 SMTP 开通步骤

QQ邮箱开通最为简单，适合开发测试：

1. 登录 [QQ邮箱](https://mail.qq.com) → **设置** → **账户**
2. 找到 "POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务" → 开启 **POP3/SMTP服务**
3. 按提示发送短信验证 → 系统生成一个 16 位**授权码**
4. 将该授权码填入 `SMTP_PASSWORD`

#### 示例配置（以 QQ邮箱为例）

```bash
# 假设 QQ邮箱为 12345678@qq.com，授权码为 abcdefghijklmnop
SMTP_HOST=smtp.qq.com
SMTP_PORT=587
SMTP_USERNAME=12345678@qq.com
SMTP_PASSWORD=abcdefghijklmnop          # 授权码，不是QQ密码！
SMTP_FROM=学习系统 <12345678@qq.com>     # 发件人地址须与SMTP_USERNAME一致
```

#### 注意事项

- `SMTP_PASSWORD` 填的是**授权码**，不是邮箱登录密码——几乎所有国内邮箱服务商都要求使用授权码
- `SMTP_FROM` 中的发件人地址**必须**与 `SMTP_USERNAME` 一致，大部分服务商会校验此一致性
- 这些属于敏感信息，通过 `.env` 文件注入，**不要提交到 git**。项目已有的 `.env` → `.env.example` 脱敏机制可直接复用
- 如果 SMTP 未配置（`SMTP_HOST` 或 `SMTP_PASSWORD` 为空），系统会降级运行：邮件相关接口返回友好提示，其他功能不受影响

### 4.4 `backend/config.py` 新增

```python
class EmailConfig(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    smtp_timeout: int = 30
    max_retries: int = 3
    verification_expire_minutes: int = 30
    password_reset_expire_minutes: int = 15
    rate_limit_send_per_hour: int = 5
```

---

## 5. 代码架构

### 5.1 文件结构

```
backend/
├── email/
│   ├── __init__.py
│   ├── sender.py         # SMTP 连接与发送（核心）
│   ├── templates.py      # Jinja2 模板渲染
│   └── utils.py          # Token 生成/验证等辅助函数
├── templates/
│   └── email/
│       ├── verify_email.html      # 邮箱验证邮件模板
│       ├── reset_password.html    # 密码重置邮件模板
│       └── learning_report.html   # 学习报告邮件模板
```

### 5.2 `sender.py` — 邮件发送核心

```python
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import config


class EmailSender:
    """异步邮件发送器，封装 aiosmtplib"""

    def __init__(self):
        cfg = config.email
        self._host = cfg.smtp_host
        self._port = cfg.smtp_port
        self._username = cfg.smtp_username
        self._password = cfg.smtp_password
        self._from = cfg.smtp_from
        self._use_tls = cfg.smtp_use_tls
        self._timeout = cfg.smtp_timeout
        self._enabled = bool(cfg.smtp_host and cfg.smtp_password)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @retry(
        stop=stop_after_attempt(config.email.max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=30),
    )
    async def send(self, to: str, subject: str, html: str) -> bool:
        """发送 HTML 邮件，失败时自动重试"""
        if not self._enabled:
            logger.warning("[Email] SMTP 未配置，跳过发送: {}", subject)
            return False

        msg = MIMEMultipart("alternative")
        msg["From"] = self._from
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                use_tls=self._use_tls,
                timeout=self._timeout,
            )
            logger.success("[Email] 发送成功: to={}, subject={}", to, subject)
            return True
        except Exception as e:
            logger.exception("[Email] 发送失败: to={}, subject={}, error={}", to, subject, e)
            raise

    async def send_verification(self, to: str, username: str, token: str) -> bool:
        ...

    async def send_password_reset(self, to: str, username: str, token: str) -> bool:
        ...

    async def send_learning_report(self, to: str, username: str, report_html: str) -> bool:
        ...


# 模块级单例，风格与现有 config 一致
email_sender = EmailSender()
```

### 5.3 `utils.py` — Token 工具

```python
import secrets
import hashlib
from datetime import datetime, timedelta

from backend.config import config


def generate_token() -> str:
    """生成 URL 安全的随机 token"""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 哈希 token，数据库存储哈希值防泄露"""
    return hashlib.sha256(token.encode()).hexdigest()


def expires_at(purpose: str) -> datetime:
    if purpose == "email_verify":
        minutes = config.email.verification_expire_minutes
    elif purpose == "password_reset":
        minutes = config.email.password_reset_expire_minutes
    else:
        minutes = 30
    return datetime.utcnow() + timedelta(minutes=minutes)
```

### 5.4 `templates.py` — 模板渲染

```python
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path

_templates_dir = Path(__file__).resolve().parent.parent / "templates" / "email"
_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=select_autoescape(["html"]),
)


def render_verify_email(username: str, verify_url: str) -> str:
    return _env.get_template("verify_email.html").render(
        username=username, verify_url=verify_url
    )


def render_reset_password(username: str, reset_url: str) -> str:
    return _env.get_template("reset_password.html").render(
        username=username, reset_url=reset_url
    )
```

---

## 6. API 设计

### 6.1 注册改造 `POST /auth/register`

**变更：** 请求体新增可选 `email` 字段。

```json
// Request
{
    "username": "zhangsan",
    "password": "123456",
    "email": "zhangsan@example.com"     // 可选
}

// Response（保持不变）
{
    "id": "...",
    "username": "zhangsan",
    "email": "zhangsan@example.com",
    "created_at": "2026-06-03T..."
}
```

注册成功后，如果提供了邮箱，异步发送验证邮件。

### 6.2 发送验证邮件 `POST /auth/send-verification`

已有邮箱的用户可请求重新发送验证邮件。

```json
// Request
{
    "user_id": 123456789           // 从 JWT 解析，非请求体传入
}

// Response
{
    "message": "验证邮件已发送"
}
```

### 6.3 验证邮箱 `GET /auth/verify-email?token={token}`

用户点击邮件中的链接后访问此端点。

```json
// Response（验证成功）
{
    "message": "邮箱验证成功"
}

// Response（token 无效或过期）
{
    "detail": "验证链接已过期或无效"
}
```

验证成功后重定向到前端页面。

### 6.4 忘记密码 `POST /auth/forgot-password`

```json
// Request
{
    "email": "zhangsan@example.com"
}

// Response（无论邮箱是否存在，统一返回成功以防枚举攻击）
{
    "message": "如果该邮箱已注册，重置密码邮件已发送"
}
```

### 6.5 重置密码 `POST /auth/reset-password`

```json
// Request
{
    "token": "...",
    "new_password": "newpassword123"
}

// Response
{
    "message": "密码重置成功"
}
```

### 6.6 发送学习报告 `POST /email/learning-report`

```json
// Request
{
    "user_id": 123456789          // 从 JWT 解析
}

// Response
{
    "message": "学习报告已发送至 xxx@example.com"
}
```

### 6.7 完整路由汇总

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| `POST` | `/auth/register` | 无 | 注册（新增 email 字段） |
| `POST` | `/auth/send-verification` | Bearer Token | 发送/重发验证邮件 |
| `GET` | `/auth/verify-email` | 无（token 验证） | 验证邮箱 |
| `POST` | `/auth/forgot-password` | 无 | 发送密码重置邮件 |
| `POST` | `/auth/reset-password` | 无（token 验证） | 重置密码 |
| `POST` | `/email/learning-report` | Bearer Token | 发送学习报告 |

---

## 7. 安全设计

### 7.1 Token 安全

- 使用 `secrets.token_urlsafe(48)` 生成 384 位熵值的随机 token
- 数据库存储 token 的 **SHA-256 哈希值**，而非明文 token，防止数据库泄露后 token 被直接利用
- Token 有效期：验证邮件 30 分钟，密码重置 15 分钟
- Token 一次性使用，使用后标记 `used = True`

### 7.2 防枚举攻击

- `/auth/forgot-password` 无论邮箱是否存在均返回相同消息
- 密码重置不要透露"用户不存在" vs "邮件已发送"的差异

### 7.3 频率限制

```python
# 每用户每小时最多 N 次（可后续扩展 Redis 实现，初期用内存 dict）
RATE_LIMIT: dict[int, list[datetime]] = {}
```

### 7.4 前端页面

需要新增以下前端页面（均在 `frontend/` 下）：

| 页面 | 路径 | 说明 |
|------|------|------|
| `verify-email.html` | `/app/verify-email.html` | 验证结果展示页 |
| `reset-password.html` | `/app/reset-password.html` | 重置密码表单页 |
| `forgot-password.html` | `/app/forgot-password.html` | 忘记密码入口页 |

---

## 8. 邮件模板示例

### 8.1 验证邮件

```
主题: [学习系统] 请验证您的邮箱地址

您好 {username}，

感谢注册学习系统！请点击下方链接验证您的邮箱地址：

[ 验证邮箱 ]（按钮，链接到 {verify_url}）

此链接将在 30 分钟内有效。如果您未注册此账号，请忽略此邮件。

---
个性化资源生成与学习多智能体系统
```

### 8.2 密码重置邮件

```
主题: [学习系统] 密码重置请求

您好 {username}，

我们收到了您重置密码的请求。请点击下方链接重置密码：

[ 重置密码 ]（按钮，链接到 {reset_url}）

此链接将在 15 分钟内有效。如果您未请求重置密码，请忽略此邮件。

---
个性化资源生成与学习多智能体系统
```

### 8.3 学习报告邮件

```
主题: [学习系统] 您的学习报告（{日期}）

您好 {username}，

以下是您本周的学习报告：

| 指标 | 数据 |
|------|------|
| 学习资源数 | {resource_count} |
| 完成测验数 | {quiz_count} |
| 平均掌握度 | {mastery}% |
| 学习路径数 | {pathway_count} |

[ 查看完整报告 ]（链接到前端学习分析页）

---
个性化资源生成与学习多智能体系统
```

---

## 9. 实现计划

### 阶段一：基础设施（P0）

1. 新增 `aiosmtplib` 依赖
2. `configs/config.yaml` + `.env.example` + `backend/config.py` 新增邮件配置
3. `backend/db/models.py` — User 模型新增 email 字段，新增 EmailVerification 模型
4. Alembic 数据库迁移
5. `backend/email/sender.py` — 邮件发送核心
6. `backend/email/utils.py` — Token 工具
7. `backend/email/templates.py` — 模板渲染
8. `backend/templates/email/` — 邮件 HTML 模板

### 阶段二：邮箱验证与密码重置（P1）

9. 注册接口改造：接受 email 参数，注册后发送验证邮件
10. `POST /auth/send-verification`
11. `GET /auth/verify-email`
12. `POST /auth/forgot-password`
13. `POST /auth/reset-password`
14. 频率限制中间件
15. 前端页面：forgot-password, reset-password, verify-email

### 阶段三：学习报告邮件推送（P2）

16. `POST /email/learning-report`
17. 学习报告 HTML 模板
18. 前端学习报告页面跳转链接

---

## 10. 测试要点

| 测试场景 | 验证点 |
|----------|--------|
| 注册时提供邮箱 | 自动发送验证邮件，数据库中 email 和 token 记录正确 |
| 点击有效验证链接 | 邮箱标记为已验证，token 标记为已使用 |
| 点击过期验证链接 | 返回错误，不修改邮箱状态 |
| 重用已使用的 token | 返回错误 |
| 忘记密码（邮箱不存在） | 返回统一成功消息 |
| 忘记密码（邮箱存在） | 生成 token，发送邮件 |
| 重置密码后旧 token 失效 | 旧 token 无法再次使用 |
| SMTP 未配置 | 系统正常运行，邮件相关接口返回友好提示 |
| 频率限制触发 | 第 6 次请求返回 429 |
