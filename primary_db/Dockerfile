FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY ingest_data.py seed_data.py ./

CMD ["python", "/app/seed_data.py"]
