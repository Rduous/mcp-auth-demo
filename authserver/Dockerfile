# Build with context = repo root (shares requirements.txt with server):
#   docker build -f authserver/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY authserver/ ./authserver/
WORKDIR /app/authserver
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
