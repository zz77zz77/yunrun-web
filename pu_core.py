import os
import json
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from utils.pu_sign import generate_random_echo, current_timestamp_str, generate_x_sign
from utils.tools import make_success_email, make_fail_email, send_email


HEADERS_LOGIN = {
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}


class UserDataMager:
    """GUI + 自动报名核心逻辑（单一来源）"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.user_datas = self.read_user_data() or []

    # -----------------------
    # persistence
    # -----------------------
    def read_user_data(self):
        if not os.path.exists(self.file_path):
            return None
        with open(self.file_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return None

    def write_user_data(self) -> None:
        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(self.user_datas, file, indent=4, ensure_ascii=False)

    # -----------------------
    # schools (for GUI search)
    # -----------------------
    def fetch_school_list(self) -> list:
        resp = requests.get("https://pocketuni.net/index.php?app=api&mod=Sitelist&act=getSchools", timeout=10)
        resp.raise_for_status()
        return resp.json() or []

    def search_schools(self, keyword: str, limit: int = 30) -> list:
        keyword = (keyword or "").strip()
        schools = self.fetch_school_list()
        if not keyword:
            return schools[:limit]
        return [s for s in schools if keyword in s.get("name", "")][:limit]

    # -----------------------
    # user management (GUI)
    # -----------------------
    def add_user_from_gui(self, school_name: str, user_name: str, password: str, email: str = "") -> dict:
        if not school_name or not user_name or not password:
            raise ValueError("学校、账号、密码不能为空")

        schools = self.fetch_school_list()
        exact = [s for s in schools if school_name == s.get("name", "")]
        choice_school = exact or [s for s in schools if school_name in s.get("name", "")]
        if not choice_school:
            raise ValueError("未找到匹配学校")
        if len(choice_school) > 1:
            raise ValueError("匹配到多个学校，请从检索列表点选学校")

        sid = choice_school[0].get("go_id")
        payload = {"userName": user_name, "password": password, "sid": int(sid), "device": "pc"}
        resp = requests.post("https://apis.pocketuni.net/uc/user/login", headers=HEADERS_LOGIN, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        if data.get("code") != 0:
            raise ValueError(f"登录失败：{data.get('message', '')}")

        token = data.get("data", {}).get("token")
        uid = data.get("data", {}).get("baseUserInfo", {}).get("id", "")
        user = {
            "userName": user_name,
            "password": password,
            "token": token,
            "uid": uid,
            "sid": sid,
            "device": "pc",
            "college": choice_school[0].get("name", school_name),
            "email": email or "",
        }
        self.user_datas.append(user)
        self.write_user_data()
        return user

    # -----------------------
    # sign-up core
    # -----------------------
    def _build_activity_headers(self, token: str, sid=None) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
        headers["Authorization"] = f"Bearer {token}:{sid}" if sid else f"Bearer {token}"
        return headers

    def _attach_x_sign(self, headers: dict) -> dict:
        headers["X-Sign"] = generate_x_sign(
            echo=generate_random_echo(),
            timestamp=current_timestamp_str(),
            client="web",
        )
        return headers

    def fetch_activity_list(self, user: dict, limit: int = 50, status: int = 0) -> list:
        """获取活动列表，status: 0=全部, 1=未开始, 2=进行中, 3=已结束"""
        token = user.get("token")
        if not token:
            raise ValueError("token 为空")
        headers = self._build_activity_headers(token, user.get("sid"))
        all_activities = []
        page = 1
        while True:
            payload = {"sort": 0, "page": page, "limit": int(limit), "puType": 0, "status": status}
            resp = requests.post("https://apis.pocketuni.net/apis/activity/list", headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
            resp_data = (resp.json() or {}).get("data", {})
            items = resp_data.get("list") or []
            all_activities.extend(items)
            total_pages = (resp_data.get("pageInfo") or {}).get("total", 1)
            if page >= total_pages or not items:
                break
            page += 1
        return all_activities

    def fetch_activity_detail(self, user: dict, activity_id) -> dict:
        """获取活动详情，POST activity/info，返回 data.baseInfo 完整字段"""
        token = user.get("token")
        if not token:
            return {}
        headers = self._build_activity_headers(token, user.get("sid"))
        try:
            resp = requests.post(
                "https://apis.pocketuni.net/apis/activity/info",
                headers=headers,
                json={"id": int(activity_id)},
                timeout=10,
            )
            resp.raise_for_status()
            return (resp.json() or {}).get("data", {}).get("baseInfo") or {}
        except Exception:
            return {}

    def filter_future_activities(self, activities: list, now_str: str = None) -> list:
        now_str = now_str or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return [a for a in (activities or []) if isinstance(a.get("joinStartTime"), str) and a["joinStartTime"] >= now_str]

    def extract_activity_brief(self, activity: dict) -> dict:
        allow = activity.get("allowUserCount", 0) or 0
        joined = activity.get("joinUserCount", 0) or 0
        desc = activity.get("description", "") or ""
        # 限制院系可能是列表或字符串
        colleges = activity.get("allowCollege") or activity.get("restrictColleges") or activity.get("colleges") or []
        if isinstance(colleges, list):
            colleges_str = "、".join([c.get("name", "") if isinstance(c, dict) else str(c) for c in colleges])
        else:
            colleges_str = str(colleges)
        # 限制年级
        years = activity.get("allowYear") or []
        if isinstance(years, list):
            years_str = "、".join([y.get("name", "") if isinstance(y, dict) else str(y) for y in years])
        else:
            years_str = str(years)
        return {
            "activity_id": activity.get("id") or activity.get("activityId") or activity.get("activity_id"),
            "title": activity.get("name") or activity.get("title") or activity.get("activityTitle") or "未命名活动",
            "logo": activity.get("logo") or "",
            "category": activity.get("categoryName") or "",
            "creator": activity.get("creatorName") or "",
            "address": activity.get("address") or "",
            "credit": activity.get("credit"),
            "pu_amount": activity.get("puAmount", 0),
            "allow_count": allow,
            "join_count": joined,
            "sign_in_count": activity.get("signInUserCount", 0),
            "sign_out_count": activity.get("signOutUserCount", 0),
            "remain_count": allow - joined,
            "status": activity.get("statusName") or "",
            "join_start_time": activity.get("joinStartTime") or "",
            "join_end_time": activity.get("joinEndTime") or "",
            "start_time": activity.get("startTime") or "",
            "end_time": activity.get("endTime") or "",
            "sign_start_time": activity.get("signStartTime") or "",
            "sign_out_start_time": activity.get("signOutStartTime") or "",
            "is_audit": bool(activity.get("isAudit")),
            "sign_type": activity.get("signType", 0),
            "need_sign_out": bool(activity.get("needSignOut")),
            "join_type": activity.get("joinType", 0),
            "allow_user_type": activity.get("allowUserType", 0),
            "contact": activity.get("contact") or "",
            "contact_phone": activity.get("contactPhone") or "",
            "teacher": activity.get("teacher") or "",
            "position": activity.get("position") or "",
            "tags": activity.get("tags") or "",
            "max_minutes": activity.get("maxMinutes", -1),
            "description": (desc[:100] + "...") if len(desc) > 100 else desc,
            "restrict_colleges": colleges_str,
            "restrict_years": years_str,
            "logo": activity.get("logo") or "",
        }

    def fetch_my_activities(self, user: dict, act_type: int = 1, page: int = 1, limit: int = 20) -> dict:
        """获取我的活动记录。type: 1=已报名, 2=已完成, 3=已评价"""
        token = user.get("token")
        if not token:
            return {"list": [], "pageInfo": {}}
        headers = self._build_activity_headers(token, user.get("sid"))
        try:
            resp = requests.post(
                "https://apis.pocketuni.net/apis/activity/myList",
                headers=headers,
                json={"type": act_type, "page": page, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data", {})
            return {"list": data.get("list") or [], "pageInfo": data.get("pageInfo") or {}}
        except Exception:
            return {"list": [], "pageInfo": {}}

    def fetch_qrcode(self, user: dict) -> dict:
        """获取用户个人二维码（从 API 获取）。返回 {"qrcodeId": "...", "base64": "..."} """
        token = user.get("token")
        sid = user.get("sid")
        if not token or not sid:
            return {}
        headers = self._build_activity_headers(token, sid)
        try:
            resp = requests.get(
                f"https://apis.pocketuni.net/uc/user/qrcode?sid={sid}",
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data", {})
            return {
                "qrcodeId": data.get("qrcodeId", ""),
                "base64": data.get("url", ""),
            }
        except Exception:
            return {}

    def generate_sign_qrcode(self, user: dict) -> dict:
        """本地生成签到用实时二维码（每30秒刷新）。
        原理: xyhui://user/{uid}/{timestamp}/{username} -> DES加密 -> 二维码
        返回 {"base64": "iVBOR...", "uid": ..., "username": ..., "timestamp": ...}
        """
        import io
        import base64
        from Crypto.Cipher import DES
        from Crypto.Util.Padding import pad
        import qrcode as qr_lib

        uid = user.get("uid") or user.get("id")
        username = user.get("userName", "")
        if not uid:
            return {}

        # 生成明文
        ts = int(time.time() * 1000)
        plaintext = f"xyhui://user/{uid}/{ts}/{username}"

        # DES 加密 (ECB, PKCS7, key前8字节)
        des_key = b"TG123!@#qazDES*&^956367encode7788TR"[:8]
        cipher = DES.new(des_key, DES.MODE_ECB)
        ct = cipher.encrypt(pad(plaintext.encode("utf-8"), DES.block_size))
        encrypted = base64.b64encode(ct).decode("ascii")

        # 生成二维码图片
        img = qr_lib.make(encrypted, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        return {"base64": b64, "uid": uid, "username": username, "timestamp": ts}

    def fetch_server_time(self) -> int:
        """获取口袋校园服务器时间戳，用于精确对时"""
        try:
            resp = requests.get(
                "https://apis.pocketuni.net/apis/system/time",
                headers={"User-Agent": "client:Android version:7.1.90"},
                timeout=5,
            )
            resp.raise_for_status()
            return (resp.json() or {}).get("data", {}).get("timestamp", 0)
        except Exception:
            return 0

    def _try_send_email(self, user: dict, activity_id: int, ok: bool, activity: dict = None, msg: str = "") -> None:
        to_email = (user.get("email") or "").strip()
        if not to_email:
            return
        content = make_success_email(str(activity_id), user, activity, msg) if ok else make_fail_email(str(activity_id), user, activity, msg)
        send_email(content, to_email)

    def _wait_until_target(self, target_ts: float) -> None:
        while True:
            left = target_ts - time.time()
            if left <= 0:
                return
            if left > 0.2:
                time.sleep(left - 0.1)
            elif left > 0.01:
                time.sleep(0.005)

    def _signup_worker(self, user: dict, activity_id: int, start_event: threading.Event, target_ts: float, join_url: str, common_payload: dict) -> dict:
        username = user.get("userName", "unknown")
        token = user.get("token")
        if not token:
            return {"userName": username, "ok": False, "msg": "token 为空"}
        headers = self._attach_x_sign(self._build_activity_headers(token, user.get("sid")))
        payload = dict(common_payload or {})
        payload["activityId"] = activity_id
        start_event.wait()
        self._wait_until_target(target_ts)
        try:
            resp = requests.post(join_url, headers=headers, json=payload, timeout=10)
            data = resp.json() if resp.content else {}
            code = data.get("code")
            ok = (resp.status_code == 200 and code in (0, "0", None))
            self._try_send_email(user, activity_id, ok, msg=data.get("message", ""))
            return {"userName": username, "ok": ok, "http_status": resp.status_code, "code": code, "msg": data.get("message", "")}
        except Exception as e:
            return {"userName": username, "ok": False, "msg": str(e)}

    def auto_signup_multithread(self, activity_id: int, join_start_time: str, join_url: str = "https://apis.pocketuni.net/apis/activity/join", common_payload: dict = None, max_workers: int = None) -> list:
        if not self.user_datas:
            return []
        max_workers = max_workers or len(self.user_datas)
        target_ts = datetime.strptime(join_start_time, "%Y-%m-%d %H:%M:%S").timestamp()
        if target_ts <= time.time():
            target_ts = time.time()
        start_event = threading.Event()
        results, futures = [], []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for user in self.user_datas:
                futures.append(executor.submit(self._signup_worker, user, activity_id, start_event, target_ts, join_url, common_payload or {}))
            start_event.set()
            for f in as_completed(futures):
                results.append(f.result())
        return results

    def auto_signup_single_user(self, user: dict, activity_id: int, join_start_time: str) -> dict:
        target_ts = datetime.strptime(join_start_time, "%Y-%m-%d %H:%M:%S").timestamp()
        if target_ts > time.time():
            self._wait_until_target(target_ts)
        token = user.get("token")
        if not token:
            return {"userName": user.get("userName", "unknown"), "ok": False, "msg": "token 为空"}
        headers = self._attach_x_sign(self._build_activity_headers(token, user.get("sid")))
        try:
            resp = requests.post("https://apis.pocketuni.net/apis/activity/join", headers=headers, json={"activityId": int(activity_id)}, timeout=10)
            data = resp.json() if resp.content else {}
            ok = (resp.status_code == 200 and data.get("code") in (0, "0", None))
            self._try_send_email(user, int(activity_id), ok, msg=data.get("message", ""))
            return {"userName": user.get("userName", "unknown"), "ok": ok, "code": data.get("code"), "msg": data.get("message", "")}
        except Exception as e:
            return {"userName": user.get("userName", "unknown"), "ok": False, "msg": str(e)}

    # -----------------------
    # user modify/delete (GUI)
    # -----------------------
    def update_user(self, user_index: int, *, email: str | None = None, password: str | None = None) -> dict:
        """
        修改用户信息：
        - email：直接写回
        - password：如果不为空则重新登录刷新 token，然后写回 password/token
        """
        if user_index < 0 or user_index >= len(self.user_datas):
            raise ValueError("user_index 无效")

        user = self.user_datas[user_index]
        user_changed = False

        if email is not None:
            user["email"] = email
            user_changed = True

        if password is not None and str(password).strip() != "":
            user_name = user.get("userName")
            sid = user.get("sid")
            if not user_name or not sid:
                raise ValueError("用户缺少 userName 或 sid，无法刷新 token")

            payload = {
                "userName": user_name,
                "password": password,
                "sid": int(sid),
                "device": "pc",
            }
            resp = requests.post(
                "https://apis.pocketuni.net/uc/user/login",
                headers=HEADERS_LOGIN,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            if data.get("code") != 0:
                raise ValueError(f"登录失败：{data.get('message', '')}")
            token = data.get("data", {}).get("token")
            if not token:
                raise ValueError("登录成功但未返回 token")

            user["password"] = password
            user["token"] = token
            user_changed = True

        if user_changed:
            self.write_user_data()
        return user

    def delete_user(self, user_index: int) -> None:
        if user_index < 0 or user_index >= len(self.user_datas):
            raise ValueError("user_index 无效")
        self.user_datas.pop(user_index)
        self.write_user_data()

