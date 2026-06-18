FROM python:3.11-slim

WORKDIR /app

# 安装依赖（单独一层，利用缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制源码
COPY . .

# 创建运行时目录
RUN mkdir -p /app/data /app/tasks /app/school_tasks

EXPOSE 5000

CMD ["python", "app.py"]
