FROM python:3.9-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app

CMD ["uvicorn", "app.api:api", "--host", "0.0.0.0", "--port", "8000"]
