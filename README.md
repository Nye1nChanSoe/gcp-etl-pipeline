# GCP ETL Pipeline

A simple serverless ETL pipeline built on Google Cloud Platform using Cloud Run Functions, Cloud Storage, BigQuery, and Cloud Scheduler.

## Architecture

```
Cloud Scheduler (cron)
  → HTTP POST → [extractor] Cloud Run Function
                  → writes JSON → GCS Bucket
                                    → GCS finalize event (Eventarc)
                                        → [loader] Cloud Run Function
                                            → appends rows → BigQuery Table
```

**Data source:** [open.er-api.com](https://open.er-api.com) — free, no-auth public exchange rate API.

---

## Project Structure

```
.
├── cloudbuild.yaml       # Cloud Build deployment config
├── extractor/
│   ├── main.py           # HTTP-triggered Cloud Run Function
│   ├── pyproject.toml
│   └── README.md
├── loader/
│   ├── main.py           # GCS-triggered Cloud Run Function
│   ├── pyproject.toml
│   └── README.md
├── .gitignore
└── README.md
```

---

## GCP Resources

| Resource           | Name                                                                            |
| ------------------ | ------------------------------------------------------------------------------- |
| Project            | `project-7abcab2d-24a7-4f5d-80a`                                                |
| Region             | `us-central1`                                                                   |
| Service Account    | `etl-pipeline-runner-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com` |
| GCS Bucket         | `YOUR_BUCKET_NAME`                                                              |
| BigQuery Dataset   | `etl_dataset`                                                                   |
| BigQuery Table     | `exchange_rates`                                                                |
| Extractor Function | `weather-extractor-fn`                                                          |
| Loader Function    | `gcs-to-bq-loader-fn`                                                           |

---

## One-Time Setup

### 1. Enable APIs

```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  eventarc.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com \
  --project=project-7abcab2d-24a7-4f5d-80a
```

### 2. Create the GCS Bucket

```bash
gsutil mb -p project-7abcab2d-24a7-4f5d-80a \
  -l us-central1 \
  gs://YOUR_BUCKET_NAME
```

### 3. Create BigQuery Dataset and Table

```bash
# Dataset
bq --project_id=project-7abcab2d-24a7-4f5d-80a \
  mk --dataset --location=US etl_dataset

# Table with schema
bq --project_id=project-7abcab2d-24a7-4f5d-80a \
  mk --table etl_dataset.exchange_rates \
  extracted_at:STRING,base_currency:STRING,target_currency:STRING,rate:FLOAT
```

### 4. Grant IAM Roles to the Service Account

```bash
SA="etl-pipeline-runner-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com"
PROJECT="project-7abcab2d-24a7-4f5d-80a"

# GCS — read and write objects
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/storage.objectAdmin"

# BigQuery — insert rows
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/bigquery.dataEditor"

# BigQuery — run jobs
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/bigquery.jobUser"

# Eventarc — receive GCS events
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/eventarc.eventReceiver"

# Invoke Cloud Run (needed by Scheduler and Eventarc)
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/run.invoker"

# Allow GCS service agent to publish Eventarc events
GCS_SA="$(gsutil kms serviceaccount -p $PROJECT)"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$GCS_SA" \
  --role="roles/pubsub.publisher"
```

---

## Deployment

### Deploy with Cloud Build (CI/CD)

```bash
gcloud builds submit \
  --project=project-7abcab2d-24a7-4f5d-80a \
  --substitutions=_GCS_BUCKET=YOUR_BUCKET_NAME,_BQ_DATASET=etl_dataset,_BQ_TABLE=exchange_rates
```

### Deploy Manually (one-off)

```bash
BUCKET="YOUR_BUCKET_NAME"
SA="etl-pipeline-runner-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com"

# Extractor
gcloud run deploy weather-extractor-fn \
  --source=extractor/ \
  --function=extract_data \
  --region=us-central1 \
  --runtime=python311 \
  --service-account=$SA \
  --set-env-vars=GCS_BUCKET_NAME=$BUCKET,BASE_CURRENCY=USD \
  --no-allow-unauthenticated

# Loader
gcloud run deploy gcs-to-bq-loader-fn \
  --source=loader/ \
  --function=load_to_bq \
  --region=us-central1 \
  --runtime=python311 \
  --service-account=$SA \
  --set-env-vars=GCS_BUCKET_NAME=$BUCKET,BQ_DATASET=etl_dataset,BQ_TABLE=exchange_rates \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=$BUCKET" \
  --trigger-service-account=$SA
```

---

## Cloud Scheduler

Create a job to trigger the extractor every hour:

```bash
# Get the extractor URL first
EXTRACTOR_URL=$(gcloud run services describe weather-extractor-fn \
  --region=us-central1 \
  --format='value(status.url)')

SA="etl-pipeline-runner-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com"

gcloud scheduler jobs create http etl-extractor-trigger \
  --location=us-central1 \
  --schedule="0 * * * *" \
  --uri="$EXTRACTOR_URL" \
  --http-method=POST \
  --oidc-service-account-email=$SA \
  --oidc-token-audience="$EXTRACTOR_URL" \
  --description="Trigger ETL extractor every hour"
```

---

## Testing

### Trigger the extractor manually

```bash
# With gcloud (recommended — handles auth automatically)
gcloud run services proxy weather-extractor-fn --region=us-central1 &
curl -X POST http://localhost:8080

# Or with a token
TOKEN=$(gcloud auth print-identity-token)
EXTRACTOR_URL=$(gcloud run services describe weather-extractor-fn \
  --region=us-central1 --format='value(status.url)')
curl -X POST -H "Authorization: Bearer $TOKEN" $EXTRACTOR_URL
```

### Check logs

```bash
# Extractor logs
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="weather-extractor-fn"' \
  --limit=50 --format=json | jq '.[].textPayload'

# Loader logs
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="gcs-to-bq-loader-fn"' \
  --limit=50 --format=json | jq '.[].textPayload'
```

### Verify data in BigQuery

```bash
bq query --project_id=project-7abcab2d-24a7-4f5d-80a \
  'SELECT * FROM `etl_dataset.exchange_rates` ORDER BY extracted_at DESC LIMIT 10'
```

---

## Cloud Build Trigger Setup (GitHub)

1. Go to **Cloud Build → Triggers → Connect repository** and link your GitHub repo.
2. Create a trigger on push to `main` with the build config set to `cloudbuild.yaml`.
3. Under **"Service account"**, select `etl-pipeline-runner-sa@...` — this is the identity Cloud Build itself uses to run steps.
4. The `--service-account` flag inside `cloudbuild.yaml` sets the **runtime identity** for the deployed Cloud Run Functions (separate from the Cloud Build executor).

> **Important:** The Cloud Build service account also needs `roles/cloudbuild.builds.builder` and `roles/iam.serviceAccountUser` on the runner SA so it can act as it during deployment.

```bash
CB_SA="$(gcloud projects describe project-7abcab2d-24a7-4f5d-80a \
  --format='value(projectNumber)')@cloudbuild.gserviceaccount.com"

gcloud iam service-accounts add-iam-policy-binding \
  etl-pipeline-runner-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com \
  --member="serviceAccount:$CB_SA" \
  --role="roles/iam.serviceAccountUser"
```

---

## Local Development

```bash
# Extractor
cd extractor
uv venv && source .venv/bin/activate
uv pip install -e .
GCS_BUCKET_NAME=your-bucket functions-framework --target extract_data --port 8080

# Loader
cd loader
uv venv && source .venv/bin/activate
uv pip install -e .
GCS_BUCKET_NAME=your-bucket BQ_DATASET=etl_dataset BQ_TABLE=exchange_rates \
  functions-framework --target load_to_bq --port 8081
```
