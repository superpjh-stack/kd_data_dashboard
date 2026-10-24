FROM node:22-alpine AS web
WORKDIR /build
COPY web/package*.json web/tsconfig*.json web/vite.config.ts web/index.html ./
COPY web/src ./src
RUN npm ci && npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY dashboard ./dashboard
COPY --from=web /build/dist ./web/dist
EXPOSE 8021
CMD ["uvicorn", "dashboard.run:app", "--host", "0.0.0.0", "--port", "8021"]
