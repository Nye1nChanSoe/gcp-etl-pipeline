FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "functions-framework==3.*" \
    "google-cloud-storage==2.*" \
    "requests==2.*"

COPY main.py .

ENV PORT=8080

CMD ["functions-framework", "--target=extract_data", "--port=8080"]