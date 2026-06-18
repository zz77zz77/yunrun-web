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
        # 添加 id 自增主键
        try:
            cur.execute('ALTER TABLE users ADD COLUMN id INT AUTO_INCREMENT PRIMARY KEY FIRST')
            print('id 列已添加')
        except Exception as e:
            print(f'id 列: {e}')
        # 添加 token 字段（存储运动平台 token）
        try:
            cur.execute('ALTER TABLE users ADD COLUMN token TEXT DEFAULT NULL')
            print('token 列已添加')
        except Exception as e:
            print(f'token 列: {e}')
        # 添加 token 相关字段
        try:
            cur.execute('ALTER TABLE users ADD COLUMN device_id VARCHAR(64) DEFAULT NULL')
            print('device_id 列已添加')
        except Exception as e:
            print(f'device_id 列: {e}')
        try:
            cur.execute('ALTER TABLE users ADD COLUMN device_name VARCHAR(128) DEFAULT NULL')
            print('device_name 列已添加')
        except Exception as e:
            print(f'device_name 列: {e}')
        try:
            cur.execute('ALTER TABLE users ADD COLUMN school_url VARCHAR(256) DEFAULT NULL')
            print('school_url 列已添加')
        except Exception as e:
            print(f'school_url 列: {e}')
    conn.commit()
print('users 表字段初始化完成')
