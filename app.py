# coding:utf-8
import os
import json
import threading
import uuid
import queue
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime
from flask import Flask, request, jsonify, session, render_template, redirect, url_for, Response, stream_with_context
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# ========== 数据库配置（优先环境变量，兼容旧配置） ==========
DB_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'yunrun-mysql'),
    'port': int(os.environ.get('MYSQL_PORT', '3306')),
    'user': os.environ.get('MYSQL_USER', 'root'),
    'password': os.environ.get('MYSQL_PASSWORD', 'yunrun2026'),
    'database': os.environ.get('MYSQL_DATABASE', 'yunrun'),
    'charset': 'utf8mb4',
    'connect_timeout': 5,
}

def get_db_conn():
    """获取数据库连接"""
    import pymysql
    return pymysql.connect(**DB_CONFIG)
from apscheduler.triggers.date import DateTrigger
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import (
    do_login, get_school_list, get_term_list, get_run_records,
    get_run_detail, do_run_task, get_member_info, compare_datetime_strings,
    device_list, init_global_vars, register_user, get_device_list
)

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()
CORS(app, supports_credentials=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TASKS_DIR = os.path.join(BASE_DIR, 'tasks')
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(TASKS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
CRON_JOBS_FILE = os.path.join(DATA_DIR, 'cron_jobs.json')
RUN_LOGS_FILE = os.path.join(DATA_DIR, 'run_logs.json')
EMAIL_CONFIG_FILE = os.path.join(DATA_DIR, 'email_config.json')

def get_sys_config(key, default):
    """从数据库读取系统配置"""
    try:
        import pymysql
        conn = pymysql.connect(
            get_db_conn()
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT `value` FROM sys_config WHERE `key`=%s', (key,))
                row = cur.fetchone()
                return row[0] if row else default
    except Exception:
        return default


def save_sys_config(key, value):
    """保存系统配置到数据库"""
    conn = get_db_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO sys_config (`key`,`value`) VALUES (%s,%s) ON DUPLICATE KEY UPDATE `value`=%s',
                        (key, value, value))
        conn.commit()


def build_scheduler():
    """根据数据库配置构建 scheduler"""
    max_workers = int(get_sys_config('scheduler_max_workers', '20'))
    max_instances = int(get_sys_config('scheduler_max_instances', '1'))
    return BackgroundScheduler(
        timezone='Asia/Shanghai',
        job_defaults={'coalesce': False, 'max_instances': max_instances},
        executors={'default': {'type': 'threadpool', 'max_workers': max_workers}}
    )


scheduler = build_scheduler()

# 实时跑步进度存储
_run_sessions = {}
_run_sessions_lock = threading.Lock()

# 学校 -> 任务文件夹映射（相对于项目根目录，男/女分开）
# 学校任务文件夹配置从数据库动态加载
# key: 学校名称, value: {'man': 路径, 'woman': 路径, 'default': 路径}
SCHOOL_TASK_DIRS = {}  # 运行时由 load_school_task_dirs() 填充
SCHOOL_TASKS_BASE = os.path.join(BASE_DIR, 'school_tasks')
os.makedirs(SCHOOL_TASKS_BASE, exist_ok=True)


def load_school_task_dirs():
    """从数据库加载学校文件夹配置，更新 SCHOOL_TASK_DIRS"""
    global SCHOOL_TASK_DIRS
    try:
        import pymysql
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT school_name, folder_type, folder_name FROM school_folders')
                rows = cur.fetchall()
        result = {}
        for school_name, folder_type, folder_name in rows:
            if school_name not in result:
                result[school_name] = {}
            result[school_name][folder_type] = os.path.join(SCHOOL_TASKS_BASE, folder_name)
        SCHOOL_TASK_DIRS = result
    except Exception as e:
        print(f'加载学校文件夹配置失败: {e}')


load_school_task_dirs()


# ---- 学校随机任务文件 ----
def get_school_task_file(school_name, sex):
    """根据学校名和性别随机选一个任务文件，返回文件路径或 None"""
    import random
    dirs_cfg = None
    for key, cfg in SCHOOL_TASK_DIRS.items():
        if key in school_name:
            dirs_cfg = cfg
            break
    if not dirs_cfg:
        return None, f'学校「{school_name}」暂无内置任务文件'

    # sex=1 男，sex=2 女，其他用 default
    if sex == 1:
        folder = dirs_cfg.get('man') or dirs_cfg.get('default')
    elif sex == 2:
        folder = dirs_cfg.get('woman') or dirs_cfg.get('default')
    else:
        folder = dirs_cfg.get('default')

    if not folder or not os.path.isdir(folder):
        # 回退到 default
        folder = dirs_cfg.get('default')
    if not folder or not os.path.isdir(folder):
        return None, f'任务文件夹不存在: {folder}'

    files = [f for f in os.listdir(folder) if f.endswith('.json')]
    if not files:
        return None, f'文件夹 {folder} 中没有 JSON 文件'

    chosen = random.choice(files)
    return os.path.join(folder, chosen), chosen


# ---- 会员验证 ----
def check_membership(user):
    """从服务器实时获取会员有效期，返回 (ok: bool, msg: str)"""
    try:
        info = get_member_info(user['username'], user.get('password', ''))
        user_time = info.get('date', '')
        now_time = info.get('now_time', '')
        if not user_time:
            return False, '无法获取会员信息，请检查网络'
        # 更新 session 里的时间
        sessions = load_json(SESSIONS_FILE, {})
        if user['username'] in sessions:
            sessions[user['username']]['user_time'] = user_time
            sessions[user['username']]['now_time'] = now_time
            save_json(SESSIONS_FILE, sessions)
        if now_time and now_time >= user_time:
            return False, f'会员已过期（有效期至 {user_time}），请续费后再跑步'
        return True, f'会员有效（有效期至 {user_time}）'
    except Exception as e:
        return False, f'会员验证失败: {str(e)}'


# ---- 邮件通知 ----
def get_email_config(username):
    """获取用户邮件配置"""
    configs = load_json(EMAIL_CONFIG_FILE, {})
    return configs.get(username, {})


def get_sys_email_config():
    """获取系统级 SMTP 配置（从数据库 sys_config 表读取）"""
    defaults = {
        'smtp_server': 'smtp.qq.com',
        'smtp_port': '465',
        'smtp_user': '',
        'smtp_pass': '',
        'sender_name': '云运动助手',
    }
    try:
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT `key`, `value` FROM sys_config WHERE `key` LIKE 'email_%'")
                for row in cur.fetchall():
                    key = row[0].replace('email_', '', 1)
                    if key in defaults:
                        defaults[key] = row[1]
    except Exception:
        pass
    return defaults


def save_sys_email_config(cfg):
    """保存系统级 SMTP 配置到数据库"""
    try:
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                for key in ('smtp_server', 'smtp_port', 'smtp_user', 'smtp_pass', 'sender_name'):
                    val = cfg.get(key, '')
                    cur.execute(
                        "INSERT INTO sys_config (`key`, `value`, `desc`) VALUES (%s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE `value`=%s",
                        (f'email_{key}', val, f'邮件{key}', val)
                    )
            conn.commit()
        return True
    except Exception:
        return False


def send_email(cfg, subject, html_content):
    """发送邮件，cfg 需要包含 receiver 和 enable"""
    if not cfg.get('enable') or not cfg.get('receiver'):
        return False, '邮件通知未启用或未填写收件人'
    mail_cfg = get_sys_email_config()
    smtp_server = mail_cfg.get('smtp_server') or 'smtp.qq.com'
    smtp_port = int(mail_cfg.get('smtp_port') or 465)
    sender = mail_cfg.get('smtp_user', '')
    auth_code = mail_cfg.get('smtp_pass', '')
    sender_name = mail_cfg.get('sender_name', '云运动助手')
    if not sender or not auth_code:
        return False, '邮件未配置，请在管理后台 -> 系统设置 -> 邮件配置中设置'
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = formataddr((sender_name, sender))
        msg['To'] = cfg['receiver']
        msg['Subject'] = Header(subject, 'utf-8')
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
        server.login(sender, auth_code)
        server.send_message(msg)
        server.quit()
        return True, '发送成功'
    except Exception as e:
        return False, str(e)


def notify_run_result(username, success, run_data):
    """跑步结束后发送邮件通知"""
    cfg = get_email_config(username)
    if not cfg.get('enable'):
        return
    real_name = run_data.get('real_name', username)
    task_name = run_data.get('task_name', '未知')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if success:
        subject = f"跑步完成 - {run_data.get('distance', '?')} km"
        body = f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;border-radius:10px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.1)">
          <div style="background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:24px;text-align:center">
            <div style="font-size:3rem">✅</div>
            <h2 style="margin:8px 0">跑步任务完成</h2>
            <p style="margin:0;opacity:.85">{now}</p>
          </div>
          <div style="padding:24px;background:#fff">
            <p>你好 <b>{real_name}</b>，您的跑步任务已成功完成！</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0">
              <div style="background:#f0fdf4;padding:14px;border-radius:8px;text-align:center">
                <div style="color:#888;font-size:.8rem">距离</div>
                <div style="font-size:1.6rem;font-weight:700;color:#10b981">{run_data.get('distance','?')} km</div>
              </div>
              <div style="background:#eff6ff;padding:14px;border-radius:8px;text-align:center">
                <div style="color:#888;font-size:.8rem">用时</div>
                <div style="font-size:1.6rem;font-weight:700;color:#3b82f6">{run_data.get('duration_min','?')} 分钟</div>
              </div>
            </div>
            <p style="color:#888;font-size:.85rem">任务文件：{task_name}</p>
          </div>
          <div style="background:#f8fafc;padding:12px;text-align:center;color:#aaa;font-size:.75rem">此邮件由云运动助手自动发送</div>
        </div>"""
    else:
        subject = "⚠️ 跑步任务失败"
        body = f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;border-radius:10px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.1)">
          <div style="background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;padding:24px;text-align:center">
            <div style="font-size:3rem">❌</div>
            <h2 style="margin:8px 0">跑步任务失败</h2>
            <p style="margin:0;opacity:.85">{now}</p>
          </div>
          <div style="padding:24px;background:#fff">
            <p>你好 <b>{real_name}</b>，您的跑步任务执行失败。</p>
            <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:14px;border-radius:4px;margin:16px 0">
              <b>错误信息：</b>{run_data.get('error','未知错误')}
            </div>
            <p style="color:#888;font-size:.85rem">任务文件：{task_name}</p>
          </div>
          <div style="background:#f8fafc;padding:12px;text-align:center;color:#aaa;font-size:.75rem">此邮件由云运动助手自动发送</div>
        </div>"""
    threading.Thread(target=send_email, args=(cfg, subject, body), daemon=True).start()


# ---- 持久化存储工具 ----
_file_lock = threading.Lock()


def load_json(path, default):
    with _file_lock:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return default


def save_json(path, data):
    with _file_lock:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def add_run_log(job_id, username, msg, success=None):
    logs = load_json(RUN_LOGS_FILE, [])
    logs.append({
        'id': str(uuid.uuid4())[:8],
        'job_id': job_id,
        'username': username,
        'msg': msg,
        'success': success,
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    logs = logs[-500:]  # 最多保留500条
    save_json(RUN_LOGS_FILE, logs)


# ---- 定时任务执行函数 ----
def execute_cron_job(job_id):
    jobs = load_json(CRON_JOBS_FILE, {})
    job = jobs.get(job_id)
    if not job:
        return
    username = job['username']
    sessions = load_json(SESSIONS_FILE, {})
    sess = sessions.get(username)

    # 如果没有 session 或 token 失效，从数据库取凭据自动登录
    def _try_relogin(reason=''):
        try:
            import pymysql as _pym
            _c = get_db_conn()
            with _c:
                with _c.cursor() as cur:
                    cur.execute('SELECT `key`, school_name, device_name FROM users WHERE username=%s LIMIT 1', (username,))
                    row = cur.fetchone()
            if not row or not row[0]:
                add_run_log(job_id, username, f'❌ 数据库中无该用户凭据，无法自动登录', False)
                return None
            pwd, school_name, dev_name = row
            dev_name = dev_name or 'Xiaomi 14'
            add_run_log(job_id, username, f'🔄 {reason}，正在自动登录...')
            new_user, err = do_login(username, pwd, school_name, dev_name)
            if err or not new_user:
                add_run_log(job_id, username, f'❌ 自动登录失败: {err}', False)
                return None
            # 更新 session 和数据库 token
            sessions2 = load_json(SESSIONS_FILE, {})
            sessions2[username] = new_user
            save_json(SESSIONS_FILE, sessions2)
            try:
                _c2 = get_db_conn()
                with _c2:
                    with _c2.cursor() as cur:
                        cur.execute('UPDATE users SET token=%s, device_id=%s, device_name=%s, school_url=%s WHERE username=%s',
                                    (new_user['token'], new_user['device_id'],
                                     new_user['device_name'], new_user['school_url'], username))
                    _c2.commit()
            except Exception:
                pass
            add_run_log(job_id, username, '✅ 自动登录成功，token 已更新')
            return new_user
        except Exception as e:
            add_run_log(job_id, username, f'❌ 自动登录异常: {e}', False)
            return None

    if not sess:
        sess = _try_relogin('用户未登录')
        if not sess:
            return
    else:
        # 验证 token 是否有效
        try:
            from core import default_post as _dp
            resp = _dp("/login/getStudentInfo", "", sess['token'],
                       sess.get('device_id', ''), sess.get('device_name', ''), sess.get('school_url', ''))
            import json as _j
            if _j.loads(resp).get('code') != 200:
                sess = _try_relogin('token 已失效')
                if not sess:
                    return
        except Exception:
            sess = _try_relogin('token 验证异常')
            if not sess:
                return

    # 实时验证会员有效期
    ok, msg = check_membership(sess)
    if not ok:
        add_run_log(job_id, job['username'], f'❌ {msg}', False)
        return

    task_file = job.get('task_file')

    # 如果配置了使用学校随机文件，则忽略固定 task_file
    if job.get('use_school_file'):
        sex = sess.get('student_info', {}).get('data', {}).get('sex', 0)
        school_name = sess.get('school_name', '')
        task_file, fname_or_err = get_school_task_file(school_name, sex)
        if not task_file:
            add_run_log(job_id, job['username'], f'❌ {fname_or_err}', False)
            return
        log_cb_early = lambda m: add_run_log(job_id, job['username'], m)
        log_cb_early(f'📂 随机选取文件：{fname_or_err}')
    
    if not task_file or not os.path.exists(task_file):
        add_run_log(job_id, job['username'], '❌ 任务文件不存在', False)
        return

    # 读取轨迹点，注册到 _run_sessions 供前端实时查看
    try:
        with open(task_file, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        all_points = task_data.get('data', {}).get('pointsList', [])
        total_points = len(all_points)
    except Exception:
        all_points = []
        total_points = 0

    run_id = str(uuid.uuid4())[:8]
    stop_event = threading.Event()
    with _run_sessions_lock:
        _run_sessions[run_id] = {
            'username': job['username'],
            'points': [],
            'all_points': [p['point'] for p in all_points],
            'logs': [],
            'done': False,
            'success': None,
            'total': total_points,
            'current': 0,
            'queues': [],
            'stop_event': stop_event,
            'cron_job_id': job_id,
            'cron_job_name': job.get('name', ''),
        }

    def push_event(eid, event_type, data_dict):
        with _run_sessions_lock:
            s = _run_sessions.get(eid)
            if not s:
                return
            raw = f"event: {event_type}\ndata: {json.dumps(data_dict, ensure_ascii=False)}\n\n"
            for q in s['queues']:
                try:
                    q.put_nowait(raw)
                except Exception:
                    pass

    def log_cb(log_msg):
        add_run_log(run_id, job['username'], log_msg)
        with _run_sessions_lock:
            s = _run_sessions.get(run_id)
            if s:
                s['logs'].append({'time': datetime.now().strftime('%H:%M:%S'), 'msg': log_msg})
        push_event(run_id, 'log', {'msg': log_msg, 'time': datetime.now().strftime('%H:%M:%S')})

    def point_cb(point_str, current, total):
        with _run_sessions_lock:
            s = _run_sessions.get(run_id)
            if s:
                s['points'].append(point_str)
                s['current'] = current
        push_event(run_id, 'point', {'point': point_str, 'current': current, 'total': total})

    add_run_log(run_id, job['username'], f'🚀 定时任务「{job.get("name","")}」开始执行')
    log_cb(f'🚀 定时任务「{job.get("name","")}」开始执行')

    try:
        result = do_run_task(task_file, sess, log_callback=log_cb,
                             point_callback=point_cb, stop_event=stop_event)
        with _run_sessions_lock:
            s = _run_sessions.get(run_id)
            if s:
                s['done'] = True
                s['success'] = result
        push_event(run_id, 'done', {'success': result})

        jobs = load_json(CRON_JOBS_FILE, {})
        if job_id in jobs:
            jobs[job_id]['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            jobs[job_id]['last_status'] = 'success' if result else 'failed'
            jobs[job_id]['last_run_id'] = run_id
            save_json(CRON_JOBS_FILE, jobs)
        add_run_log(run_id, job['username'], '✅ 任务执行完成' if result else '❌ 任务执行失败', result)

        # 邮件通知
        try:
            run_data = {
                'real_name': sess.get('student_info', {}).get('data', {}).get('realName', job['username']),
                'task_name': job.get('task_filename', task_file),
                'distance': task_data.get('data', {}).get('recordMileage', '?'),
                'duration_min': round(task_data.get('data', {}).get('duration', 0) / 60, 1),
                'error': '任务执行失败'
            }
        except Exception:
            run_data = {'real_name': job['username'], 'task_name': job.get('task_filename', ''), 'error': '执行失败'}
        notify_run_result(job['username'], result, run_data)

    except Exception as e:
        log_cb(f'❌ 执行异常: {str(e)}')
        with _run_sessions_lock:
            s = _run_sessions.get(run_id)
            if s:
                s['done'] = True
                s['success'] = False
        push_event(run_id, 'done', {'success': False})
        add_run_log(run_id, job['username'], f'❌ 执行异常: {str(e)}', False)


def reload_all_cron_jobs():
    jobs = load_json(CRON_JOBS_FILE, {})
    for job_id, job in jobs.items():
        if job.get('enabled') and job.get('cron'):
            try:
                cron = job['cron'].split()
                if len(cron) == 5:
                    trigger = CronTrigger(
                        minute=cron[0], hour=cron[1],
                        day=cron[2], month=cron[3], day_of_week=cron[4]
                    )
                    if scheduler.get_job(job_id):
                        scheduler.remove_job(job_id)
                    scheduler.add_job(execute_cron_job, trigger, id=job_id, args=[job_id])
            except Exception as e:
                print(f"加载定时任务失败 {job_id}: {e}")


# ---- 认证中间件 ----
def get_current_user():
    username = session.get('username')
    if not username:
        return None
    sessions = load_json(SESSIONS_FILE, {})
    return sessions.get(username)


def ensure_valid_token(user):
    """检测 token 是否有效，失效则用存储的用户名密码自动重新登录，更新 session。
    返回最新的 user dict，失败返回原 user。"""
    if not user:
        return user
    # 用一个轻量接口探测 token 是否有效
    try:
        from core import default_post as _dp
        resp = _dp("/login/getStudentInfo", "",
                   user['token'], user['device_id'],
                   user['device_name'], user['school_url'])
        data = json.loads(resp)
        if data.get('code') == 200:
            return user  # token 有效，直接返回
    except Exception:
        pass

    # token 失效，尝试自动重新登录
    username = user.get('username')
    password = user.get('password')
    school_name = user.get('school_name')
    device_name = user.get('device_name', 'Xiaomi 14')
    if not username or not password or not school_name:
        return user  # 缺少凭据，无法重登

    try:
        new_user, err = do_login(username, password, school_name, device_name)
        if err or not new_user:
            return user  # 重登失败，返回旧数据
        # 更新 session 文件
        sessions = load_json(SESSIONS_FILE, {})
        sessions[username] = new_user
        save_json(SESSIONS_FILE, sessions)
        # 同步更新数据库中的 token
        try:
            import pymysql as _pym
            _c = get_db_conn()
            with _c:
                with _c.cursor() as cur:
                    cur.execute('UPDATE users SET token=%s, device_id=%s, device_name=%s, school_url=%s WHERE username=%s',
                                (new_user['token'], new_user['device_id'],
                                 new_user['device_name'], new_user['school_url'], username))
                _c.commit()
        except Exception:
            pass
        return new_user
    except Exception:
        return user


# ---- 页面路由 ----
@app.route('/')
def index():
    if not session.get('username'):
        return redirect(url_for('login_page'))
    return render_template('index.html')


@app.route('/login')
def login_page():
    if session.get('username'):
        return redirect(url_for('index'))
    return render_template('login.html')


# ---- API: 认证 ----
@app.route('/api/schools', methods=['GET'])
def api_schools():
    try:
        schools = get_school_list()
        return jsonify({'code': 200, 'data': schools})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    school_name = data.get('school_name', '').strip()
    device_name = data.get('device_name', 'Xiaomi 14')
    if not all([username, password, school_name]):
        return jsonify({'code': 400, 'msg': '请填写完整信息'})
    try:
        import pymysql as _pym

        # 先验证数据库中的用户名和密码
        db_user_exists = False
        try:
            _vc = get_db_conn()
            with _vc:
                with _vc.cursor() as cur:
                    cur.execute('SELECT `key` FROM users WHERE username=%s LIMIT 1', (username,))
                    row = cur.fetchone()
            if row is not None:
                db_user_exists = True
                if row[0] != password:
                    return jsonify({'code': 401, 'msg': '密码错误'})
            # 用户不存在时继续，登录成功后自动注册
        except Exception:
            pass  # 数据库连接失败时降级处理

        user_data = None
        err = None

        # 优先从数据库读取已保存的 token，尝试复用
        try:
            _conn = get_db_conn()
            with _conn:
                with _conn.cursor() as cur:
                    cur.execute('SELECT token, device_id, device_name, school_url FROM users WHERE username=%s LIMIT 1', (username,))
                    row = cur.fetchone()
        except Exception:
            row = None

        if row and row[0]:  # 有保存的 token
            saved_token, saved_device_id, saved_device_name, saved_school_url = row
            # 验证 token 是否有效
            try:
                from core import default_post as _dp, get_student_info, get_member_info
                resp = _dp("/login/getStudentInfo", "", saved_token,
                           saved_device_id or "1234567890123456",
                           saved_device_name or device_name,
                           saved_school_url or "")
                import json as _j
                resp_data = _j.loads(resp)
                if resp_data.get('code') == 200:
                    # token 有效，直接构建 user_data
                    member_info = get_member_info(username, password)
                    user_data = {
                        'token': saved_token,
                        'device_id': saved_device_id,
                        'device_name': saved_device_name or device_name,
                        'school_url': saved_school_url,
                        'school_name': school_name,
                        'username': username,
                        'password': password,
                        'student_info': resp_data,
                        'user_time': member_info.get('date'),
                        'now_time': member_info.get('now_time')
                    }
            except Exception:
                user_data = None

        # token 无效或不存在，重新登录
        if not user_data:
            user_data, err = do_login(username, password, school_name, device_name)
            if err:
                return jsonify({'code': 401, 'msg': err})
            # 将新 token 写入数据库
            try:
                _conn2 = get_db_conn()
                with _conn2:
                    with _conn2.cursor() as cur:
                        cur.execute('SELECT 1 FROM users WHERE username=%s LIMIT 1', (username,))
                        if cur.fetchone():
                            cur.execute(
                                'UPDATE users SET token=%s, device_id=%s, device_name=%s, school_url=%s WHERE username=%s',
                                (user_data['token'], user_data['device_id'],
                                 user_data['device_name'], user_data['school_url'], username)
                            )
                        else:
                            cur.execute(
                                'INSERT INTO users (username, `key`, `date`, school_name, token, device_id, device_name, school_url) VALUES (%s,%s,NOW(),%s,%s,%s,%s,%s)',
                                (username, password, school_name, user_data['token'],
                                 user_data['device_id'], user_data['device_name'], user_data['school_url'])
                            )
                    _conn2.commit()
            except Exception:
                pass

        sessions = load_json(SESSIONS_FILE, {})
        sessions[username] = user_data
        save_json(SESSIONS_FILE, sessions)
        session['username'] = username
        session.permanent = True
        student = user_data.get('student_info', {}).get('data', {})
        return jsonify({'code': 200, 'msg': '登录成功', 'data': {
            'username': username,
            'real_name': student.get('realName', username),
            'school_name': school_name,
            'user_time': user_data.get('user_time'),
            'now_time': user_data.get('now_time'),
            'student_info': student
        }})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    username = session.get('username')
    if username:
        sessions = load_json(SESSIONS_FILE, {})
        sessions.pop(username, None)
        save_json(SESSIONS_FILE, sessions)
    session.clear()
    return jsonify({'code': 200, 'msg': '已退出'})


@app.route('/api/user/info', methods=['GET'])
def api_user_info():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    student = user.get('student_info', {}).get('data', {})
    return jsonify({'code': 200, 'data': {
        'username': user['username'],
        'real_name': student.get('realName', user['username']),
        'school_name': user['school_name'],
        'user_time': user.get('user_time'),
        'now_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'device_name': user.get('device_name'),
        'student_info': student
    }})


# ---- API: 跑步 ----
@app.route('/api/run/start', methods=['POST'])
def api_run_start():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.json
    task_filename = data.get('task_file', '')
    if not task_filename or '/' in task_filename or '\\' in task_filename or '..' in task_filename:
        return jsonify({'code': 400, 'msg': '非法文件名'})

    # 实时验证会员有效期
    ok, msg = check_membership(user)
    if not ok:
        return jsonify({'code': 403, 'msg': msg})

    task_file = os.path.join(TASKS_DIR, user['username'], task_filename)
    if not os.path.exists(task_file):
        return jsonify({'code': 400, 'msg': '任务文件不存在'})

    run_id = str(uuid.uuid4())[:8]

    # 读取任务文件，提前返回轨迹点供地图预览
    try:
        with open(task_file, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        all_points = task_data.get('data', {}).get('pointsList', [])
        total_points = len(all_points)
    except:
        all_points = []
        total_points = 0

    stop_event = threading.Event()
    with _run_sessions_lock:
        _run_sessions[run_id] = {
            'username': user['username'],
            'points': [],
            'all_points': [p['point'] for p in all_points],
            'logs': [],
            'done': False,
            'success': None,
            'total': total_points,
            'current': 0,
            'queues': [],
            'stop_event': stop_event
        }

    def push_event(run_id, event_type, data_dict):
        with _run_sessions_lock:
            sess = _run_sessions.get(run_id)
            if not sess:
                return
            msg = f"event: {event_type}\ndata: {json.dumps(data_dict, ensure_ascii=False)}\n\n"
            for q in sess['queues']:
                try:
                    q.put_nowait(msg)
                except:
                    pass

    def log_cb(msg):
        add_run_log(run_id, user['username'], msg)
        with _run_sessions_lock:
            sess = _run_sessions.get(run_id)
            if sess:
                sess['logs'].append({'time': datetime.now().strftime('%H:%M:%S'), 'msg': msg})
        push_event(run_id, 'log', {'msg': msg, 'time': datetime.now().strftime('%H:%M:%S')})

    def point_cb(point_str, current, total):
        """每上传一个轨迹点时回调"""
        with _run_sessions_lock:
            sess = _run_sessions.get(run_id)
            if sess:
                sess['points'].append(point_str)
                sess['current'] = current
        push_event(run_id, 'point', {'point': point_str, 'current': current, 'total': total})

    def run_bg():
        try:
            ok = do_run_task(task_file, user, log_callback=log_cb, point_callback=point_cb, stop_event=stop_event)
            with _run_sessions_lock:
                sess = _run_sessions.get(run_id)
                if sess:
                    sess['done'] = True
                    sess['success'] = ok
            push_event(run_id, 'done', {'success': ok})
            # 发送邮件通知
            try:
                with open(task_file, 'r', encoding='utf-8') as f:
                    td = json.load(f)
                run_data = {
                    'real_name': user.get('student_info', {}).get('data', {}).get('realName', user['username']),
                    'task_name': task_filename,
                    'distance': td.get('data', {}).get('recordMileage', '?'),
                    'duration_min': round(td.get('data', {}).get('duration', 0) / 60, 1),
                    'error': '任务被停止或执行失败'
                }
            except Exception:
                run_data = {'real_name': user['username'], 'task_name': task_filename, 'error': '执行失败'}
            notify_run_result(user['username'], ok, run_data)
        except Exception as e:
            log_cb(f'❌ 异常: {str(e)}')
            with _run_sessions_lock:
                sess = _run_sessions.get(run_id)
                if sess:
                    sess['done'] = True
                    sess['success'] = False
            push_event(run_id, 'done', {'success': False})
            notify_run_result(user['username'], False, {
                'real_name': user.get('student_info', {}).get('data', {}).get('realName', user['username']),
                'task_name': task_filename, 'error': str(e)
            })

    t = threading.Thread(target=run_bg, daemon=True)
    t.start()
    return jsonify({
        'code': 200, 'msg': '跑步任务已在后台启动', 'run_id': run_id,
        'total': total_points,
        'all_points': [p['point'] for p in all_points]
    })


@app.route('/api/run/events/<run_id>')
def api_run_events(run_id):
    """SSE 实时推送跑步进度"""
    username = session.get('username')
    if not username:
        return jsonify({'code': 401}), 401

    def generate():
        q = queue.Queue()
        with _run_sessions_lock:
            sess = _run_sessions.get(run_id)
            if not sess:
                yield "event: error\ndata: {\"msg\": \"run_id不存在\"}\n\n"
                return
            # 先推送已有的历史数据
            for log in sess['logs']:
                yield f"event: log\ndata: {json.dumps(log, ensure_ascii=False)}\n\n"
            for pt in sess['points']:
                yield f"event: point\ndata: {json.dumps({'point': pt}, ensure_ascii=False)}\n\n"
            if sess['done']:
                yield f"event: done\ndata: {json.dumps({'success': sess['success']})}\n\n"
                return
            sess['queues'].append(q)

        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                    if '"done"' in msg:
                        break
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            with _run_sessions_lock:
                sess = _run_sessions.get(run_id)
                if sess and q in sess['queues']:
                    sess['queues'].remove(q)

    return Response(stream_with_context(generate()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/run/stop', methods=['POST'])
def api_run_stop():
    """停止当前跑步任务"""
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    run_id = request.json.get('run_id', '')
    with _run_sessions_lock:
        sess = _run_sessions.get(run_id)
        if not sess or sess.get('username') != user['username']:
            return jsonify({'code': 404, 'msg': '任务不存在'})
        if sess.get('done'):
            return jsonify({'code': 400, 'msg': '任务已结束'})
        stop_ev = sess.get('stop_event')
        if stop_ev:
            stop_ev.set()
    return jsonify({'code': 200, 'msg': '已发送停止信号'})


@app.route('/api/run/upload_task', methods=['POST'])
def api_upload_task():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    if 'file' not in request.files:
        return jsonify({'code': 400, 'msg': '未上传文件'})
    f = request.files['file']
    if not f.filename.endswith('.json'):
        return jsonify({'code': 400, 'msg': '只支持JSON文件'})
    try:
        content = json.loads(f.read().decode('utf-8'))
        username = user['username']
        user_task_dir = os.path.join(TASKS_DIR, username)
        os.makedirs(user_task_dir, exist_ok=True)
        files = [x for x in os.listdir(user_task_dir) if x.startswith('tasklist_')]
        last = 0
        for fn in files:
            try:
                n = int(fn.replace('tasklist_', '').replace('.json', ''))
                last = max(last, n + 1)
            except:
                pass
        save_path = os.path.join(user_task_dir, f'tasklist_{last}.json')
        with open(save_path, 'w', encoding='utf-8') as out:
            json.dump(content, out, ensure_ascii=False)
        return jsonify({'code': 200, 'msg': '上传成功',
                        'info': {
                            'mileage': content.get('data', {}).get('recordMileage'),
                            'duration': content.get('data', {}).get('duration'),
                            'points': len(content.get('data', {}).get('pointsList', []))
                        }})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/run/task_files', methods=['GET'])
def api_task_files():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    user_task_dir = os.path.join(TASKS_DIR, user['username'])
    os.makedirs(user_task_dir, exist_ok=True)
    result = []
    for fn in sorted(os.listdir(user_task_dir)):
        if fn.endswith('.json'):
            fp = os.path.join(user_task_dir, fn)
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                result.append({
                    'name': fn,
                    'mileage': d.get('data', {}).get('recordMileage', '?'),
                    'duration': d.get('data', {}).get('duration', 0),
                    'points': len(d.get('data', {}).get('pointsList', []))
                })
            except:
                result.append({'name': fn})
    return jsonify({'code': 200, 'data': result})


@app.route('/api/run/delete_task', methods=['POST'])
def api_delete_task():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    filename = request.json.get('filename', '')
    if not filename or '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'code': 400, 'msg': '非法文件名'})
    fp = os.path.join(TASKS_DIR, user['username'], filename)
    if os.path.exists(fp):
        os.remove(fp)
    return jsonify({'code': 200, 'msg': '已删除'})


@app.route('/api/run/download_task', methods=['GET'])
def api_download_task():
    from flask import send_file
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'}), 401
    filename = request.args.get('filename', '')
    if not filename or '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'code': 400, 'msg': '非法文件名'}), 400
    fp = os.path.join(TASKS_DIR, user['username'], filename)
    if not os.path.exists(fp):
        return jsonify({'code': 404, 'msg': '文件不存在'}), 404
    return send_file(fp, as_attachment=True, download_name=filename)


# ---- API: 历史记录 ----
@app.route('/api/history/terms', methods=['GET'])
def api_terms():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    user = ensure_valid_token(user)
    try:
        terms = get_term_list(user['token'], user['device_id'],
                              user['device_name'], user['school_url'])
        return jsonify({'code': 200, 'data': terms})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/history/runs', methods=['GET'])
def api_runs():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    user = ensure_valid_token(user)
    table_name = request.args.get('table_name', '')
    if not table_name:
        return jsonify({'code': 400, 'msg': '缺少table_name'})
    try:
        all_runs, month_groups = get_run_records(
            table_name, user['token'], user['device_id'],
            user['device_name'], user['school_url'])
        return jsonify({'code': 200, 'data': {'runs': all_runs, 'groups': month_groups}})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/history/detail', methods=['GET'])
def api_run_detail():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    user = ensure_valid_token(user)
    run_id = request.args.get('run_id')
    table_name = request.args.get('table_name')
    if not run_id or not table_name:
        return jsonify({'code': 400, 'msg': '缺少参数'})
    try:
        detail, err = get_run_detail(run_id, table_name, user['token'],
                                     user['device_id'], user['device_name'], user['school_url'])
        if err:
            return jsonify({'code': 500, 'msg': err})
        return jsonify({'code': 200, 'data': detail})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/history/save', methods=['POST'])
def api_save_run():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    user = ensure_valid_token(user)
    data = request.json
    run_id = data.get('run_id')
    table_name = data.get('table_name')
    if not run_id or not table_name:
        return jsonify({'code': 400, 'msg': '缺少参数'})
    try:
        detail, err = get_run_detail(run_id, table_name, user['token'],
                                     user['device_id'], user['device_name'], user['school_url'])
        if err:
            return jsonify({'code': 500, 'msg': err})
        user_task_dir = os.path.join(TASKS_DIR, user['username'])
        os.makedirs(user_task_dir, exist_ok=True)
        files = [x for x in os.listdir(user_task_dir) if x.startswith('tasklist_')]
        last = 0
        for fn in files:
            try:
                n = int(fn.replace('tasklist_', '').replace('.json', ''))
                last = max(last, n + 1)
            except:
                pass
        save_path = os.path.join(user_task_dir, f'tasklist_{last}.json')
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump({'code': 200, 'data': detail}, f, ensure_ascii=False)
        return jsonify({'code': 200, 'msg': f'已保存为 tasklist_{last}.json'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ---- API: 定时任务 ----
@app.route('/api/cron/list', methods=['GET'])
def api_cron_list():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    jobs = load_json(CRON_JOBS_FILE, {})
    user_jobs = {k: v for k, v in jobs.items() if v.get('username') == user['username']}
    return jsonify({'code': 200, 'data': list(user_jobs.values())})


@app.route('/api/cron/create', methods=['POST'])
def api_cron_create():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.json
    name = data.get('name', '').strip()
    task_filename = data.get('task_file', '').strip()
    cron_expr = data.get('cron', '').strip()
    days = data.get('days', [])
    run_time = data.get('time', '').strip()   # "07:30"
    run_date = data.get('run_date', '').strip()  # "2026-03-22" 指定日期一次性执行
    use_school_file = bool(data.get('use_school_file', False))

    if not name:
        return jsonify({'code': 400, 'msg': '请填写任务名称'})

    # 使用学校随机文件时不需要指定 task_file
    if use_school_file:
        task_file = ''
        task_filename = ''
        # 预检：确认该学校有对应文件夹
        sex = user.get('student_info', {}).get('data', {}).get('sex', 0)
        school_name = user.get('school_name', '')
        test_file, err_msg = get_school_task_file(school_name, sex)
        if not test_file:
            return jsonify({'code': 400, 'msg': err_msg})
    else:
        if not task_filename:
            return jsonify({'code': 400, 'msg': '请选择任务文件'})
        if '/' in task_filename or '\\' in task_filename or '..' in task_filename:
            return jsonify({'code': 400, 'msg': '非法文件名'})
        task_file = os.path.join(TASKS_DIR, user['username'], task_filename)
        if not os.path.exists(task_file):
            return jsonify({'code': 400, 'msg': '任务文件不存在'})

    job_id = str(uuid.uuid4())[:8]
    jobs = load_json(CRON_JOBS_FILE, {})
    day_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

    # ---- 一次性日期任务 ----
    if run_date and run_time:
        try:
            run_dt = datetime.strptime(f"{run_date} {run_time}", '%Y-%m-%d %H:%M')
        except ValueError:
            return jsonify({'code': 400, 'msg': '日期/时间格式错误'})
        if run_dt <= datetime.now():
            return jsonify({'code': 400, 'msg': '执行时间必须在当前时间之后'})
        trigger = DateTrigger(run_date=run_dt, timezone='Asia/Shanghai')
        jobs[job_id] = {
            'id': job_id, 'name': name, 'cron': '',
            'days': [], 'time': run_time,
            'days_label': run_date, 'time_label': run_time,
            'task_file': task_file, 'task_filename': task_filename,
            'username': user['username'], 'once': True,
            'use_school_file': use_school_file,
            'enabled': True, 'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'last_run': None, 'last_status': None
        }
        save_json(CRON_JOBS_FILE, jobs)
        scheduler.add_job(execute_cron_job, trigger, id=job_id, args=[job_id])
        return jsonify({'code': 200, 'msg': f'一次性任务已创建，将于 {run_date} {run_time} 执行', 'job_id': job_id})

    # ---- 周期性任务 ----
    if not cron_expr and days and run_time:
        try:
            h, m = run_time.split(':')
            dow = ','.join(str(d) for d in sorted(days))
            cron_expr = f"{int(m)} {int(h)} * * {dow}"
        except Exception:
            return jsonify({'code': 400, 'msg': '时间格式错误，请用 HH:MM'})

    if not cron_expr:
        return jsonify({'code': 400, 'msg': '请设置执行时间'})

    cron_parts = cron_expr.split()
    if len(cron_parts) != 5:
        return jsonify({'code': 400, 'msg': 'Cron格式错误'})
    try:
        trigger = CronTrigger(minute=cron_parts[0], hour=cron_parts[1],
                              day=cron_parts[2], month=cron_parts[3], day_of_week=cron_parts[4])
    except Exception as e:
        return jsonify({'code': 400, 'msg': f'时间设置无效: {str(e)}'})

    days_label = '、'.join(day_names[d] for d in sorted(days)) if days else cron_expr
    time_label = run_time if run_time else cron_expr
    jobs[job_id] = {
        'id': job_id, 'name': name, 'cron': cron_expr,
        'days': days, 'time': run_time,
        'days_label': days_label, 'time_label': time_label,
        'task_file': task_file, 'task_filename': task_filename,
        'username': user['username'], 'once': False,
        'use_school_file': use_school_file,
        'enabled': True, 'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'last_run': None, 'last_status': None
    }
    save_json(CRON_JOBS_FILE, jobs)
    scheduler.add_job(execute_cron_job, trigger, id=job_id, args=[job_id])
    return jsonify({'code': 200, 'msg': '定时任务创建成功', 'job_id': job_id})


@app.route('/api/cron/toggle', methods=['POST'])
def api_cron_toggle():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    job_id = request.json.get('job_id')
    jobs = load_json(CRON_JOBS_FILE, {})
    job = jobs.get(job_id)
    if not job or job['username'] != user['username']:
        return jsonify({'code': 404, 'msg': '任务不存在'})
    job['enabled'] = not job['enabled']
    save_json(CRON_JOBS_FILE, jobs)
    if job['enabled']:
        cron = job['cron'].split()
        trigger = CronTrigger(minute=cron[0], hour=cron[1],
                              day=cron[2], month=cron[3], day_of_week=cron[4])
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        scheduler.add_job(execute_cron_job, trigger, id=job_id, args=[job_id])
    else:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    return jsonify({'code': 200, 'msg': '已' + ('启用' if job['enabled'] else '禁用')})


@app.route('/api/cron/delete', methods=['POST'])
def api_cron_delete():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    job_id = request.json.get('job_id')
    jobs = load_json(CRON_JOBS_FILE, {})
    job = jobs.get(job_id)
    if not job or job['username'] != user['username']:
        return jsonify({'code': 404, 'msg': '任务不存在'})
    jobs.pop(job_id)
    save_json(CRON_JOBS_FILE, jobs)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    return jsonify({'code': 200, 'msg': '已删除'})


@app.route('/api/cron/run_now', methods=['POST'])
def api_cron_run_now():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    job_id = request.json.get('job_id')
    jobs = load_json(CRON_JOBS_FILE, {})
    job = jobs.get(job_id)
    if not job or job['username'] != user['username']:
        return jsonify({'code': 404, 'msg': '任务不存在'})
    t = threading.Thread(target=execute_cron_job, args=[job_id], daemon=True)
    t.start()
    return jsonify({'code': 200, 'msg': '已触发立即执行'})


# ---- API: 日志 ----
@app.route('/api/logs', methods=['GET'])
def api_logs():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    logs = load_json(RUN_LOGS_FILE, [])
    user_logs = [l for l in logs if l.get('username') == user['username']]
    return jsonify({'code': 200, 'data': user_logs[-100:]})


# ---- API: 当前跑步进度 ----
@app.route('/api/run/active', methods=['GET'])
def api_run_active():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    with _run_sessions_lock:
        # 优先返回未完成的任务，其次返回最新完成的任务
        active = None
        latest_done = None
        for run_id, sess in _run_sessions.items():
            if sess.get('username') == user['username']:
                last_log = sess['logs'][-1]['msg'] if sess['logs'] else None
                entry = {
                    'run_id': run_id,
                    'current': sess['current'],
                    'total': sess['total'],
                    'done': sess['done'],
                    'success': sess['success'],
                    'last_log': last_log,
                    'all_points': sess.get('all_points', []),
                    'cron_job_name': sess.get('cron_job_name', ''),
                    'is_cron': bool(sess.get('cron_job_id')),
                    'cron_job_id': sess.get('cron_job_id', '')
                }
                if not sess['done']:
                    active = entry
                else:
                    latest_done = entry
        return jsonify({'code': 200, 'data': active or latest_done})


# ---- API: 主页统计 ----
@app.route('/api/home/stats', methods=['GET'])
def api_home_stats():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    try:
        from core import get_term_list, get_run_records
        terms = get_term_list(user['token'], user['device_id'], user['device_name'], user['school_url'])
        if not terms:
            return jsonify({'code': 200, 'data': None})
        # 取最新学期
        latest_term = terms[0]
        all_runs, _ = get_run_records(latest_term['value'], user['token'],
                                      user['device_id'], user['device_name'], user['school_url'])
        qualified = [r for r in all_runs if r.get('isQualified', '1') == '1' and not r.get('noQualifiedReason')]
        unqualified = [r for r in all_runs if r.get('isQualified') == '2' or r.get('noQualifiedReason')]
        total_dist = sum(float(r.get('recordMileage', 0)) for r in qualified)
        target = 40
        pct = min(100, round(len(qualified) / target * 100))
        return jsonify({'code': 200, 'data': {
            'term': latest_term.get('key', ''),
            'qualified': len(qualified),
            'unqualified': len(unqualified),
            'total': len(all_runs),
            'target': target,
            'percent': pct,
            'distance': round(total_dist, 2)
        }})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ---- API: 邮件通知配置 ----
@app.route('/api/email/config', methods=['GET'])
def api_email_config_get():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    cfg = get_email_config(user['username'])
    return jsonify({'code': 200, 'data': {
        'enable': cfg.get('enable', False),
        'receiver': cfg.get('receiver', '')
    }})


@app.route('/api/email/config', methods=['POST'])
def api_email_config_save():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.json
    configs = load_json(EMAIL_CONFIG_FILE, {})
    configs[user['username']] = {
        'enable': bool(data.get('enable', False)),
        'receiver': data.get('receiver', '').strip()
    }
    save_json(EMAIL_CONFIG_FILE, configs)
    return jsonify({'code': 200, 'msg': '保存成功'})


@app.route('/api/email/test', methods=['POST'])
def api_email_test():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    cfg = get_email_config(user['username'])
    if not cfg.get('receiver'):
        return jsonify({'code': 400, 'msg': '请先填写并保存收件人邮箱'})
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    html = f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:24px;border-radius:10px;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,.1)">
      <h2 style="color:#667eea">✅ 邮件通知测试</h2>
      <p>这是一封来自<b>云运动助手</b>的测试邮件。</p>
      <p>如果您收到此邮件，说明邮件通知配置正确。</p>
      <p style="color:#888;font-size:.85rem">发送时间：{now}</p>
    </div>"""
    ok, msg = send_email(cfg, '邮件通知测试', html)
    return jsonify({'code': 200 if ok else 500, 'msg': msg})


# ---- API: 设备列表 ----
@app.route('/api/devices', methods=['GET'])
def api_devices():
    return jsonify({'code': 200, 'data': get_device_list()})


# ---- API: 检查学校是否有内置任务文件 ----
@app.route('/api/school/has_tasks', methods=['GET'])
def api_school_has_tasks():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'has_tasks': False})
    school_name = user.get('school_name', '')
    for key in SCHOOL_TASK_DIRS:
        if key in school_name:
            return jsonify({'code': 200, 'has_tasks': True})
    return jsonify({'code': 200, 'has_tasks': False})



# ---- API: 充值 ----
@app.route('/api/recharge', methods=['POST'])
def api_recharge():
    data = request.get_json(silent=True) or {}
    key = data.get('key', '').strip()
    if not key:
        return jsonify({'code': 400, 'msg': '请输入充值卡密'})
    # 优先从 session 获取（已登录），否则从请求体取
    user = get_current_user()
    if user:
        username = user['username']
        password = user.get('password', '')
    else:
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        if not username or not password:
            return jsonify({'code': 401, 'msg': '请先登录后再充值'})
    try:
        import pymysql as _pym
        from datetime import timedelta as _td
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                # 验证卡密是否存在且未使用
                cur.execute('SELECT `key`, `time`, `username` FROM buy WHERE `key`=%s LIMIT 1', (key,))
                buy_row = cur.fetchone()
                if not buy_row:
                    return jsonify({'code': 400, 'msg': '卡密不存在'})
                if buy_row[2]:
                    return jsonify({'code': 400, 'msg': '该卡密已被使用'})
                add_hours = int(buy_row[1])

                # 获取用户当前到期时间
                cur.execute('SELECT `date` FROM users WHERE username=%s LIMIT 1', (username,))
                user_row = cur.fetchone()
                if not user_row:
                    return jsonify({'code': 400, 'msg': '用户不存在'})

                now = datetime.now()
                current_date = user_row[0]
                # 兼容 datetime 对象和字符串
                if isinstance(current_date, str):
                    try:
                        current_date = datetime.strptime(current_date, '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        current_date = now
                elif current_date is None:
                    current_date = now

                # 未过期从到期时间续，已过期从当前时间续
                base = max(now, current_date)
                new_date = base + _td(hours=add_hours)
                new_date_str = new_date.strftime('%Y-%m-%d %H:%M:%S')

                # 标记卡密已使用
                cur.execute('UPDATE buy SET `username`=%s WHERE `key`=%s', (username, key))
                # 更新用户到期时间
                cur.execute('UPDATE users SET `date`=%s WHERE username=%s', (new_date_str, username))
            conn.commit()

        # 同步更新 session
        sessions = load_json(SESSIONS_FILE, {})
        if username in sessions:
            sessions[username]['user_time'] = new_date_str
            save_json(SESSIONS_FILE, sessions)

        return jsonify({'code': 200, 'msg': f'充值成功，已增加 {add_hours} 小时', 'user_time': new_date_str})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ==================== 管理员后台 ====================

ADMIN_SESSION_KEY = 'admin_username'


def get_db():
    import pymysql
    return get_db_conn()


def get_admin():
    return session.get(ADMIN_SESSION_KEY)


def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get(ADMIN_SESSION_KEY):
            return jsonify({'code': 401, 'msg': '未登录'})
        return f(*args, **kwargs)
    return decorated


# ---- 管理员页面路由 ----
@app.route('/admin')
def admin_index():
    if not session.get(ADMIN_SESSION_KEY):
        return redirect('/admin/login')
    return render_template('admin.html')


@app.route('/admin/login')
def admin_login_page():
    if session.get(ADMIN_SESSION_KEY):
        return redirect('/admin')
    # 首次访问：如果没有管理员，跳转设置页面
    try:
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM admins')
                if cur.fetchone()[0] == 0:
                    return redirect('/admin/setup')
    except Exception:
        pass
    return render_template('admin_login.html')


@app.route('/admin/setup', methods=['GET', 'POST'])
def admin_setup():
    if request.method == 'GET':
        try:
            conn = get_db_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT COUNT(*) FROM admins')
                    if cur.fetchone()[0] > 0:
                        return redirect('/admin/login')
        except Exception:
            pass
        return '''<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>初始化管理员</title>
<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#fff;border-radius:16px;padding:32px;width:380px;box-shadow:0 20px 40px rgba(0,0,0,.15)}
h2{text-align:center;margin-bottom:24px;color:#333}label{display:block;font-size:.85rem;color:#555;margin:12px 0 6px;font-weight:600}
input{width:100%;padding:10px 12px;border:1.5px solid #ddd;border-radius:8px;font-size:.9rem;outline:none}
input:focus{border-color:#667eea;box-shadow:0 0 0 3px rgba(102,126,234,.12)}
button{width:100%;margin-top:20px;padding:12px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer}
button:hover{opacity:.9}.msg{margin-top:12px;padding:10px;border-radius:8px;font-size:.85rem;display:none}
.msg.err{background:#fef2f2;color:#dc2626;border:1px solid #fecaca;display:block}
.msg.ok{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;display:block}</style></head>
<body><div class="card">
<h2>🔧 首次使用 - 设置管理员</h2>
<form onsubmit="submitSetup(event)">
<label>管理员用户名</label><input id="u" placeholder="设置管理员用户名" required>
<label>管理员密码</label><input id="p" type="password" placeholder="设置管理员密码" required>
<label>确认密码</label><input id="p2" type="password" placeholder="再次输入密码" required>
<button type="submit">✅ 确认创建</button>
<div id="msg" class="msg"></div>
</form></div>
<script>
async function submitSetup(e){
  e.preventDefault();
  const u=document.getElementById('u').value,p=document.getElementById('p').value,p2=document.getElementById('p2').value;
  const msgEl=document.getElementById('msg');
  if(p!==p2){msgEl.textContent='两次密码不一致';msgEl.className='msg err';return;}
  const r=await fetch('/admin/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
  const d=await r.json();
  if(d.code===200){msgEl.textContent='创建成功，正在跳转...';msgEl.className='msg ok';setTimeout(()=>window.location.href='/admin/login',1000);}
  else{msgEl.textContent=d.msg||'创建失败';msgEl.className='msg err';}
}
</script></body></html>'''

    # POST 处理
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'code': 400, 'msg': '用户名和密码不能为空'})
    if len(password) < 4:
        return jsonify({'code': 400, 'msg': '密码至少4位'})
    try:
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM admins')
                if cur.fetchone()[0] > 0:
                    return jsonify({'code': 403, 'msg': '管理员已存在，请直接登录'})
                cur.execute('INSERT INTO admins (username, password) VALUES (%s, %s)', (username, password))
            conn.commit()
        return jsonify({'code': 200, 'msg': '创建成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ---- 管理员 API ----
@app.route('/admin/api/setup', methods=['POST'])
def admin_api_setup():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'code': 400, 'msg': '用户名和密码不能为空'})
    if len(password) < 4:
        return jsonify({'code': 400, 'msg': '密码至少4位'})
    try:
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM admins')
                if cur.fetchone()[0] > 0:
                    return jsonify({'code': 403, 'msg': '管理员已存在，请直接登录'})
                cur.execute('INSERT INTO admins (username, password) VALUES (%s, %s)', (username, password))
            conn.commit()
        return jsonify({'code': 200, 'msg': '创建成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})

@app.route('/admin/api/login', methods=['POST'])
def admin_api_login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'code': 400, 'msg': '请填写完整'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT username FROM admins WHERE username=%s AND password=%s LIMIT 1',
                            (username, password))
                row = cur.fetchone()
        if row:
            session[ADMIN_SESSION_KEY] = username
            session.permanent = True
            return jsonify({'code': 200, 'msg': '登录成功'})
        return jsonify({'code': 401, 'msg': '用户名或密码错误'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/logout', methods=['POST'])
def admin_api_logout():
    session.pop(ADMIN_SESSION_KEY, None)
    return jsonify({'code': 200})


@app.route('/admin/api/me')
@require_admin
def admin_api_me():
    return jsonify({'code': 200, 'username': session.get(ADMIN_SESSION_KEY)})


@app.route('/admin/api/stats')
@require_admin
def admin_api_stats():
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM users')
                total = cur.fetchone()[0]
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cur.execute('SELECT COUNT(*) FROM users WHERE `date` > %s', (now_str,))
                active = cur.fetchone()[0]
                cur.execute('SELECT username, school_name, `date` FROM users ORDER BY id DESC LIMIT 10')
                recent = [{'username': r[0], 'school_name': r[1], 'date': str(r[2]) if r[2] else ''} for r in cur.fetchall()]
        return jsonify({'code': 200, 'total': total, 'active': active, 'expired': total - active, 'recent': recent})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/users')
@require_admin
def admin_api_users():
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT username, school_name, `date`, remark FROM users ORDER BY id DESC')
                rows = [{'username': r[0], 'school_name': r[1], 'date': str(r[2]) if r[2] else '', 'remark': r[3] or ''} for r in cur.fetchall()]
        return jsonify({'code': 200, 'data': rows})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/users/expire', methods=['POST'])
@require_admin
def admin_api_set_expire():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    date = data.get('date', '').strip()
    if not username or not date:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE users SET `date`=%s WHERE username=%s', (date, username))
            conn.commit()
        return jsonify({'code': 200, 'msg': '修改成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/users/remark', methods=['POST'])
@require_admin
def admin_api_set_remark():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    remark = data.get('remark', '').strip()
    if not username:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE users SET remark=%s WHERE username=%s', (remark, username))
            conn.commit()
        return jsonify({'code': 200, 'msg': '备注已保存'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/users/delete', methods=['POST'])
@require_admin
def admin_api_delete_user():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM users WHERE username=%s', (username,))
            conn.commit()
        return jsonify({'code': 200, 'msg': '用户已删除'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/users/batch_extend', methods=['POST'])
@require_admin
def admin_api_batch_extend():
    """批量为有效期内的用户延长 N 天"""
    data = request.get_json(silent=True) or {}
    days = int(data.get('days', 0))
    if days <= 0:
        return jsonify({'code': 400, 'msg': '天数必须大于0'})
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                # 取出所有有效用户的 date 字段，在 Python 层面加天数再写回
                cur.execute('SELECT username, `date` FROM users WHERE `date` > %s', (now_str,))
                rows = cur.fetchall()
                count = 0
                for username, date_val in rows:
                    try:
                        # 兼容字符串和时间戳两种格式
                        if isinstance(date_val, str) and len(date_val) > 10:
                            from datetime import timedelta
                            dt = datetime.strptime(date_val, '%Y-%m-%d %H:%M:%S')
                            new_dt = dt + timedelta(days=days)
                            new_val = new_dt.strftime('%Y-%m-%d %H:%M:%S')
                        elif isinstance(date_val, (int, float)) or (isinstance(date_val, str) and date_val.isdigit()):
                            new_val = int(date_val) + days * 86400
                        else:
                            # datetime 对象
                            from datetime import timedelta
                            new_val = (date_val + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                        cur.execute('UPDATE users SET `date`=%s WHERE username=%s', (new_val, username))
                        count += 1
                    except Exception:
                        continue
            conn.commit()
        return jsonify({'code': 200, 'msg': f'已延长 {days} 天', 'count': count})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/school_folders')
@require_admin
def admin_api_school_folders():
    """返回所有已配置的学校文件夹及文件列表"""
    load_school_task_dirs()  # 每次刷新从数据库加载
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT school_name, folder_type, folder_name FROM school_folders ORDER BY school_name, folder_type')
                rows = cur.fetchall()
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})

    schools = {}
    for school_name, folder_type, folder_name in rows:
        if school_name not in schools:
            schools[school_name] = {'school_name': school_name, 'folders': []}
        folder_path = os.path.join(SCHOOL_TASKS_BASE, folder_name)
        files = sorted([f for f in os.listdir(folder_path) if f.endswith('.json')]) if os.path.isdir(folder_path) else []
        schools[school_name]['folders'].append({
            'folder_type': folder_type,
            'folder_name': folder_name,
            'files': files,
            'exists': os.path.isdir(folder_path)
        })
    return jsonify({'code': 200, 'schools': list(schools.values())})


@app.route('/admin/api/school_list')
@require_admin
def admin_api_school_list():
    """从运动服务器获取学校列表"""
    try:
        schools = get_school_list()
        return jsonify({'code': 200, 'data': [s['schoolName'] for s in schools]})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/school_folders/set', methods=['POST'])
@require_admin
def admin_api_set_folder():
    """设置学校对应的文件夹"""
    data = request.get_json(silent=True) or {}
    school_name = data.get('school_name', '').strip()
    folder_type = data.get('folder_type', 'default').strip()
    folder_name = data.get('folder_name', '').strip()
    if not school_name or not folder_name:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    if folder_type not in ('man', 'woman', 'default'):
        return jsonify({'code': 400, 'msg': 'folder_type 必须是 man/woman/default'})
    # 创建文件夹
    folder_path = os.path.join(SCHOOL_TASKS_BASE, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO school_folders (school_name, folder_type, folder_name) VALUES (%s,%s,%s) '
                    'ON DUPLICATE KEY UPDATE folder_name=%s',
                    (school_name, folder_type, folder_name, folder_name)
                )
            conn.commit()
        load_school_task_dirs()
        return jsonify({'code': 200, 'msg': '设置成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/school_folders/delete', methods=['POST'])
@require_admin
def admin_api_delete_folder_config():
    """删除学校文件夹配置（不删除实际文件）"""
    data = request.get_json(silent=True) or {}
    school_name = data.get('school_name', '').strip()
    folder_type = data.get('folder_type', '').strip()
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM school_folders WHERE school_name=%s AND folder_type=%s',
                            (school_name, folder_type))
            conn.commit()
        load_school_task_dirs()
        return jsonify({'code': 200, 'msg': '已删除配置'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


def _get_folder_path(folder_name):
    """根据文件夹名找到路径"""
    if not folder_name or '..' in folder_name or '/' in folder_name or '\\' in folder_name:
        return None
    return os.path.join(SCHOOL_TASKS_BASE, folder_name)


@app.route('/admin/api/school_files/upload', methods=['POST'])
@require_admin
def admin_api_upload():
    folder_name = request.form.get('folder', '')
    folder_path = _get_folder_path(folder_name)
    if not folder_path:
        return jsonify({'code': 400, 'msg': '非法文件夹名'})
    os.makedirs(folder_path, exist_ok=True)
    files = request.files.getlist('files')
    count = sum(1 for f in files if f.filename.endswith('.json') and not f.save(os.path.join(folder_path, f.filename)))
    return jsonify({'code': 200, 'msg': '上传成功', 'count': len(files)})


@app.route('/admin/api/school_files/download')
@require_admin
def admin_api_download():
    from flask import send_file
    folder_name = request.args.get('folder', '')
    filename = request.args.get('file', '')
    folder_path = _get_folder_path(folder_name)
    if not folder_path or not filename or '..' in filename:
        return jsonify({'code': 400, 'msg': '参数错误'})
    file_path = os.path.join(folder_path, filename)
    if not os.path.exists(file_path):
        return jsonify({'code': 404, 'msg': '文件不存在'})
    return send_file(file_path, as_attachment=True, download_name=filename)


@app.route('/admin/api/school_files/delete', methods=['POST'])
@require_admin
def admin_api_delete_file():
    data = request.get_json(silent=True) or {}
    folder_name = data.get('folder', '')
    filename = data.get('file', '')
    folder_path = _get_folder_path(folder_name)
    if not folder_path or not filename or '..' in filename or '/' in filename:
        return jsonify({'code': 400, 'msg': '参数错误'})
    file_path = os.path.join(folder_path, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    return jsonify({'code': 200, 'msg': '删除成功'})


@app.route('/admin/api/admins')
@require_admin
def admin_api_list_admins():
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT username, source FROM admins ORDER BY username')
                rows = [{'username': r[0], 'source': r[1] or '手动创建'} for r in cur.fetchall()]
        return jsonify({'code': 200, 'data': rows})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/admins/add', methods=['POST'])
@require_admin
def admin_api_add_admin():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'code': 400, 'msg': '请填写完整'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM admins WHERE username=%s', (username,))
                if cur.fetchone():
                    return jsonify({'code': 409, 'msg': '管理员已存在'})
                cur.execute('INSERT INTO admins (username, password, source) VALUES (%s, %s, %s)',
                            (username, password, '手动创建'))
            conn.commit()
        return jsonify({'code': 200, 'msg': '添加成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/admins/delete', methods=['POST'])
@require_admin
def admin_api_delete_admin():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    if username == session.get(ADMIN_SESSION_KEY):
        return jsonify({'code': 400, 'msg': '不能删除自己'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM admins WHERE username=%s', (username,))
            conn.commit()
        return jsonify({'code': 200, 'msg': '删除成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/admins/promote', methods=['POST'])
@require_admin
def admin_api_promote():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'code': 400, 'msg': '请选择用户'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                # 从 users 表取密码
                cur.execute('SELECT `key` FROM users WHERE username=%s LIMIT 1', (username,))
                row = cur.fetchone()
                if not row:
                    return jsonify({'code': 404, 'msg': '用户不存在'})
                cur.execute('SELECT 1 FROM admins WHERE username=%s', (username,))
                if cur.fetchone():
                    return jsonify({'code': 409, 'msg': '该用户已是管理员'})
                cur.execute('INSERT INTO admins (username, password, source) VALUES (%s, %s, %s)',
                            (username, row[0], '从用户提升'))
            conn.commit()
        return jsonify({'code': 200, 'msg': '已设为管理员'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/change_password', methods=['POST'])
@require_admin
def admin_api_change_pwd():
    data = request.get_json(silent=True) or {}
    old_pwd = data.get('old_pwd', '').strip()
    new_pwd = data.get('new_pwd', '').strip()
    admin_user = session.get(ADMIN_SESSION_KEY)
    if not old_pwd or not new_pwd:
        return jsonify({'code': 400, 'msg': '请填写完整'})
    if len(new_pwd) < 6:
        return jsonify({'code': 400, 'msg': '新密码至少6位'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM admins WHERE username=%s AND password=%s', (admin_user, old_pwd))
                if not cur.fetchone():
                    return jsonify({'code': 401, 'msg': '当前密码错误'})
                cur.execute('UPDATE admins SET password=%s WHERE username=%s', (new_pwd, admin_user))
            conn.commit()
        return jsonify({'code': 200, 'msg': '密码修改成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ==================== 密钥管理 ====================
@app.route('/admin/api/keys')
@require_admin
def admin_api_keys():
    filter_type = request.args.get('filter', 'all')
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                if filter_type == 'unused':
                    cur.execute('SELECT `key`, `time`, `username` FROM buy WHERE username IS NULL OR username="" ORDER BY `key`')
                elif filter_type == 'used':
                    cur.execute('SELECT `key`, `time`, `username` FROM buy WHERE username IS NOT NULL AND username!="" ORDER BY `key`')
                else:
                    cur.execute('SELECT `key`, `time`, `username` FROM buy ORDER BY `key`')
                rows = [{'key': r[0], 'time': r[1], 'username': r[2] or ''} for r in cur.fetchall()]
        return jsonify({'code': 200, 'data': rows})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/keys/generate', methods=['POST'])
@require_admin
def admin_api_generate_keys():
    import secrets, string
    data = request.get_json(silent=True) or {}
    hours = int(data.get('hours', 720))
    count = min(int(data.get('count', 1)), 100)
    if hours <= 0 or count <= 0:
        return jsonify({'code': 400, 'msg': '参数错误'})
    chars = string.ascii_uppercase + string.digits
    generated = []
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                for _ in range(count):
                    key = ''.join(secrets.choice(chars) for _ in range(16))
                    cur.execute('INSERT INTO buy (`key`, `time`) VALUES (%s, %s)', (key, hours))
                    generated.append(key)
            conn.commit()
        return jsonify({'code': 200, 'keys': generated})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/keys/delete', methods=['POST'])
@require_admin
def admin_api_delete_key():
    data = request.get_json(silent=True) or {}
    key = data.get('key', '').strip()
    if not key:
        return jsonify({'code': 400, 'msg': '参数错误'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM buy WHERE `key`=%s', (key,))
            conn.commit()
        return jsonify({'code': 200, 'msg': '删除成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ==================== 设备管理 ====================
@app.route('/admin/api/devices', methods=['GET'])
@require_admin
def admin_api_devices():
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id, name FROM devices ORDER BY id')
                rows = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
        return jsonify({'code': 200, 'data': rows})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/devices/add', methods=['POST'])
@require_admin
def admin_api_add_device():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'code': 400, 'msg': '设备名称不能为空'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('INSERT INTO devices (name) VALUES (%s)', (name,))
            conn.commit()
        return jsonify({'code': 200, 'msg': '添加成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/devices/update', methods=['POST'])
@require_admin
def admin_api_update_device():
    data = request.get_json(silent=True) or {}
    did = data.get('id')
    name = data.get('name', '').strip()
    if not did or not name:
        return jsonify({'code': 400, 'msg': '参数错误'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE devices SET name=%s WHERE id=%s', (name, did))
            conn.commit()
        return jsonify({'code': 200, 'msg': '修改成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/devices/delete', methods=['POST'])
@require_admin
def admin_api_delete_device():
    data = request.get_json(silent=True) or {}
    did = data.get('id')
    if not did:
        return jsonify({'code': 400, 'msg': '参数错误'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM devices WHERE id=%s', (did,))
            conn.commit()
        return jsonify({'code': 200, 'msg': '删除成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ==================== 用户密码修改 ====================
@app.route('/admin/api/users/password', methods=['POST'])
@require_admin
def admin_api_set_user_password():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    new_password = data.get('password', '').strip()
    if not username or not new_password:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    if len(new_password) < 6:
        return jsonify({'code': 400, 'msg': '密码至少6位'})
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE users SET `key`=%s WHERE username=%s', (new_password, username))
            conn.commit()
        return jsonify({'code': 200, 'msg': '密码修改成功'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ==================== 系统配置 ====================
@app.route('/admin/api/sys_config', methods=['GET'])
@require_admin
def admin_api_get_sys_config():
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT `key`, `value`, `desc` FROM sys_config ORDER BY `key`')
                rows = [{'key': r[0], 'value': r[1], 'desc': r[2] or ''} for r in cur.fetchall()]
        return jsonify({'code': 200, 'data': rows})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/sys_config', methods=['POST'])
@require_admin
def admin_api_save_sys_config():
    data = request.get_json(silent=True) or {}
    key = data.get('key', '').strip()
    value = data.get('value', '').strip()
    if not key or not value:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    try:
        save_sys_config(key, value)
        # 如果修改了 scheduler 配置，重启 scheduler
        if key in ('scheduler_max_workers', 'scheduler_max_instances'):
            global scheduler
            if scheduler.running:
                scheduler.shutdown(wait=False)
            scheduler = build_scheduler()
            reload_all_cron_jobs()
            scheduler.start()
        # 如果修改了 app_edition，同步更新 core 模块全局变量
        if key == 'app_edition':
            import core as _core
            _core.app_edition = value
        return jsonify({'code': 200, 'msg': '保存成功，已生效'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ==================== 管理后台：邮件配置 ====================
@app.route('/admin/api/email/config', methods=['GET'])
@require_admin
def admin_api_email_config_get():
    """获取系统邮件配置"""
    cfg = get_sys_email_config()
    return jsonify({'code': 200, 'data': cfg})


@app.route('/admin/api/email/config', methods=['POST'])
@require_admin
def admin_api_email_config_save():
    """保存系统邮件配置"""
    data = request.get_json(silent=True) or {}
    if save_sys_email_config(data):
        return jsonify({'code': 200, 'msg': '邮件配置已保存'})
    return jsonify({'code': 500, 'msg': '保存失败'})


@app.route('/admin/api/email/test', methods=['POST'])
@require_admin
def admin_api_email_test():
    """发送测试邮件"""
    data = request.get_json(silent=True) or {}
    receiver = data.get('receiver', '').strip()
    if not receiver:
        return jsonify({'code': 400, 'msg': '请填写收件人邮箱'})
    ok, msg = send_email({'enable': True, 'receiver': receiver}, '测试邮件', '<h2>邮件配置成功！</h2><p>这是一封测试邮件，说明 SMTP 配置正确。</p>')
    return jsonify({'code': 200 if ok else 500, 'msg': msg})


# ==================== 地图配置 ====================
def get_sys_config_value(key, default=''):
    """从 sys_config 表读取单个配置值"""
    try:
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT `value` FROM sys_config WHERE `key`=%s', (key,))
                row = cur.fetchone()
        return row[0] if row else default
    except Exception:
        return default


@app.route('/api/config/map_key', methods=['GET'])
def api_map_key():
    """前端获取高德地图 key（无需登录）"""
    key = get_sys_config_value('amap_key', '')
    security = get_sys_config_value('amap_security_code', '')
    return jsonify({'code': 200, 'data': {'key': key, 'security_code': security}})


@app.route('/admin/api/map/config', methods=['GET'])
@require_admin
def admin_api_map_config_get():
    """管理后台获取地图配置"""
    return jsonify({'code': 200, 'data': {
        'amap_key': get_sys_config_value('amap_key', ''),
        'amap_security_code': get_sys_config_value('amap_security_code', ''),
    }})


@app.route('/admin/api/map/config', methods=['POST'])
@require_admin
def admin_api_map_config_save():
    """管理后台保存地图配置"""
    data = request.get_json(silent=True) or {}
    try:
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                for key in ('amap_key', 'amap_security_code'):
                    if key in data:
                        cur.execute(
                            "INSERT INTO sys_config (`key`, `value`, `desc`) VALUES (%s, %s, %s) "
                            "ON DUPLICATE KEY UPDATE `value`=%s",
                            (key, data[key], {'amap_key': '高德地图Key', 'amap_security_code': '高德安全密钥'}[key], data[key])
                        )
            conn.commit()
        return jsonify({'code': 200, 'msg': '地图配置已保存'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ==================== 管理后台：定时任务 & 日志 ====================
@app.route('/admin/api/cron/list')
@require_admin
def admin_api_cron_list():
    """获取所有用户的定时任务"""
    jobs = load_json(CRON_JOBS_FILE, {})
    return jsonify({'code': 200, 'data': list(jobs.values())})


@app.route('/admin/api/cron/toggle', methods=['POST'])
@require_admin
def admin_api_cron_toggle():
    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id', '')
    jobs = load_json(CRON_JOBS_FILE, {})
    if job_id not in jobs:
        return jsonify({'code': 404, 'msg': '任务不存在'})
    jobs[job_id]['enabled'] = not jobs[job_id].get('enabled', True)
    save_json(CRON_JOBS_FILE, jobs)
    enabled = jobs[job_id]['enabled']
    if enabled:
        job = jobs[job_id]
        try:
            if job.get('cron'):
                cron = job['cron'].split()
                trigger = CronTrigger(minute=cron[0], hour=cron[1], day=cron[2], month=cron[3], day_of_week=cron[4])
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
                scheduler.add_job(execute_cron_job, trigger, id=job_id, args=[job_id])
        except Exception:
            pass
    else:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    return jsonify({'code': 200, 'msg': '已' + ('启用' if enabled else '禁用')})


@app.route('/admin/api/cron/delete', methods=['POST'])
@require_admin
def admin_api_cron_delete():
    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id', '')
    jobs = load_json(CRON_JOBS_FILE, {})
    if job_id not in jobs:
        return jsonify({'code': 404, 'msg': '任务不存在'})
    jobs.pop(job_id)
    save_json(CRON_JOBS_FILE, jobs)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    return jsonify({'code': 200, 'msg': '已删除'})


@app.route('/admin/api/logs')
@require_admin
def admin_api_logs():
    username = request.args.get('username', '')
    logs = load_json(RUN_LOGS_FILE, [])
    if username:
        logs = [l for l in logs if l.get('username') == username]
    return jsonify({'code': 200, 'data': list(reversed(logs[-200:]))})


@app.route('/admin/api/users/list_simple')
@require_admin
def admin_api_users_simple():
    """返回用户名列表，用于日志筛选"""
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT username FROM users ORDER BY username')
                users = [r[0] for r in cur.fetchall()]
        return jsonify({'code': 200, 'data': users})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/pu/users')
@require_admin
def admin_api_pu_users():
    """获取所有 PU 用户及其自动托管状态"""
    try:
        conn = _pu_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT id, user_name, college, email, yunrun_username, auto_scheduler FROM pu_users ORDER BY yunrun_username, id'
                )
                rows = cur.fetchall()
        data = [{'id': r[0], 'userName': r[1], 'college': r[2] or '', 'email': r[3] or '',
                 'yunrun_username': r[4] or '', 'auto_scheduler': bool(r[5])} for r in rows]
        return jsonify({'code': 200, 'data': data})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/admin/api/pu/users/toggle', methods=['POST'])
@require_admin
def admin_api_pu_toggle():
    """管理员开关某个 PU 用户的自动托管"""
    data = request.get_json(silent=True) or {}
    uid = data.get('id')
    enabled = bool(data.get('enabled'))
    if not uid:
        return jsonify({'code': 400, 'msg': '缺少 id'})
    try:
        conn = _pu_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE pu_users SET auto_scheduler=%s WHERE id=%s', (1 if enabled else 0, uid))
            conn.commit()
        return jsonify({'code': 200})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


# ==================== 口袋校园自动报名模块 ====================
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_pu_state_lock = threading.Lock()
_pu_log_buf = []
_pu_jobs = {}
_pu_scheduler_thread = None
_pu_scheduler_stop = None
_pu_scheduled_keys = set()


def _pu_db():
    return get_db_conn()


def _pu_log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with _pu_state_lock:
        _pu_log_buf.append(line)
        if len(_pu_log_buf) > 400:
            _pu_log_buf.pop(0)


def _pu_read_users():
    conn = _pu_db()
    with conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id, user_name, password, token, sid, device, college, email, yunrun_username, auto_scheduler FROM pu_users ORDER BY id')
            rows = cur.fetchall()
    return [{'id': r[0], 'userName': r[1], 'password': r[2], 'token': r[3],
             'sid': r[4], 'device': r[5] or 'pc', 'college': r[6] or '', 'email': r[7] or '',
             'yunrun_username': r[8] or '', 'auto_scheduler': bool(r[9])} for r in rows]


def _pu_read_users_for(yunrun_username):
    """只读取当前登录用户绑定的口袋账号"""
    conn = _pu_db()
    with conn:
        with conn.cursor() as cur:
            # uid 列可能不存在，用 try 降级
            try:
                cur.execute('SELECT id, user_name, password, token, sid, device, college, email, auto_scheduler, uid FROM pu_users WHERE yunrun_username=%s ORDER BY id', (yunrun_username,))
                rows = cur.fetchall()
                return [{'id': r[0], 'userName': r[1], 'password': r[2], 'token': r[3],
                         'sid': r[4], 'device': r[5] or 'pc', 'college': r[6] or '', 'email': r[7] or '',
                         'auto_scheduler': bool(r[8]), 'uid': r[9] or ''} for r in rows]
            except Exception:
                cur.execute('SELECT id, user_name, password, token, sid, device, college, email, auto_scheduler FROM pu_users WHERE yunrun_username=%s ORDER BY id', (yunrun_username,))
                rows = cur.fetchall()
                return [{'id': r[0], 'userName': r[1], 'password': r[2], 'token': r[3],
                         'sid': r[4], 'device': r[5] or 'pc', 'college': r[6] or '', 'email': r[7] or '',
                         'auto_scheduler': bool(r[8]), 'uid': ''} for r in rows]


def _pu_get_mgr(yunrun_username=None):
    """获取 UserDataMager，用内存数据而非文件"""
    try:
        from pu_core import UserDataMager
        mgr = UserDataMager.__new__(UserDataMager)
        mgr.file_path = ''
        mgr.user_datas = _pu_read_users_for(yunrun_username) if yunrun_username else _pu_read_users()
        return mgr
    except Exception as e:
        raise RuntimeError(f'pu_core 加载失败: {e}')


@app.route('/signup/')
@app.route('/signup')
def signup_index():
    if not session.get('username'):
        return redirect(url_for('login_page'))
    sessions = load_json(SESSIONS_FILE, {})
    user = sessions.get(session['username'], {})
    school = user.get('school_name', '')
    if '安徽邮电' not in school:
        return redirect(url_for('index'))
    return render_template('signup.html')


@app.route('/api/signup/users', methods=['GET'])
def pu_api_users():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    try:
        return jsonify({'code': 200, 'data': _pu_read_users_for(user['username'])})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/signup/users/add', methods=['POST'])
def pu_api_users_add():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.get_json(silent=True) or {}
    # 学校名和用户名从 session 自动获取
    school_name = user.get('school_name', '').strip()
    user_name = user.get('username', '').strip()
    password = data.get('password', '')
    email = data.get('email', '').strip()
    if not school_name or not user_name or not password:
        return jsonify({'code': 400, 'msg': '缺少学校/用户名/密码'})
    try:
        mgr = _pu_get_mgr()
        # 禁用文件写入，数据直接存数据库
        mgr.write_user_data = lambda: None
        new_user = mgr.add_user_from_gui(school_name, user_name, password, email=email)
        conn = _pu_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO pu_users (user_name, password, token, sid, device, college, email, yunrun_username) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) '
                    'ON DUPLICATE KEY UPDATE token=%s, password=%s, email=%s',
                    (new_user['userName'], new_user['password'], new_user.get('token'), new_user.get('sid'),
                     new_user.get('device', 'pc'), new_user.get('college', ''), new_user.get('email', ''), user['username'],
                     new_user.get('token'), new_user['password'], new_user.get('email', ''))
                )
            conn.commit()
        _pu_log(f'用户绑定: {new_user["userName"]} -> {user["username"]}')
        return jsonify({'code': 200, 'msg': '绑定成功', 'user': new_user})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/signup/users/delete', methods=['POST'])
def pu_api_users_delete():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.get_json(silent=True) or {}
    uid = data.get('id')
    if not uid:
        return jsonify({'code': 400, 'msg': '缺少 id'})
    try:
        conn = _pu_db()
        with conn:
            with conn.cursor() as cur:
                # 只能删除自己的账号
                cur.execute('DELETE FROM pu_users WHERE id=%s AND yunrun_username=%s', (uid, user['username']))
            conn.commit()
        return jsonify({'code': 200, 'msg': '已删除'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/signup/users/scheduler', methods=['POST'])
def pu_api_toggle_scheduler():
    """用户自己控制是否启用自动托管"""
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled', False))
    try:
        conn = _pu_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE pu_users SET auto_scheduler=%s WHERE yunrun_username=%s',
                            (1 if enabled else 0, user['username']))
            conn.commit()
        return jsonify({'code': 200, 'msg': '已' + ('启用' if enabled else '禁用') + '自动托管'})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/signup/schools', methods=['GET'])
def pu_api_schools():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    keyword = request.args.get('keyword', '').strip()
    try:
        mgr = _pu_get_mgr()
        schools = mgr.search_schools(keyword, limit=30) if keyword else mgr.fetch_school_list()[:30]
        return jsonify({'code': 200, 'data': [{'name': s.get('name', ''), 'go_id': s.get('go_id')} for s in schools]})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/signup/activities', methods=['POST'])
def pu_api_activities():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.get_json(silent=True) or {}
    only_future = bool(data.get('only_future', True))
    try:
        pu_users = _pu_read_users_for(user['username'])
        if not pu_users:
            return jsonify({'code': 400, 'msg': '请先绑定口袋校园账号'})

        # 并发刷新所有绑定账号的 token
        from concurrent.futures import ThreadPoolExecutor, as_completed
        refreshed = []
        with ThreadPoolExecutor(max_workers=min(len(pu_users), 5)) as pool:
            futs = {pool.submit(_pu_refresh_token, u): u for u in pu_users}
            for f in as_completed(futs):
                try:
                    refreshed.append(f.result())
                except Exception:
                    refreshed.append(futs[f])
        # 用第一个有效 token 获取活动列表（同校活动相同）
        valid_user = next((u for u in refreshed if u.get('token')), refreshed[0])
        mgr = _pu_get_mgr(user['username'])
        mgr.user_datas = refreshed
        activities = mgr.fetch_activity_list(valid_user, limit=50)
        if only_future:
            activities = mgr.filter_future_activities(activities)
        # 对每条活动补充详情
        briefs = []
        for a in activities:
            aid = a.get('id') or a.get('activityId')
            detail = mgr.fetch_activity_detail(valid_user, aid)
            if detail:
                merged = {**detail, **a}
                for key in ('joinEndTime', 'categoryName', 'creatorName', 'address', 'isAudit', 'description'):
                    if key not in merged or not merged.get(key):
                        merged[key] = detail.get(key, '')
            else:
                merged = a
            briefs.append(mgr.extract_activity_brief(merged))
        return jsonify({'code': 200, 'data': briefs})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/signup/my_activities', methods=['POST'])
def pu_api_my_activities():
    """获取当前用户的已报名/已完成活动记录"""
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.get_json(silent=True) or {}
    act_type = int(data.get('type', 1))  # 1=已报名, 2=已完成, 3=已评价
    page = int(data.get('page', 1))
    limit = int(data.get('limit', 20))
    try:
        pu_users = _pu_read_users_for(user['username'])
        if not pu_users:
            return jsonify({'code': 400, 'msg': '请先绑定口袋校园账号'})
        # 刷新 token
        pu_user = _pu_refresh_token(pu_users[0])
        mgr = _pu_get_mgr(user['username'])
        result = mgr.fetch_my_activities(pu_user, act_type=act_type, page=page, limit=limit)
        # 对每条活动补充详情
        briefs = []
        for a in result.get('list', []):
            briefs.append(mgr.extract_activity_brief(a))
        return jsonify({'code': 200, 'data': briefs, 'pageInfo': result.get('pageInfo', {})})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/signup/qrcode', methods=['GET'])
def pu_api_qrcode():
    """本地生成签到用实时二维码（DES加密，每30秒刷新）"""
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    try:
        pu_users = _pu_read_users_for(user['username'])
        if not pu_users:
            return jsonify({'code': 400, 'msg': '请先绑定口袋校园账号'})
        pu_user = _pu_refresh_token(pu_users[0])
        # 如果数据库没有 uid，从登录响应获取
        if not pu_user.get('uid'):
            import requests as _req
            try:
                lr = _req.post('https://apis.pocketuni.net/uc/user/login',
                    headers={'Content-Type': 'application/json'},
                    json={'userName': pu_user['userName'], 'password': pu_user['password'],
                          'sid': int(pu_user['sid']), 'device': 'pc'}, timeout=10)
                ld = lr.json() if lr.content else {}
                pu_user['uid'] = ld.get('data', {}).get('baseUserInfo', {}).get('id', '')
            except Exception:
                pass
        if not pu_user.get('uid'):
            return jsonify({'code': 500, 'msg': '无法获取用户UID，请重新绑定账号'})
        mgr = _pu_get_mgr(user['username'])
        qr = mgr.generate_sign_qrcode(pu_user)
        if not qr or not qr.get('base64'):
            return jsonify({'code': 500, 'msg': '生成二维码失败'})
        return jsonify({'code': 200, 'data': qr})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


@app.route('/api/signup/start', methods=['POST'])
def pu_api_signup_start():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.get_json(silent=True) or {}
    activity_id = data.get('activity_id')
    join_start_time = data.get('join_start_time', '').strip()
    if not activity_id or not join_start_time:
        return jsonify({'code': 400, 'msg': '缺少 activity_id 或 join_start_time'})

    job_id = str(uuid.uuid4())[:8]
    with _pu_state_lock:
        _pu_jobs[job_id] = {'status': 'running', 'result': None}

    def _build_signup_email(ok, user_name, base, now, msg_text):
        allow = base.get('allowUserCount', 0) or 0
        joined = base.get('joinUserCount', 0) or 0
        desc = base.get('description', '') or ''
        desc_short = (desc[:100] + '...') if len(desc) > 100 else desc or '无'
        fields = [
            ('活动名称',   base.get('name') or base.get('title') or '—'),
            ('活动分类',   base.get('categoryName') or '—'),
            ('举办组织',   base.get('creatorName') or '—'),
            ('活动地址',   base.get('address') or '—'),
            ('分数/学时',  base.get('credit') if base.get('credit') is not None else '—'),
            ('可报名人数', allow),
            ('已报名人数', joined),
            ('剩余名额',   allow - joined),
            ('活动状态',   base.get('statusName') or '—'),
            ('开始报名',   base.get('joinStartTime') or '—'),
            ('结束报名',   base.get('joinEndTime') or '—'),
            ('活动开始',   base.get('startTime') or '—'),
            ('活动结束',   base.get('endTime') or '—'),
            ('是否审核',   '是' if base.get('isAudit') else '否'),
            ('活动简介',   desc_short),
        ]
        rows_html = ''.join(
            f'<tr>'
            f'<td style="padding:8px 16px 8px 0;color:#666;white-space:nowrap;font-size:13px">{label}</td>'
            f'<td style="padding:8px 0;color:#222;font-size:13px"><b>{val}</b></td>'
            f'</tr>'
            for label, val in fields
        )
        if ok:
            header_bg = 'linear-gradient(135deg,#43a047,#1b5e20)'
            icon = '✅'
            title = '报名成功'
            extra = f'<p style="color:#555;font-size:13px">服务器消息：{msg_text}</p>' if msg_text else ''
        else:
            header_bg = 'linear-gradient(135deg,#e53935,#b71c1c)'
            icon = '❌'
            title = '报名失败'
            extra = f'<div style="background:#fff3f3;border-left:4px solid #e53935;padding:10px 14px;border-radius:4px;margin:12px 0;font-size:13px;color:#c62828">失败原因：{msg_text}</div>' if msg_text else ''

        return f'''
<div style="font-family:'PingFang SC','Microsoft YaHei',sans-serif;max-width:560px;margin:0 auto;
            border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.12)">
  <div style="background:{header_bg};color:#fff;padding:28px 24px;text-align:center">
    <div style="font-size:2.8rem;line-height:1">{icon}</div>
    <h2 style="margin:10px 0 4px;font-size:1.4rem">{title}</h2>
    <p style="margin:0;opacity:.85;font-size:.85rem">{now}</p>
  </div>
  <div style="padding:24px;background:#fff">
    <p style="margin:0 0 16px;font-size:14px">用户：<b>{user_name}</b></p>
    {extra}
    <div style="background:#f8f9fa;border-radius:8px;padding:4px 16px;margin-top:8px">
      <table style="border-collapse:collapse;width:100%">{rows_html}</table>
    </div>
  </div>
  <div style="background:#f1f3f5;padding:12px;text-align:center;color:#aaa;font-size:.75rem">
    此邮件由口袋校园报名助手自动发送
  </div>
</div>'''

    def _run():
        try:
            mgr = _pu_get_mgr(user['username'])
            mgr._try_send_email = lambda *a, **kw: None

            # 并发刷新所有账号的 token
            from concurrent.futures import ThreadPoolExecutor, as_completed
            pu_users = mgr.user_datas
            refreshed = []
            with ThreadPoolExecutor(max_workers=min(len(pu_users), 5)) as pool:
                futs = {pool.submit(_pu_refresh_token, u): u for u in pu_users}
                for f in as_completed(futs):
                    try:
                        refreshed.append(f.result())
                    except Exception:
                        refreshed.append(futs[f])
            mgr.user_datas = refreshed
            pu_users = refreshed

            # 提前拉取活动详情，用于邮件展示
            base = {}
            if pu_users:
                try:
                    base = mgr.fetch_activity_detail(pu_users[0], int(activity_id)) or {}
                except Exception:
                    base = {}
            result = mgr.auto_signup_multithread(int(activity_id), join_start_time)
            # 写入日志
            try:
                conn = _pu_db()
                with conn:
                    with conn.cursor() as cur:
                        for r in (result if isinstance(result, list) else [result]):
                            cur.execute(
                                'INSERT INTO pu_signup_logs (user_name, activity_id, join_start_time, status, result) VALUES (%s,%s,%s,%s,%s)',
                                (str(r.get('userName', '')), int(activity_id), join_start_time,
                                 'success' if r.get('ok') or r.get('success') else 'failed',
                                 json.dumps(r, ensure_ascii=False))
                            )
                    conn.commit()
            except Exception:
                pass
            # 发送邮件通知
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for r in (result if isinstance(result, list) else [result]):
                to_email = ''
                for u in mgr.user_datas:
                    if u.get('userName') == r.get('userName'):
                        to_email = (u.get('email') or '').strip()
                        break
                if not to_email:
                    continue
                ok = bool(r.get('ok') or r.get('success'))
                msg_text = r.get('msg', '')
                activity_title = base.get('name') or base.get('title') or str(activity_id)
                subject = f'{"报名成功" if ok else "报名失败"} - {activity_title}'
                body = _build_signup_email(ok, r.get('userName', ''), base, now, msg_text)
                threading.Thread(
                    target=send_email,
                    args=({'enable': True, 'receiver': to_email}, subject, body),
                    daemon=True
                ).start()
            with _pu_state_lock:
                _pu_jobs[job_id] = {'status': 'completed', 'result': result}
            _pu_log(f'报名完成 job={job_id}')
        except Exception as e:
            with _pu_state_lock:
                _pu_jobs[job_id] = {'status': 'failed', 'result': str(e)}
            _pu_log(f'报名失败 job={job_id}: {e}')

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'code': 200, 'job_id': job_id})


@app.route('/api/signup/job/<job_id>', methods=['GET'])
def pu_api_job(job_id):
    with _pu_state_lock:
        job = _pu_jobs.get(job_id)
    if not job:
        return jsonify({'code': 404, 'msg': '任务不存在'})
    return jsonify({'code': 200, 'data': job})


@app.route('/api/signup/logs', methods=['GET'])
def pu_api_logs():
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    with _pu_state_lock:
        return jsonify({'code': 200, 'data': list(_pu_log_buf)})


@app.route('/api/signup/scheduled', methods=['GET'])
def pu_api_scheduled():
    """返回当前用户已注册的定时报名任务列表"""
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    try:
        import pymysql as _pym
        # 获取该用户的所有 PU 账号 id
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id, user_name FROM pu_users WHERE yunrun_username=%s', (user['username'],))
                uid_rows = cur.fetchall()
        if not uid_rows:
            return jsonify({'code': 200, 'data': []})
        uid_set = {str(r[0]) for r in uid_rows}
        user_name_set = {r[1] for r in uid_rows}

        # 从 APScheduler 读取所有 pu_signup_* 任务
        all_jobs = scheduler.get_jobs()
        pu_jobs = [j for j in all_jobs if j.id.startswith('pu_signup_')]

        # 同时查报名结果日志
        conn2 = get_db_conn()
        with conn2:
            with conn2.cursor() as cur:
                cur.execute(
                    'SELECT activity_id, status, result FROM pu_signup_logs '
                    'WHERE user_name IN (SELECT user_name FROM pu_users WHERE yunrun_username=%s) '
                    'ORDER BY id DESC LIMIT 200',
                    (user['username'],)
                )
                log_rows = cur.fetchall()

        # 同时查 pu_scheduled_keys 表（如果存在）
        db_keys = []
        try:
            conn3 = get_db_conn()
            with conn3:
                with conn3.cursor() as cur:
                    placeholders = ','.join(['%s'] * len(uid_set))
                    for uid in uid_set:
                        cur.execute(
                            "SELECT `key`, title, created_at FROM pu_scheduled_keys WHERE `key` LIKE %s ORDER BY created_at DESC LIMIT 100",
                            (f'pu|{uid}|%',)
                        )
                        db_keys.extend(cur.fetchall())
        except Exception:
            pass

        # 建立 activity_id -> 报名结果 映射
        result_map = {}
        for lr in log_rows:
            aid = str(lr[0])
            if aid not in result_map:
                result_map[aid] = {'status': lr[1], 'msg': ''}
                try:
                    r = json.loads(lr[2]) if lr[2] else {}
                    if isinstance(r, list): r = r[0] if r else {}
                    result_map[aid]['msg'] = r.get('msg', '')
                except Exception:
                    pass

        data = []
        seen_aids = set()

        # 优先从 APScheduler job 列表构建（最准确）
        for job in pu_jobs:
            # job.id = pu_signup_{uid}_{aid}
            parts = job.id.split('_')
            if len(parts) < 4:
                continue
            uid_str = parts[2]
            aid_str = parts[3]
            # uid_set 可能是 int 或 str，统一转 str 比较
            if uid_str not in {str(u) for u in uid_set}:
                continue
            seen_aids.add(aid_str)
            args = job.args or []
            title = args[3] if len(args) >= 4 else aid_str
            jst = args[2] if len(args) >= 3 else ''
            next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else None
            result_info = result_map.get(aid_str, {})
            status = result_info.get('status', 'scheduled') if result_info else 'scheduled'
            data.append({
                'activity_id': aid_str,
                'title': title,
                'join_start_time': jst,
                'next_run': next_run,
                'status': status,
                'result_msg': result_info.get('msg', ''),
                'created_at': '',
            })

        # 补充数据库里有但 APScheduler 已执行完的任务
        for row in sorted(db_keys, key=lambda x: x[2], reverse=True):
            key, db_title, created_at = row[0], row[1] or '', row[2]
            kparts = key.split('|')
            if len(kparts) < 3:
                continue
            aid_str = kparts[2]
            jst = '|'.join(kparts[3:]) if len(kparts) > 3 else ''
            if aid_str in seen_aids:
                continue
            seen_aids.add(aid_str)
            result_info = result_map.get(aid_str, {})
            status = result_info.get('status', 'done') if result_info else 'done'
            data.append({
                'activity_id': aid_str,
                'title': db_title or aid_str,
                'join_start_time': jst,
                'next_run': None,
                'status': status,
                'result_msg': result_info.get('msg', ''),
                'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S') if hasattr(created_at, 'strftime') else str(created_at),
            })

        return jsonify({'code': 200, 'data': data,
                        '_debug': {'jobs': [j.id for j in pu_jobs], 'uid_set': list(uid_set)}})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


def _pu_refresh_token(u: dict) -> dict:
    """确保 user dict 中有可用的 token。
    策略：先从数据库读最新 token → 测试是否可用 → 可用直接用 → 不可用则重新登录获取。
    """
    import requests as _req
    import pymysql as _pym
    fresh_u = dict(u)

    # Step 1: 从数据库读取最新 token（可能被其他流程更新过）
    try:
        _c = get_db_conn()
        with _c:
            with _c.cursor() as cur:
                cur.execute('SELECT token FROM pu_users WHERE id=%s', (u['id'],))
                row = cur.fetchone()
        if row and row[0]:
            fresh_u['token'] = row[0]
    except Exception:
        pass

    # Step 2: 测试 token 是否可用
    token_valid = False
    try:
        test_resp = _req.post(
            'https://apis.pocketuni.net/apis/activity/list',
            headers={
                'Authorization': f'Bearer {fresh_u.get("token", "")}:{fresh_u.get("sid")}',
                'Content-Type': 'application/json'
            },
            json={'sort': 0, 'page': 1, 'limit': 1, 'puType': 0, 'status': 0},
            timeout=8
        )
        test_data = test_resp.json() if test_resp.content else {}
        if test_data.get('code') == 0:
            token_valid = True
    except Exception:
        pass

    if token_valid:
        return fresh_u

    # Step 3: token 不可用，重新登录获取
    _pu_log(f'[token刷新] {fresh_u["userName"]} token 失效，重新登录')
    try:
        login_resp = _req.post(
            'https://apis.pocketuni.net/uc/user/login',
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36',
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/plain, */*'
            },
            json={
                'userName': fresh_u['userName'],
                'password': fresh_u['password'],
                'sid': int(fresh_u['sid']),
                'device': 'pc'
            },
            timeout=10
        )
        login_data = login_resp.json() if login_resp.content else {}
        if login_data.get('code') == 0:
            new_token = login_data.get('data', {}).get('token')
            new_uid = login_data.get('data', {}).get('baseUserInfo', {}).get('id', '')
            if new_token:
                fresh_u['token'] = new_token
                if new_uid:
                    fresh_u['uid'] = new_uid
                _pu_log(f'[token刷新] {fresh_u["userName"]} 重新登录成功')
                # 保存新 token 和 uid 到数据库
                try:
                    _c2 = get_db_conn()
                    with _c2:
                        with _c2.cursor() as cur:
                            if new_uid:
                                cur.execute('UPDATE pu_users SET token=%s, uid=%s WHERE id=%s', (new_token, new_uid, u['id']))
                            else:
                                cur.execute('UPDATE pu_users SET token=%s WHERE id=%s', (new_token, u['id']))
                        _c2.commit()
                except Exception:
                    pass
        else:
            _pu_log(f'[token刷新] {fresh_u["userName"]} 登录失败: {login_data.get("message", "未知错误")}')
    except Exception as e:
        _pu_log(f'[token刷新] {fresh_u["userName"]} 登录异常: {e}')

    return fresh_u


def _pu_do_signup(pu_user_id: int, activity_id: int, join_start_time: str, activity_title: str):
    """APScheduler 定时任务执行函数：到点报名"""
    import pymysql as _pym
    try:
        # 从数据库读最新用户信息
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id, user_name, password, token, sid, device, college, email FROM pu_users WHERE id=%s', (pu_user_id,))
                row = cur.fetchone()
        if not row:
            _pu_log(f'[定时报名] 用户ID {pu_user_id} 不存在，跳过')
            return
        u = {'id': row[0], 'userName': row[1], 'password': row[2], 'token': row[3],
             'sid': row[4], 'device': row[5] or 'pc', 'college': row[6] or '', 'email': row[7] or ''}
    except Exception as e:
        _pu_log(f'[定时报名] 读取用户失败: {e}')
        return

    # 刷新 token
    u = _pu_refresh_token(u)

    # 执行报名（禁用 pu_core 内部的邮件，由本函数统一发送）
    from pu_core import UserDataMager as _UDM
    m = _UDM.__new__(_UDM)
    m.file_path = ''
    m.user_datas = [u]
    m._try_send_email = lambda *a, **kw: None  # 屏蔽 pu_core 内部邮件
    try:
        r = m.auto_signup_single_user(u, activity_id, join_start_time)
        ok = r.get('ok') or r.get('success')
        msg_text = r.get('msg', '')
        _pu_log(f'[定时报名] {u["userName"]} 活动{activity_id}({activity_title}): {"✅成功" if ok else "❌失败"} {msg_text}')
        # 写入报名日志
        try:
            conn2 = get_db_conn()
            with conn2:
                with conn2.cursor() as cur:
                    cur.execute(
                        'INSERT INTO pu_signup_logs (user_name, activity_id, join_start_time, status, result) VALUES (%s,%s,%s,%s,%s)',
                        (u['userName'], activity_id, join_start_time,
                         'success' if ok else 'failed', json.dumps(r, ensure_ascii=False))
                    )
                conn2.commit()
        except Exception:
            pass
        # 发邮件
        to_email = (u.get('email') or '').strip()
        if to_email:
            now_t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            subject = f'{"报名成功" if ok else "报名失败"} - {activity_title}'
            color = '#2e7d32' if ok else '#c62828'
            icon = '✅' if ok else '❌'
            label = '报名成功' if ok else '报名失败'
            extra = f'<p>{"消息" if ok else "失败原因"}：{msg_text}</p>' if msg_text else ''
            body = (f'<div style="font-family:sans-serif;max-width:520px">'
                    f'<h3 style="color:{color}">{icon} 自动托管{label}</h3>'
                    f'<p>用户：<b>{u["userName"]}</b></p>'
                    f'<p>活动：{activity_title}</p>'
                    f'<p>时间：{now_t}</p>{extra}</div>')
            threading.Thread(target=send_email,
                             args=({'enable': True, 'receiver': to_email}, subject, body),
                             daemon=True).start()
    except Exception as ex:
        _pu_log(f'[定时报名异常] {u["userName"]} 活动{activity_id}: {ex}')


def _start_pu_scheduler_loop(poll_interval=60):
    """启动 PU 自动托管轮询线程（幂等）。
    轮询时发现新活动 → 用 APScheduler DateTrigger 注册精确定时报名任务。
    已注册的任务 key 持久化到 pu_scheduled_keys 表防重复。
    """
    global _pu_scheduler_thread, _pu_scheduler_stop
    with _pu_state_lock:
        if _pu_scheduler_thread and _pu_scheduler_thread.is_alive():
            return False
        if not _pu_scheduler_stop or _pu_scheduler_stop.is_set():
            _pu_scheduler_stop = threading.Event()
        # 从数据库恢复已注册的 key 到内存
        try:
            import pymysql as _pym
            conn = get_db_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT `key` FROM pu_scheduled_keys')
                    for row in cur.fetchall():
                        _pu_scheduled_keys.add(row[0])
        except Exception:
            pass

    def _is_key_registered(key: str) -> bool:
        # 先查内存（最快，防止同一轮重复注册）
        with _pu_state_lock:
            if key in _pu_scheduled_keys:
                # job 还在 → 已注册等待触发
                parts = key.split('|')
                if len(parts) >= 3:
                    job_id = f'pu_signup_{parts[1]}_{parts[2]}'
                    if scheduler.get_job(job_id) is not None:
                        return True
                    # job 消失了，但不从内存移除——已执行过的不再重复
                return True
        # 查数据库
        try:
            import pymysql as _pym
            conn = get_db_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT 1 FROM pu_scheduled_keys WHERE `key`=%s', (key,))
                    found = cur.fetchone() is not None
            if found:
                with _pu_state_lock:
                    _pu_scheduled_keys.add(key)
            return found
        except Exception:
            return False

    def _register_key(key: str, title: str = ''):
        with _pu_state_lock:
            _pu_scheduled_keys.add(key)
        try:
            import pymysql as _pym
            conn = get_db_conn()
            with conn:
                with conn.cursor() as cur:
                    # 自动建表（如果不存在）
                    cur.execute('''CREATE TABLE IF NOT EXISTS pu_scheduled_keys (
                        `key` VARCHAR(200) PRIMARY KEY,
                        title VARCHAR(500) DEFAULT '',
                        created_at DATETIME DEFAULT NOW()
                    ) CHARACTER SET utf8mb4''')
                    cur.execute(
                        'INSERT IGNORE INTO pu_scheduled_keys (`key`, title, created_at) VALUES (%s, %s, NOW())',
                        (key, title or '')
                    )
                conn.commit()
        except Exception:
            pass

    def _loop():
        _pu_log(f'自动托管启动，轮询间隔={poll_interval}s')
        while not _pu_scheduler_stop.is_set():
            try:
                import pymysql as _pym
                conn = get_db_conn()
                with conn:
                    with conn.cursor() as cur:
                        cur.execute('SELECT id, user_name, password, token, sid, device, college, email, yunrun_username FROM pu_users WHERE auto_scheduler=1')
                        rows = cur.fetchall()
                enabled_users = [{'id': r[0], 'userName': r[1], 'password': r[2], 'token': r[3],
                                   'sid': r[4], 'device': r[5] or 'pc', 'college': r[6] or '',
                                   'email': r[7] or '', 'yunrun_username': r[8]} for r in rows]

                for pu_user in enabled_users:
                    # 轮询前先刷新 token，确保 token 有效
                    pu_user = _pu_refresh_token(pu_user)

                    from pu_core import UserDataMager as _UDM
                    mgr = _UDM.__new__(_UDM)
                    mgr.file_path = ''
                    mgr.user_datas = [pu_user]
                    try:
                        raw_list = mgr.fetch_activity_list(pu_user, limit=50)
                    except Exception as fe:
                        _pu_log(f'[获取活动失败] {pu_user.get("userName")}: {fe}')
                        continue
                    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    # 只处理报名未截止、且状态不是已结束的活动
                    SKIP_STATUS = {'已结束', '已停止报名', '报名已截止', '活动已结束'}
                    activities = [
                        a for a in (raw_list or [])
                        if (a.get('statusName') or '') not in SKIP_STATUS
                        and not (isinstance(a.get('joinEndTime'), str) and a['joinEndTime'] and a['joinEndTime'] < now_str)
                    ]
                    for a in activities:
                        # 补充详情字段（joinEndTime、joinStartTime 等列表接口可能缺失）
                        aid_raw = a.get('id') or a.get('activityId')
                        try:
                            detail = mgr.fetch_activity_detail(pu_user, aid_raw) or {}
                            for fk in ('joinEndTime', 'joinStartTime', 'categoryName', 'creatorName', 'address', 'isAudit', 'description', 'name'):
                                if not a.get(fk) and detail.get(fk):
                                    a[fk] = detail[fk]
                        except Exception:
                            pass
                        brief = mgr.extract_activity_brief(a)
                        aid = brief.get('activity_id')
                        jst = brief.get('join_start_time') or ''  # 报名开始时间
                        title = brief.get('title') or str(aid)
                        if not aid:
                            continue
                        key = f"pu|{pu_user['id']}|{aid}|{jst}"
                        if _is_key_registered(key):
                            continue
                        # 解析报名开始时间，为空或已过则立即执行
                        run_dt = datetime.now().replace(microsecond=0)
                        if jst:
                            try:
                                parsed = datetime.strptime(jst, '%Y-%m-%d %H:%M:%S')
                                if parsed > datetime.now():
                                    run_dt = parsed
                            except ValueError:
                                pass
                        # 注册 APScheduler DateTrigger 任务
                        job_id = f'pu_signup_{pu_user["id"]}_{aid}'
                        try:
                            if scheduler.get_job(job_id):
                                scheduler.remove_job(job_id)
                            scheduler.add_job(
                                _pu_do_signup,
                                trigger=DateTrigger(run_date=run_dt, timezone='Asia/Shanghai'),
                                id=job_id,
                                args=[pu_user['id'], int(aid), jst, title],
                                misfire_grace_time=30,
                                replace_existing=True,
                            )
                            _register_key(key, title)
                            _pu_log(f'[已注册定时报名] {pu_user["userName"]} 活动《{title}》 触发时间={run_dt}')
                        except Exception as se:
                            _pu_log(f'[注册任务失败] {se}')
            except Exception as ex:
                _pu_log(f'[调度器异常] {ex}')
            for _ in range(poll_interval):
                if _pu_scheduler_stop.is_set():
                    break
                import time as _t; _t.sleep(1)
        _pu_log('自动托管已停止')

    _pu_scheduler_thread = threading.Thread(target=_loop, daemon=True)
    _pu_scheduler_thread.start()
    return True


@app.route('/api/signup/scheduler/start', methods=['POST'])
def pu_api_scheduler_start():
    global _pu_scheduler_thread, _pu_scheduler_stop, _pu_scheduled_keys
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.get_json(silent=True) or {}
    poll_interval = max(3, int(data.get('poll_interval', 10)))
    if not _start_pu_scheduler_loop(poll_interval):
        return jsonify({'code': 200, 'msg': '已在运行'})
    return jsonify({'code': 200, 'msg': f'已启动，轮询间隔={poll_interval}s'})


@app.route('/api/signup/scheduler/stop', methods=['POST'])
def pu_api_scheduler_stop():
    global _pu_scheduler_stop
    if _pu_scheduler_stop:
        _pu_scheduler_stop.set()
    return jsonify({'code': 200, 'msg': '已发送停止信号'})


@app.route('/api/signup/scheduler/status', methods=['GET'])
def pu_api_scheduler_status():
    running = bool(_pu_scheduler_thread and _pu_scheduler_thread.is_alive())
    return jsonify({'code': 200, 'running': running})


@app.route('/api/signup/schedule_activity', methods=['POST'])
def pu_api_schedule_activity():
    """手动为某个活动创建定时报名任务"""
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'msg': '未登录'})
    data = request.get_json(silent=True) or {}
    activity_id = data.get('activity_id')
    join_start_time = (data.get('join_start_time') or '').strip()
    title = (data.get('title') or str(activity_id)).strip()
    if not activity_id or not join_start_time:
        return jsonify({'code': 400, 'msg': '缺少 activity_id 或 join_start_time'})
    try:
        pu_users = _pu_read_users_for(user['username'])
        if not pu_users:
            return jsonify({'code': 400, 'msg': '请先绑定口袋校园账号'})
        results = []
        for pu_user in pu_users:
            key = f"pu|{pu_user['id']}|{activity_id}|{join_start_time}"
            job_id = f'pu_signup_{pu_user["id"]}_{activity_id}'
            # 如果 job 还在等待触发，跳过
            if scheduler.get_job(job_id) is not None:
                results.append(f"{pu_user['userName']} 已在等待触发")
                continue
            # 无论 key 是否在内存/数据库，都允许手动重新注册（清除旧 key）
            with _pu_state_lock:
                _pu_scheduled_keys.discard(key)
            try:
                run_dt = datetime.strptime(join_start_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return jsonify({'code': 400, 'msg': '时间格式错误，需 YYYY-MM-DD HH:MM:SS'})
            if run_dt <= datetime.now():
                run_dt = datetime.now().replace(microsecond=0)
            job_id = f'pu_signup_{pu_user["id"]}_{activity_id}'
            try:
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
                scheduler.add_job(
                    _pu_do_signup,
                    trigger=DateTrigger(run_date=run_dt, timezone='Asia/Shanghai'),
                    id=job_id,
                    args=[pu_user['id'], int(activity_id), join_start_time, title],
                    misfire_grace_time=30,
                    replace_existing=True,
                )
                # 写入内存和数据库
                with _pu_state_lock:
                    _pu_scheduled_keys.add(key)
                try:
                    import pymysql as _pym
                    conn = get_db_conn()
                    with conn:
                        with conn.cursor() as cur:
                            cur.execute('''CREATE TABLE IF NOT EXISTS pu_scheduled_keys (
                                `key` VARCHAR(200) PRIMARY KEY,
                                title VARCHAR(500) DEFAULT '',
                                created_at DATETIME DEFAULT NOW()
                            ) CHARACTER SET utf8mb4''')
                            cur.execute('DELETE FROM pu_scheduled_keys WHERE `key`=%s', (key,))
                            cur.execute(
                                'INSERT INTO pu_scheduled_keys (`key`, title, created_at) VALUES (%s, %s, NOW())',
                                (key, title)
                            )
                        conn.commit()
                except Exception:
                    pass
                results.append(f"{pu_user['userName']} 已注册，触发时间={run_dt}")
                _pu_log(f'[手动注册] {pu_user["userName"]} 活动《{title}》 触发时间={run_dt}')
            except Exception as se:
                results.append(f"{pu_user['userName']} 注册失败: {se}")
        return jsonify({'code': 200, 'msg': '；'.join(results)})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})


if __name__ == '__main__':
    init_global_vars()
    reload_all_cron_jobs()
    scheduler.start()
    # 如果数据库里有启用自动托管的 PU 用户，自动启动调度器
    try:
        conn = _pu_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM pu_users WHERE auto_scheduler=1')
                cnt = cur.fetchone()[0]
        if cnt > 0:
            _start_pu_scheduler_loop(10)
    except Exception:
        pass
    app.run(host='0.0.0.0', port=5000, debug=False)

