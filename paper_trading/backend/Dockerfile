FROM python:3.11-slim

WORKDIR /app

# Install dependencies before copying code (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite DB lives in a mounted volume; default path resolves to /app/paper_trading.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
