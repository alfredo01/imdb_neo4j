FROM python:3.9-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu && \
    pip install torch-scatter torch-sparse -f https://data.pyg.org/whl/torch-2.2.2+cpu.html

COPY . /app

CMD ["uvicorn", "app.api:api", "--host", "0.0.0.0", "--port", "8000"]
