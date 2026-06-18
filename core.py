# coding:utf-8
import os
import random
import time
import requests
import json
import gzip
import hashlib
from base64 import b64encode, b64decode
from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT
from datetime import datetime
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INIT_DATA = {
    "yun_host": "https://sports.yzhiee.com:8085",
    "publickey": "BDdKFsuBf51UObke1pEgfER17biBg/5r8slqE4s8oOa8lVesWgIUxsRc+AmZ72GcuJ56f7avnyJe3CJY4n00LU4=",
    "privatekey": "P3s0+rMuY4Nt5cUWuOCjMhDzVNdom+W0RvdV6ngM+/E=",
    "cipherkeyencrypted": "BGfbsG9EkXz5KeCva8E0MisBeS6bhBEDId3VXeIuBoiBMZU0Mosv7PqKsvqxZ3PjkUlsjzh09Se629SWW45XP4TIUeXoLpYzgk5fAMbg0VNVnXuLH9xVzdHAeM+1qJrgvwwkwio85/DnrP1aArvVQrw3N4xd5tugqQ==",
    "cipherkey": "JXhWGZjmhhXN+nt8nLpNxA==",
    "md5key": "pie0hDSfMRINRXc7s1UIXfkE",
    "platform": "android",
    "app_edition": "3.5.10",
    "school_login_url": "appLogin",
    "school_id": 195
}

CipherKeyEncrypted = INIT_DATA['cipherkeyencrypted']
default_key = INIT_DATA['cipherkey']
md5key = INIT_DATA['md5key']
platform = INIT_DATA['platform']
app_edition = INIT_DATA['app_edition']
school_login_url = INIT_DATA['school_login_url']

device_list = []  # 兼容旧引用，运行时由 get_device_list() 填充


def get_device_list():
    """从数据库获取设备列表"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=os.environ.get('MYSQL_HOST', 'yunrun-mysql'), port=int(os.environ.get('MYSQL_PORT', '3306')),
            user=os.environ.get('MYSQL_USER', 'root'), password=os.environ.get('MYSQL_PASSWORD', 'yunrun2026'),
            database=os.environ.get('MYSQL_DATABASE', 'yunrun'), charset='utf8mb4', connect_timeout=5
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT name FROM devices ORDER BY id')
                return [r[0] for r in cur.fetchall()]
    except Exception:
        # 降级到内置列表
        return [
            "Xiaomi 14", "Xiaomi 13 Pro", "Redmi K70",
            "OPPO Find X7 Ultra", "vivo X100 Pro",
            "Huawei Mate 60 Pro", "iPhone 15 Pro Max", "iPhone 15 Pro"
        ]


def md5_encryption(data):
    m = hashlib.md5()
    m.update(data.encode('utf-8'))
    return m.hexdigest()


def encrypt_sm4(value, SM_KEY, isBytes=False):
    crypt_sm4 = CryptSM4()
    crypt_sm4.set_key(SM_KEY, SM4_ENCRYPT)
    if not isBytes:
        encrypt_value = b64encode(crypt_sm4.crypt_ecb(value.encode("utf-8")))
    else:
        encrypt_value = b64encode(crypt_sm4.crypt_ecb(value))
    return encrypt_value.decode()


def decrypt_sm4(value, SM_KEY):
    crypt_sm4 = CryptSM4()
    crypt_sm4.set_key(SM_KEY, SM4_DECRYPT)
    return crypt_sm4.crypt_ecb(b64decode(value))


def compare_datetime_strings(time1_str, time2_str):
    try:
        fmt = "%Y-%m-%d %H:%M:%S" if len(time1_str) > 10 else "%Y-%m-%d"
        fmt2 = "%Y-%m-%d %H:%M:%S" if len(time2_str) > 10 else "%Y-%m-%d"
        return datetime.strptime(time1_str, fmt) >= datetime.strptime(time2_str, fmt2)
    except:
        return time1_str >= time2_str


def connect_mysql():
    try:
        url = 'https://www.zgymc.top:8081/api/init.php'
        response = requests.post(url=url, timeout=10, verify=False)
        return 1, response.json()
    except:
        return (0,)


def init_global_vars():
    global CipherKeyEncrypted, default_key, md5key, platform, app_edition, school_login_url
    result = connect_mysql()
    if result[0] == 0:
        return False, {}
    init_data = result[1]
    CipherKeyEncrypted = init_data.get('cipherkeyencrypted', CipherKeyEncrypted)
    default_key = init_data.get('cipherkey', default_key)
    md5key = init_data.get('md5key', md5key)
    platform = init_data.get('platform', platform)
    app_edition = init_data.get('app_edition', app_edition)
    school_login_url = init_data.get('school_login_url', school_login_url)
    # 从 sys_config 表读取可覆盖的配置（优先级最高）
    try:
        db_edition = get_sys_config_value('app_edition')
        if db_edition:
            app_edition = db_edition
    except Exception:
        pass
    return True, init_data


def get_sys_config_value(key):
    """从 sys_config 表读取单个配置值"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=os.environ.get('MYSQL_HOST', 'yunrun-mysql'), port=3306, user='root', password=os.environ.get('MYSQL_PASSWORD', 'yunrun2026'),
            database='yunrun', charset='utf8mb4', connect_timeout=5
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT `value` FROM sys_config WHERE `key`=%s', (key,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None


