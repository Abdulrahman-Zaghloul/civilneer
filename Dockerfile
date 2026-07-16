FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m pip install --upgrade pip

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY static ./static
COPY README.md ./README.md

RUN mkdir -p web_uploads web_jobs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.web_api:app", "--host", "0.0.0.0", "--port", "8000"]
