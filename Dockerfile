FROM python:3.11-slim
WORKDIR /app
# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 复制源码
COPY . .
# 设置PYTHONPATH，让web_ui.py中的 from proxy_pool.xxx import 能找到父目录的proxy_pool包
ENV PYTHONPATH=/app/..
# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:5000/api/stats || exit 1
# 暴露端口
EXPOSE 5000
# 启动（如果 web_ui.py 存在，则使用 gunicorn，否则使用 flask）
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "web_ui:app"]