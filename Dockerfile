# echo — 多阶段构建：前端产物 + 后端服务
# 注意：M3 部署里程碑会完善；此处为 M0 骨架。

# 阶段 1：构建前端
FROM node:20-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# 阶段 2：后端运行时
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
# R-144 A：scripts/ 必须进镜像——scheduler._backup_job 每天 02:30 会调 /app/scripts/backup.sh，
# 少了它容器里「每日备份」会一直报「备份脚本不存在」（备份永不执行 → 没有回滚预案）
COPY scripts/ ./scripts/
RUN chmod +x scripts/*.sh
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