def getsign(utc, uuid):
    sb = f"platform={platform}&utc={utc}&uuid={uuid}&appsecret={md5key}"
    m = hashlib.md5()
    m.update(sb.encode("utf-8"))
    return m.hexdigest()


def default_post(router, data, token, device_id, device_name, school_url, isBytes=False):
    url = school_url + router
    my_utc = str(int(time.time()))
    sign = getsign(my_utc, device_id)
    headers = {
        'token': token,
        'isApp': 'app',
        'deviceId': device_id,
        'deviceName': str(device_name),
        'version': app_edition,
        'platform': 'android',
        'Content-Type': 'application/json; charset=utf-8',
        'Connection': 'Keep-Alive',
        'Accept-Encoding': 'gzip',
        'User-Agent': 'okhttp/3.12.0',
        'utc': my_utc,
        'uuid': device_id,
        'sign': sign
    }
    data_json = {
        "cipherKey": CipherKeyEncrypted,
        "content": encrypt_sm4(data, b64decode(default_key), isBytes=isBytes)
    }
    req = requests.post(url=url, data=json.dumps(data_json), headers=headers)
    try:
        return decrypt_sm4(req.text, b64decode(default_key)).decode()
    except:
        return req.text


def get_school_list():
    utc = str(int(time.time()))
    uuid_temp = "2211725972932675"
    sign_data = f'platform=android&utc={utc}&uuid={uuid_temp}&appsecret={md5key}'
    sign = md5_encryption(sign_data)
    url = "http://sports.aiyyd.com:9001/api/app/schoolList"
    headers = {
        "isApp": "app", "deviceId": uuid_temp, "deviceName": 'Xiaomi',
        "version": app_edition, "platform": platform, "uuid": uuid_temp,
        "utc": utc, "sign": sign,
        "Content-Type": "application/json; charset=utf-8",
        "Connection": "Keep-Alive", "Accept-Encoding": "gzip",
        "User-Agent": "okhttp/3.12.0"
    }
    data_json = {
        "cipherKey": CipherKeyEncrypted,
        "content": encrypt_sm4("", b64decode(default_key))
    }
    req = requests.post(url=url, data=json.dumps(data_json), headers=headers)
    info = json.loads(decrypt_sm4(req.text, b64decode(default_key)).decode())
    if info.get('code') != 200:
        return []
    return info.get('data', [])


