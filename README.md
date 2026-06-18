# 云跑步自动化平台 + PU口袋校园自动报名

安徽邮电职业技术学院一站式大学生体测跑步与第二课堂活动管理平台，支持云跑步自动化、PU口袋校园活动自动报名、签到二维码生成等功能。

---

## 功能特性

### 云跑步模块

- **自动跑步**：基于 GPS 轨迹点文件自动完成跑步任务，支持实时地图预览
- **定时任务**：支持创建定时跑步计划，到点自动执行
- **多学校支持**：内置多学校任务文件，管理员可按学校分类管理
- **任务管理**：支持上传、下载、删除自定义轨迹文件
- **跑步历史**：查看历史跑步记录、成绩详情、保存轨迹
- **邮件通知**：跑步完成/失败自动发送邮件通知

### PU口袋校园模块

- **账号绑定**：绑定口袋校园账号，自动同步学校信息
- **活动浏览**：查看学校活动列表，支持筛选未过期活动
- **自动报名**：支持手动报名和定时自动报名
- **自动托管**：开启后自动监控新活动，到点自动抢报
- **签到二维码**：本地生成实时签到二维码（DES 加密，30秒刷新）
- **多账号支持**：支持绑定多个口袋校园账号，并发处理
- **我的活动**：查看已报名/已完成的活动记录
- **Token 自动刷新**：Token 失效时自动重新登录，无需人工干预

### 管理后台

- **用户管理**：查看/编辑/删除用户，批量续期
- **学校任务管理**：按学校分类管理轨迹文件，支持上传下载
- **兑换码管理**：生成/管理兑换码，用于用户激活
- **设备管理**：管理可用设备列表
- **管理员管理**：支持多管理员，权限分级
- **系统配置**：公告、系统参数等配置管理
- **日志监控**：实时查看运行日志

---

## 技术架构

```
┌─────────────────────────────────────────────┐
│                  前端 (Flask Templates)       │
│   login.html │ index.html │ admin.html       │
│   signup.html │ admin_login.html              │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│               Flask 应用 (app.py)            │
│   用户认证 │ 跑步调度 │ PU报名 │ 管理后台     │
├─────────────────────────────────────────────┤
│   core.py        │  pu_core.py               │
│   (云跑步核心)    │  (PU口袋核心)              │
├─────────────────────────────────────────────┤
│   utils/pu_sign.py  │  utils/tools.py        │
│   (X-Sign 加密)      │  (邮件发送)             │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│            MySQL 8.0 (Docker 容器)           │
│   users │ pu_users │ admins │ devices ...    │
└─────────────────────────────────────────────┘
```

### 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask 3.0 |
| 数据库 | MySQL 8.0 (Docker) |
| 定时任务 | APScheduler |
| 加密 | pycryptodome (DES/AES)、gmssl (国密) |
| 二维码 | qrcode + Pillow |
| 部署 | Docker Compose |

---

## 项目结构

```
├── app.py                  # 主程序（路由、调度、管理后台）
├── core.py                 # 云跑步核心逻辑（登录、跑步、轨迹）
├── pu_core.py              # PU口袋校园核心逻辑（报名、二维码）
├── docker-compose.yml      # Docker 部署配置
├── Dockerfile              # 构建配置
├── requirements.txt        # Python 依赖
├── init_db.sql             # 数据库初始化脚本
├── templates/              # 页面模板
│   ├── login.html          # 登录页
│   ├── index.html          # 主页（跑步控制台）
│   ├── signup.html         # PU口袋报名页
│   ├── admin.html          # 管理后台
│   └── admin_login.html    # 管理员登录页
├── static/                 # 静态资源
│   ├── css/style.css
│   └── js/ (app.js, admin.js, login.js)
├── utils/                  # 工具类
│   ├── pu_sign.py          # X-Sign 加密（AES-CBC）
│   └── tools.py            # 邮件发送
├── data/                   # 运行时数据
│   ├── sessions.json
│   ├── cron_jobs.json
│   ├── run_logs.json
│   └── email_config.json
├── tasks/                  # 用户上传的轨迹文件
└── school_tasks/           # 学校内置轨迹文件
    ├── anhuiyoudian_girl/  # 女生轨迹
    └── anhuiyoudian_man/   # 男生轨迹
```

