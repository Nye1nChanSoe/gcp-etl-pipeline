FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "functions-framework==3.*" \
    "google-cloud-storage==2.*" \
    "google-cloud-bigquery==3.*"

COPY main.py .

ENV PORT=8080

CMD ["functions-framework", "--target=load_to_bq", "--port=8080"]