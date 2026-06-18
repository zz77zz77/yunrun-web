# coding: utf-8
import os
import pymysql

DEVICES = [
    "Xiaomi 14", "Xiaomi 13 Pro", "Xiaomi 13 Ultra",
    "Redmi K70", "Redmi K60 Pro", "Redmi Note 13 Pro",
    "OPPO Find X7 Ultra", "OPPO Find X6 Pro", "OnePlus 12",
    "vivo X100 Pro", "vivo X90 Pro+", "iQOO 12",
    "Honor Magic5 Pro", "Honor 100", "Honor X50",
    "Huawei Mate 60 Pro", "Huawei P60 Art",
    "Samsung Galaxy S24 Ultra", "Samsung Galaxy Z Fold5",
    "iPhone 15 Pro Max", "iPhone 15 Pro", "iPhone 14 Pro Max"
]

conn = pymysql.connect(
    host=os.environ.get('MYSQL_HOST', 'yunrun-mysql'), port=3306,
    user='root', password=os.environ.get('MYSQL_PASSWORD', 'yunrun2026'),
    database='yunrun', charset='utf8mb4'
)
with conn:
    with conn.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS devices (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(128) NOT NULL UNIQUE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        for d in DEVICES:
            cur.execute('INSERT IGNORE INTO devices (name) VALUES (%s)', (d,))
    conn.commit()
print(f'devices 表初始化完成，共 {len(DEVICES)} 条')