def do_login(username, password, school_name, device_name):
    device_id = str(random.randint(1000000000000000, 9999999999999999))
    schools = get_school_list()
    school_url = None
    sc_id = None
    for s in schools:
        if s['schoolName'] == school_name:
            school_url = s['schoolUrl']
            sc_id = s['schoolId']
            break
    if not school_url:
        return None, "未找到该学校"

    utc = int(time.time())
    encrypt_data = f'{{"password":"{password}","schoolId":"{sc_id}","userName":"{username}","type":"1"}}'
    sign_data = f'platform=android&utc={utc}&uuid={device_id}&appsecret={md5key}'
    sign = md5_encryption(sign_data)
    content = encrypt_sm4(encrypt_data, b64decode(default_key))
    headers = {
        "token": "", "isApp": "app", "deviceId": device_id,
        "deviceName": device_name, "version": app_edition, "platform": platform,
        "uuid": device_id, "utc": str(utc), "sign": sign,
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Encoding": "gzip", "User-Agent": "okhttp/3.12.0"
    }
    data = {"cipherKey": CipherKeyEncrypted, "content": content}
    url = school_url + '/login/' + school_login_url
    response = requests.post(url, headers=headers, json=data)
    if "{" in response.text:
        dec = response.json()
    else:
        dec = json.loads(decrypt_sm4(response.text, b64decode(default_key)).decode())
    if dec.get('code') != 200:
        return None, dec.get('msg', '登录失败')

    token = dec['data']['token']
    student_info = get_student_info(token, device_id, device_name, school_url)
    member_info = get_member_info(username, password)
    return {
        'token': token, 'device_id': device_id, 'device_name': device_name,
        'school_url': school_url, 'school_name': school_name,
        'username': username, 'password': password,
        'student_info': student_info,
        'user_time': member_info.get('date'), 'now_time': member_info.get('now_time')
    }, None


def get_student_info(token, device_id, device_name, school_url):
    url = school_url + "/login/getStudentInfo"
    utc = int(time.time())
    sign = md5_encryption(f'platform=android&utc={utc}&uuid={device_id}&appsecret={md5key}')
    headers = {
        "token": token, "isApp": "app", "deviceId": device_id,
        "deviceName": device_name, "version": app_edition, "platform": platform,
        "uuid": device_id, "utc": str(utc), "sign": sign,
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Encoding": "gzip", "User-Agent": "okhttp/3.12.0"
    }
    data_json = {"cipherKey": CipherKeyEncrypted, "content": encrypt_sm4("", b64decode(default_key))}
    response = requests.post(url, headers=headers, json=data_json)
    if "{" in response.text:
        return response.json()
    return json.loads(decrypt_sm4(response.text, b64decode(default_key)).decode())


