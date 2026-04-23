FROM python:3.11-slim
WORKDIR /src
# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 复制源码到 /src/proxy_pool/，使 from proxy_pool.xxx import 正常工作
COPY . /src/proxy_pool/
# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:5000/api/stats || exit 1
# 暴露端口
EXPOSE 5000
# 启动（工作目录为 /src，gunicorn 可找到 proxy_pool 包）
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "proxy_pool.web_ui:app"]