---

## 快速部署

### 环境要求

- Docker 20.0+
- Docker Compose 2.0+

### 部署步骤

```bash
# 1. 克隆项目
git clone https://github.com/zz77zz77/yunrun-web.git

# 2. 启动服务
docker compose up -d --build

# 3. 访问应用
# 用户端：http://your-server:80
# 管理后台：http://your-server:80/admin
```

首次访问管理后台会自动跳转到管理员设置页面。

### 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| yunrun-web | 80 | Web 应用 |
| yunrun-mysql | 3307 | MySQL 数据库（外部可连） |

### 数据持久化

| Volume | 说明 |
|--------|------|
| yunrun-data | 运行时配置数据 |
| yunrun-tasks | 用户任务文件 |
| yunrun-mysql-data | MySQL 数据 |

正常重启（`docker compose down` + `up`）**不会丢失数据**。只有 `docker compose down -v` 才会清除。

---

## 自定义配置

### 1. 修改访问端口

**文件：`docker-compose.yml` 第 11 行**

```yaml
ports:
  - "80:5000"     # 左边是外部访问端口，右边是容器内部端口（不要改）
```

改为其他端口（如 8080）：
```yaml
ports:
  - "8080:5000"
```

然后重启：`docker compose up -d yunrun-web`

---

### 2. 修改 MySQL 密码

需要同时修改 **两个地方**，密码必须一致：

**文件：`docker-compose.yml`**

```yaml
# yunrun-web 服务的 environment（第 22 行）
- MYSQL_PASSWORD=你的新密码

# yunrun-mysql 服务的 environment（第 38 行）
- MYSQL_ROOT_PASSWORD=你的新密码

# healthcheck 中的密码也要改（第 42 行）
test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p你的新密码"]
```

**文件：`app.py` 第 22 行**（默认值，环境变量优先）

```python
'password': os.environ.get('MYSQL_PASSWORD', '你的新密码'),
```

> ⚠️ 修改密码后需要重建 MySQL 容器：`docker compose down -v && docker compose up -d --build`

---

### 3. 修改 MySQL 端口

**文件：`docker-compose.yml` 第 33 行**

```yaml
ports:
  - "3307:3306"   # 左边是外部访问端口
```

---

### 4. 修改数据库名称

**文件：`docker-compose.yml`**

```yaml
# yunrun-web 的 environment
- MYSQL_DATABASE=你的数据库名

# yunrun-mysql 的 environment
- MYSQL_DATABASE=你的数据库名
```

**文件：`app.py` 第 23 行**

```python
'database': os.environ.get('MYSQL_DATABASE', '你的数据库名'),
```

---

### 5. 修改源码/数据目录路径

**文件：`docker-compose.yml` 第 12-16 行**

```yaml
volumes:
  - /your/path/to/code:/app              # 源码路径
  - yunrun-data:/app/data                # 运行数据（Docker volume）
  - yunrun-tasks:/app/tasks              # 用户任务文件
  - /your/path/to/school_tasks:/app/school_tasks  # 学校轨迹文件
```

---

### 6. 修改学校轨迹文件目录

轨迹文件存放在 `school_tasks/` 下，按学校名分子目录：

```
school_tasks/
├── 学校A_girl/     # 女生轨迹
│   ├── tasklist_0.json
│   └── tasklist_1.json
└── 学校A_man/      # 男生轨迹
    └── tasklist_0.json
```

**文件：`app.py` 第 104 行**

```python
SCHOOL_TASKS_BASE = os.path.join(BASE_DIR, 'school_tasks')
```

