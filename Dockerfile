FROM python:3.9-slim

# Evitar que Python guarde los logs en búfer
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py .

CMD ["uvicorn", "bridge:app", "--host", "0.0.0.0", "--port", "8000"]
