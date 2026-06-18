# coding: utf-8
import os
import pymysql

conn = pymysql.connect(
    host=os.environ.get('MYSQL_HOST', 'yunrun-mysql'), port=3306,
    user='root', password=os.environ.get('MYSQL_PASSWORD', 'yunrun2026'),
    database='yunrun', charset='utf8mb4'
)
with conn:
    with conn.cursor() as cur:
        # 报名用户表
        cur.execute('''CREATE TABLE IF NOT EXISTS pu_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_name VARCHAR(64) NOT NULL,
            password VARCHAR(128) NOT NULL,
            token TEXT DEFAULT NULL,
            sid INT DEFAULT NULL,
            device VARCHAR(32) DEFAULT 'pc',
            college VARCHAR(128) DEFAULT NULL,
            email VARCHAR(128) DEFAULT NULL,
            created_at DATETIME DEFAULT NOW(),
            UNIQUE KEY uk_username_sid (user_name, sid)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

        # 报名任务记录表
        cur.execute('''CREATE TABLE IF NOT EXISTS pu_signup_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_name VARCHAR(64),
            activity_id INT,
            activity_title VARCHAR(256),
            join_start_time VARCHAR(32),
            status VARCHAR(32),
            result TEXT,
            created_at DATETIME DEFAULT NOW()
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

        # 自动托管配置表
        cur.execute('''CREATE TABLE IF NOT EXISTS pu_scheduler_config (
            id INT AUTO_INCREMENT PRIMARY KEY,
            `key` VARCHAR(64) NOT NULL UNIQUE,
            `value` VARCHAR(256) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        cur.execute("INSERT IGNORE INTO pu_scheduler_config (`key`,`value`) VALUES ('poll_interval','10')")
        cur.execute("INSERT IGNORE INTO pu_scheduler_config (`key`,`value`) VALUES ('enabled','0')")
    conn.commit()
print('pu_users / pu_signup_logs / pu_scheduler_config 表初始化完成')