---

### 7. 配置高德地图

跑步轨迹地图使用高德地图 JS API 2.0，需要配置 **两个密钥**：

**获取步骤：**

1. 注册/登录 [高德开放平台](https://console.amap.com/)
2. 控制台 → 应用管理 → 创建新应用
3. 添加 Key → 服务平台选择「Web端(JS API)」
4. 创建完成后获得两个值：

```
Key:            xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
安全密钥:       xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

5. 登录管理后台 → 系统设置 → 高德地图配置 → 填入两个值 → 保存

> **注意：** Key 和安全密钥是配套的，缺一不可。如果只填 Key 不填安全密钥，地图会加载失败。

---

### 8. 配置邮件通知

登录管理后台 → 系统设置 → 邮件通知配置：

| 字段 | 说明 | 示例 |
|------|------|------|
| SMTP 服务器 | 邮箱的 SMTP 地址 | `smtp.qq.com` |
| 端口 | SMTP SSL 端口 | `465` |
| 发件人邮箱 | 你的邮箱地址 | `your@qq.com` |
| SMTP 授权码 | 邮箱的授权码（非登录密码） | 在邮箱设置中开启 SMTP 获取 |
| 发件人名称 | 显示的发件人名 | `云运动助手` |

填写完成后点击「发送测试」验证是否配置正确。

> **QQ邮箱授权码获取：** 设置 → 账户 → POP3/SMTP服务 → 开启 → 生成授权码

---

### 9. 修改自动托管轮询间隔

**文件：`app.py`，调用 `_start_pu_scheduler_loop` 时传入参数**

默认 10 秒，可在管理后台 API 中通过 `poll_interval` 参数调整，最小 3 秒。

---

### 10. 使用外部 MySQL（不用内置容器）

**文件：`docker-compose.yml`**

注释掉 `yunrun-mysql` 服务，修改 `yunrun-web` 的环境变量：

```yaml
environment:
  - MYSQL_HOST=你的数据库地址
  - MYSQL_PORT=3306
  - MYSQL_USER=root
  - MYSQL_PASSWORD=你的密码
  - MYSQL_DATABASE=yunrun
```

---

### 11. 修改管理员账号

首次访问 `/admin` 自动进入设置页面。如需重置：

```bash
# 进入 MySQL 容器
docker exec -it yunrun-mysql mysql -u root -pyunrun2026 yunrun

# 清空管理员表（会触发重新设置）
DELETE FROM admins;
```

---

### 12. 修改时区

**文件：`docker-compose.yml`，两个服务都要改：**

```yaml
environment:
  - TZ=Asia/Shanghai    # 改为你的时区
```

---

### 配置速查表

| 配置项 | 文件/位置 | 说明 |
|--------|----------|------|
| 访问端口 | `docker-compose.yml` | `ports: - "80:5000"` |
| MySQL 密码 | `docker-compose.yml` + `app.py` | 三处必须一致 |
| 数据库名 | `docker-compose.yml` + `app.py` | 两处必须一致 |
| 源码路径 | `docker-compose.yml` | `/opt/yunrun/web:/app` |
| 学校轨迹路径 | `app.py` `SCHOOL_TASKS_BASE` | 默认 `school_tasks/` |
| 高德地图 Key | 管理后台 → 系统设置 | 在高德开放平台申请 |
| 高德安全密钥 | 管理后台 → 系统设置 | 与 Key 配套，缺一不可 |
| 邮件 SMTP | 管理后台 → 系统设置 | 服务器/端口/账号/授权码 |
| 时区 | `docker-compose.yml` | `TZ=Asia/Shanghai` |
| MySQL 外部端口 | `docker-compose.yml` | `ports: - "3307:3306"` |

---

## API 接口

### 云跑步

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/login` | POST | 用户登录 |
| `/api/run/start` | POST | 开始跑步 |
| `/api/run/stop` | POST | 停止跑步 |
| `/api/run/events/<id>` | GET | SSE 实时事件流 |
| `/api/run/upload_task` | POST | 上传轨迹文件 |
| `/api/history/runs` | GET | 跑步历史 |
| `/api/cron/create` | POST | 创建定时任务 |

### PU口袋校园

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/signup/users/add` | POST | 绑定口袋账号 |
| `/api/signup/activities` | POST | 获取活动列表 |
| `/api/signup/my_activities` | POST | 我的活动记录 |
| `/api/signup/start` | POST | 手动报名 |
| `/api/signup/qrcode` | GET | 签到二维码 |
| `/api/signup/users/scheduler` | POST | 开关自动托管 |

### 管理后台

| 接口 | 方法 | 说明 |
|------|------|------|
| `/admin/api/setup` | POST | 首次设置管理员 |
| `/admin/api/users` | GET | 用户列表 |
| `/admin/api/school_folders` | GET | 学校任务管理 |
| `/admin/api/devices` | GET | 设备管理 |

---

## 自动托管工作流程

```
用户开启自动托管
    │
    ▼
调度器每 10 秒轮询
    │
    ▼
刷新 Token（失效则自动登录）
    │
    ▼
获取活动列表，筛选未过期活动
    │
    ▼
新活动 → 注册 APScheduler 定时任务
    │
    ▼
到达报名时间 → 自动执行报名
    │
    ▼
报名结果 → 记录日志 + 发送邮件通知
```

---

## 核心代码讲解

### 1. 云跑步核心 (`core.py`)

负责与云运动平台 API 交互，完成登录、获取任务、提交跑步轨迹等操作。

**登录流程：**
```python
do_login(username, password, school_name, device_name)
# 1. 根据学校名获取学校对应的 API 地址
# 2. 使用 RSA 公钥加密密码
# 3. 发送登录请求获取 token
# 4. 返回 user_data（含 token、device_id 等）
```

**跑步执行流程：**
```python
do_run_task(user, task_data, log_cb, point_cb)
# 1. 读取轨迹点文件（GPS 坐标序列）
# 2. 逐个模拟提交轨迹点（间隔可配置）
# 3. 每个点提交后回调 point_cb 更新前端地图
# 4. 全部完成后回调 log_cb 通知结果
```

**Token 自动刷新：**
```python
ensure_valid_token(user)
# 1. 用轻量接口探测 token 是否有效
# 2. 无效则从数据库读取账号密码自动重新登录
# 3. 更新数据库中的 token
```

---

### 2. PU口袋校园核心 (`pu_core.py`)

负责口袋校园平台的账号管理、活动获取、自动报名等。

**签到二维码生成原理：**
```python
generate_sign_qrcode(user)
# 1. 构造明文: "xyhui://user/{uid}/{timestamp}/{username}"
# 2. DES 加密 (ECB 模式, PKCS7 填充, key 前8字节)
# 3. 生成二维码图片 (qrcode + Pillow)
# 4. 返回 base64 编码的 PNG 图片
# 5. 前端每 30 秒调用一次，timestamp 随之变化
```

**自动报名流程：**
```python
auto_signup_multithread(activity_id, join_start_time)
# 1. 多线程并发，每个账号一个线程
# 2. 精确等待到报名开始时间
# 3. 发送 POST /apis/activity/join 请求
# 4. 带 X-Sign 加密头（AES-CBC）
```

**X-Sign 加密机制 (`utils/pu_sign.py`)：**
```python
generate_x_sign(echo, timestamp, client)
# 1. 构造 payload: {"echo": random, "timestamp": ts, "client": "web"}
# 2. AES-CBC 加密 (固定 PSK 密钥)
# 3. Base64 编码后放入请求头 X-Sign
```

---

### 3. 主程序路由 (`app.py`)

**Token 自动刷新（`_pu_refresh_token`）：**
```python
def _pu_refresh_token(u):
    # Step 1: 从数据库读最新 token
    # Step 2: 用 activity/list 接口测试 token 是否有效
    # Step 3: 无效则用账号密码重新登录，保存新 token 到数据库
    # 保证每次 API 调用前 token 都是有效的
```

**自动托管调度器（`_start_pu_scheduler_loop`）：**
```python
def _start_pu_scheduler_loop(poll_interval):
    # 后台线程，每 poll_interval 秒轮询一次：
    # 1. 读取所有 auto_scheduler=1 的用户
    # 2. 刷新每个用户的 token
    # 3. 获取活动列表，筛选未过期活动
    # 4. 新活动注册 APScheduler DateTrigger 定时任务
    # 5. 到达报名时间自动执行 _pu_do_signup
```

**数据库连接管理：**
```python
DB_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'yunrun-mysql'),
    'port': int(os.environ.get('MYSQL_PORT', '3306')),
    'user': os.environ.get('MYSQL_USER', 'root'),
    'password': os.environ.get('MYSQL_PASSWORD', 'yunrun2026'),
    'database': os.environ.get('MYSQL_DATABASE', 'yunrun'),
}
# 所有数据库操作通过 get_db_conn() 获取连接
# 环境变量优先，无硬编码敏感信息
```

---

### 4. 前端地图加载 (`index.html` + `app.js`)

**动态加载高德地图：**
```javascript
// index.html: 先从 API 获取 key，再动态加载地图脚本
const res = await fetch('/api/config/map_key');
const { key, security_code } = res.data;
// 设置安全密钥
window._AMapSecurityConfig = { securityJsCode: security_code };
// 动态加载高德 JS
const s = document.createElement('script');
s.src = 'https://webapi.amap.com/maps?v=2.0&key=' + key;
// 加载完成后再加载 app.js
```

**轨迹点解析：**
```javascript
// app.js: GPS 坐标解析，兼容经纬度顺序
function parsePoint(pointStr) {
  const [a, b] = pointStr.split(',').map(Number);
  // 高德地图用 [lng, lat]，中国经度 73-135
  if (a > 73 && a < 135) return [a, b];  // lng,lat
  return [b, a];  // lat,lng → 交换
}
```

---

### 5. 数据库表结构 (`init_db.sql`)

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `users` | 云跑步用户 | username, token, device_id |
| `pu_users` | PU口袋用户 | user_name, token, uid, sid, yunrun_username |
| `pu_signup_logs` | 报名日志 | user_name, activity_id, status |
| `pu_scheduled_keys` | 定时任务注册 | key (防重复) |
| `admins` | 管理员 | username, password |
| `devices` | 设备列表 | name |
| `sys_config` | 系统配置 | key, value (邮件/地图等) |
| `school_folders` | 学校文件夹 | school_name, folder_type |

---

### 6. Docker 部署架构

```
宿主机                          Docker 网络 (web_default)
┌─────────────┐
│ :80         │──── yunrun-web ────┐
│ :3307       │     (Flask)        │
└─────────────┘                    ├── yunrun-mysql (:3306)
                                   │   (MySQL 8.0)
挂载卷:                            │
├── /opt/yunrun/web → /app         │
├── yunrun-data → /app/data        │
├── yunrun-tasks → /app/tasks      │
└── yunrun-mysql-data → /var/lib/mysql
```

- 源码通过 bind mount 挂载，改代码后 `docker restart yunrun-web` 即生效
- MySQL 数据通过 named volume 持久化，重启不丢失
- 两个容器通过 Docker 内部网络通信（`yunrun-mysql:3306`）

---

## 安全说明

- 所有数据库连接通过环境变量配置，代码中无硬编码敏感信息
- PU口袋校园密码使用 DES 加密传输
- 管理后台支持多管理员、权限分级
- 签到二维码每 30 秒自动刷新

---

## 许可证

仅供学习和研究使用，请遵守相关法律法规和学校规定。
