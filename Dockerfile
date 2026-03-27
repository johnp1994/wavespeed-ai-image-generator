# ---------- build stage ----------
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY main.py .

# Cloud Run injects PORT; default to 8080 for local Docker runs
ENV PORT=8080

EXPOSE 8080

# Use shell form so $PORT is expanded at runtime
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
