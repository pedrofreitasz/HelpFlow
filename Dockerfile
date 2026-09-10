FROM python:3.11-slim
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY . .
RUN useradd --uid 10001 --create-home helpflow && mkdir -p instance/uploads && chown -R helpflow:helpflow /app
USER helpflow
ENV HOST=0.0.0.0 PORT=5000 PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["python", "run.py"]
