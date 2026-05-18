FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema (gcc para compilar algunas wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primero para aprovechar cache de Docker
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copiar el resto del proyecto (backend sirve también el frontend estático)
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Variables de entorno por defecto (sobreescribir en runtime)
ENV PORT=8001 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/api/health || exit 1

WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
