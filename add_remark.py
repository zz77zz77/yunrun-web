import os
import pymysql
conn = pymysql.connect(host=os.environ.get('MYSQL_HOST', 'yunrun-mysql'), port=int(os.environ.get('MYSQL_PORT', '3306')), user=os.environ.get('MYSQL_USER', 'root'), password=os.environ.get('MYSQL_PASSWORD', 'yunrun2026'), database=os.environ.get('MYSQL_DATABASE', 'yunrun'), charset='utf8mb4')
with conn:
    with conn.cursor() as cur:
        try:
            cur.execute('ALTER TABLE users ADD COLUMN remark VARCHAR(256) DEFAULT NULL')
            print('remark 字段已添加')
        except Exception as e:
            print(f'remark: {e}')
    conn.commit()