def get_member_info(username, password):
    """直连 MySQL 查询用户会员信息，对应 userinfo.php 逻辑"""
    try:
        import pymysql
        from datetime import datetime as _dt
        conn = pymysql.connect(
            host=os.environ.get('MYSQL_HOST', 'yunrun-mysql'), port=int(os.environ.get('MYSQL_PORT', '3306')),
            user=os.environ.get('MYSQL_USER', 'root'), password=os.environ.get('MYSQL_PASSWORD', 'yunrun2026'),
            database=os.environ.get('MYSQL_DATABASE', 'yunrun'), charset='utf8mb4',
            connect_timeout=5
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT `username`, `key`, `date` FROM `users` WHERE `username`=%s AND `key`=%s LIMIT 1",
                    (username, password)
                )
                row = cur.fetchone()
        if row:
            return {
                'username': row[0],
                'key': row[1],
                'date': str(row[2]) if row[2] else '',
                'now_time': _dt.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        return {}
    except Exception:
        return {}


def get_term_list(token, device_id, device_name, school_url):
    resp = default_post("/run/listXnYearXqByStudentId", "", token, device_id, device_name, school_url)
    data = json.loads(resp)
    if data.get('code') != 200:
        return []
    return data.get('data', [])


def get_run_records(table_name, token, device_id, device_name, school_url):
    resp = default_post("/run/crsReocordInfoList",
                        json.dumps({"tableName": table_name}),
                        token, device_id, device_name, school_url)
    data = json.loads(resp)
    if data.get('code') != 200:
        return [], []
    all_runs = []
    month_groups = []
    for month_data in data.get('data', {}).get('rank', []):
        month_name = month_data.get('month', '')
        rank_list = month_data.get('rankList', [])
        if rank_list:
            month_groups.append({'month': month_name, 'runs': rank_list})
            all_runs.extend(rank_list)
    return all_runs, month_groups


def get_run_detail(run_id, table_name, token, device_id, device_name, school_url):
    resp = default_post("/run/crsReocordInfo",
                        json.dumps({"id": run_id, "tableName": table_name}),
                        token, device_id, device_name, school_url)
    key = b64decode(default_key)
    text = gzip.decompress(decrypt_sm4(resp, key)).decode()
    data = json.loads(text)
    if data.get('code') != 200:
        return None, data.get('msg', '获取失败')
    return data.get('data'), None


def do_run_task(task_file_path, session_data, log_callback=None, point_callback=None, stop_event=None):
    """执行跑步任务，log_callback(msg) 用于记录日志，point_callback(point, current, total) 推送轨迹点
    stop_event: threading.Event，置位后中止任务"""
    token = session_data['token']
    device_id = session_data['device_id']
    device_name = session_data['device_name']
    school_url = session_data['school_url']

    def log(msg):
        if log_callback:
            log_callback(msg)

    # 获取跑步信息
    resp = default_post("/run/getHomeRunInfo", "", token, device_id, device_name, school_url)
    try:
        home_resp = json.loads(resp)
    except Exception as e:
        log(f"❌ 解析跑步信息失败: {e}, 原始响应: {resp[:200]}")
        return False
    if home_resp.get('code') != 200:
        log(f"❌ 获取跑步信息失败: {home_resp.get('msg', '未知错误')} (code={home_resp.get('code')})")
        return False
    cralist = home_resp.get('data', {}).get('cralist', [])
    if not cralist:
        log("❌ 没有可用的跑步任务配置")
        return False
    home_data = cralist[0]

    ra_type = home_data['raType']
    ra_id = home_data['id']
    school_id = home_data['schoolId']
    ra_run_area = home_data['raRunArea']
    ra_cadence_min = home_data['raCadenceMin'] + 30
    ra_cadence_max = home_data['raCadenceMax'] - 150
    strides = 0.8

    # 开始跑步
    start_data = {'raRunArea': ra_run_area, 'raType': ra_type, 'raId': ra_id}
    start_resp = json.loads(default_post('/run/start', json.dumps(start_data),
                                         token, device_id, device_name, school_url))
    if start_resp.get('code') != 200:
        log(f"❌ 创建任务失败: {start_resp.get('msg', '未知错误')} (code={start_resp.get('code')})")
        return False
    start_data_body = start_resp.get('data', {})
    if not start_data_body:
        log("❌ 创建任务响应数据为空")
        return False
    record_start_time = start_data_body['recordStartTime']
    crs_run_record_id = start_data_body['id']
    user_name = start_data_body['studentId']
    log(f"✅ 任务创建成功 ID:{crs_run_record_id}")

    # 读取轨迹文件
    with open(task_file_path, 'r', encoding='utf-8') as f:
        task_map = json.loads(f.read())

    task_data = task_map.get('data', {})
    if not task_data or not task_data.get('pointsList'):
        log("❌ 任务文件格式错误或无轨迹点")
        return False

    points_list = task_data['pointsList']
    total = len(points_list)
    log(f"📍 轨迹点: {total}, 目标距离: {task_data.get('recordMileage', '?')} km")

    points = []
    count = 0
    segment = 0
    for idx, point in enumerate(points_list):
        point_changed = {
            'point': point['point'], 'runStatus': '1', 'speed': point['speed'],
            'isFence': 'Y', 'isMock': False,
            'runMileage': point['runMileage'], 'runTime': point['runTime'],
            'ts': str(int(time.time()))
        }
        points.append(point_changed)
        count += 1
        # 每个点都推送给前端地图
        if point_callback:
            point_callback(point['point'], idx + 1, total)
        # 检查停止信号
        if stop_event and stop_event.is_set():
            log("⏹ 用户已停止跑步")
            return False
        if count == 10:
            segment += 1
            seg_data = {
                "StepNumber": int(float(points[-1]['runMileage']) - float(points[0]['runMileage'])) / strides,
                'a': 0, 'b': None, 'c': None,
                "mileage": float(points[-1]['runMileage']) - float(points[0]['runMileage']),
                "orientationNum": 0,
                "runSteps": random.uniform(ra_cadence_min, ra_cadence_max),
                'cardPointList': points, "simulateNum": 0,
                "time": float(points[-1]['runTime']) - float(points[0]['runTime']),
                'crsRunRecordId': crs_run_record_id,
                "speeds": task_data['recodePace'],
                'schoolId': school_id, "strides": strides, 'userName': user_name
            }
            default_post("/run/splitPointCheating",
                         gzip.compress(json.dumps(seg_data).encode("utf-8")),
                         token, device_id, device_name, school_url, isBytes=True)
            sleep_time = task_data['duration'] / total * 10
            log(f"📤 第{segment}段上传完成")
            # 可中断的 sleep
            if stop_event:
                stop_event.wait(timeout=sleep_time)
                if stop_event.is_set():
                    log("⏹ 用户已停止跑步")
                    return False
            else:
                time.sleep(sleep_time)
            count = 0
            points = []

    if count > 0:
        seg_data = {
            "StepNumber": int(float(points[-1]['runMileage']) - float(points[0]['runMileage'])) / strides,
            'a': 0, 'b': None, 'c': None,
            "mileage": float(points[-1]['runMileage']) - float(points[0]['runMileage']),
            "orientationNum": 0,
            "runSteps": random.uniform(ra_cadence_min, ra_cadence_max),
            'cardPointList': points, "simulateNum": 0,
            "time": float(points[-1]['runTime']) - float(points[0]['runTime']),
            'crsRunRecordId': crs_run_record_id,
            "speeds": task_data['recodePace'],
            'schoolId': school_id, "strides": strides, 'userName': user_name
        }
        default_post("/run/splitPointCheating",
                     gzip.compress(json.dumps(seg_data).encode("utf-8")),
                     token, device_id, device_name, school_url, isBytes=True)
        log(f"📤 最后一段上传完成")

    # 完成跑步
    finish_data = {
        'recordMileage': task_data['recordMileage'],
        'recodeCadence': task_data['recodeCadence'],
        'recodePace': task_data['recodePace'],
        'deviceName': device_name, 'sysEdition': '15', 'appEdition': app_edition,
        'raIsStartPoint': 'Y', 'raIsEndPoint': 'Y', 'raRunArea': ra_run_area,
        'recodeDislikes': str(task_data['recodeDislikes']),
        'raId': str(ra_id), 'raType': ra_type, 'id': str(crs_run_record_id),
        'duration': task_data['duration'],
        'recordStartTime': record_start_time,
        'manageList': task_data['manageList'], 'remake': '1'
    }
    finish_resp = json.loads(default_post("/run/finish", json.dumps(finish_data),
                                          token, device_id, device_name, school_url))
    if finish_resp.get('code') == 200:
        log(f"🎉 跑步完成! 距离:{finish_data['recordMileage']}km")
        return True
    else:
        log(f"❌ 完成失败: {finish_resp.get('msg')}")
        return False


# ==================== 本地数据库操作 ====================
DB_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'yunrun-mysql'),
    'port': 3306,
    'user': 'root',
    'password': os.environ.get('MYSQL_PASSWORD', 'yunrun2026'),
    'database': 'yunrun',
    'charset': 'utf8mb4',
    'connect_timeout': 5,
}


def get_db_connection():
    """获取 MySQL 连接（需要 PyMySQL）"""
    import pymysql
    return pymysql.connect(**DB_CONFIG)


def register_user(username, password, school_name):
    """
    本地注册用户，直连 MySQL。
    返回 (ok: bool, msg: str, http_code: int)
    """
    if not username or not password:
        return False, 'username 与 password 不能为空', 400
    if len(password) < 6:
        return False, '密码长度至少为6位', 400

    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                # 检查用户名是否已存在
                cur.execute('SELECT 1 FROM `users` WHERE `username` = %s LIMIT 1', (username,))
                if cur.fetchone():
                    return False, '用户名已存在', 409
                # 插入新用户（date 字段存注册时间，key 字段存密码，与 PHP 保持一致）
                cur.execute(
                    'INSERT INTO `users` (`username`, `key`, `date`, `school_name`) VALUES (%s, %s, NOW(), %s)',
                    (username, password, school_name)
                )
            conn.commit()
        return True, '注册成功', 200
    except Exception as e:
        return False, f'数据库错误: {str(e)}', 500
