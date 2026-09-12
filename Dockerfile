FROM python:3.11-slim

WORKDIR /app
COPY kse-monitor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kse-monitor/ .

ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
