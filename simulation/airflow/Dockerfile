FROM apache/airflow:2.10.5-python3.12

COPY requirements.txt /requirements.txt
COPY entrypoint.sh /opt/airflow-bootstrap.sh

RUN pip install --no-cache-dir -r /requirements.txt
