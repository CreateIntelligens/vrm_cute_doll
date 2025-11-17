FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 複製需求檔案
COPY requirements.txt .

# 安裝 Python 依賴
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式
COPY server.py .

# 創建必要的目錄
RUN mkdir -p /app/vrm /app/uploads /app/frontend

# 暴露端口
EXPOSE 5456

# 啟動命令
CMD ["python", "server.py"]
