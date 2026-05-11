# GCP ETL Pipeline

A containerized serverless ETL pipeline built on Google Cloud Platform using:

- Cloud Run
- Eventarc
- Cloud Storage
- BigQuery
- Cloud Build
- Cloud Scheduler
- Artifact Registry
- Docker + uv

---

# Architecture

```text
Cloud Scheduler
      ↓
forex-extractor-fn (Cloud Run HTTP Service)
      ↓ writes JSON to GCS
Google Cloud Storage Bucket
      ↓ object finalized event
Eventarc Trigger
      ↓
gcs-to-bq-loader-fn (Cloud Run Service)
      ↓
BigQuery
```

**Data source:** `https://open.er-api.com`

---

# Project Structure

```text
.
├── cloudbuild.yaml
├── extractor
│   ├── Dockerfile
│   ├── main.py
│   ├── pyproject.toml
│   ├── README.md
│   └── uv.lock
├── loader
│   ├── Dockerfile
│   ├── main.py
│   ├── pyproject.toml
│   ├── README.md
│   └── uv.lock
└── README.md
```

---

# GCP Resources

| Resource | Name |
|---|---|
| Project | `project-7abcab2d-24a7-4f5d-80a` |
| Region | `asia-southeast1` |
| Artifact Registry Repo | `etl-images` |
| Runtime Service Account | `etl-pipeline-deployer-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com` |
| Build Service Account | `391506331477-compute@developer.gserviceaccount.com` |
| GCS Bucket | `harbour-etl-prod-raw-data-bucket-sg` |
| BigQuery Dataset | `harbour_prod_staging` |
| BigQuery Table | `exchangerates_api_raw` |
| Extractor Service | `forex-extractor-fn` |
| Loader Service | `gcs-to-bq-loader-fn` |
| Eventarc Trigger | `gcs-to-bq-loader-trigger` |

---

# 1. Set Variables

```bash
PROJECT_ID="project-7abcab2d-24a7-4f5d-80a"
REGION="asia-southeast1"

BUCKET="harbour-etl-prod-raw-data-bucket-sg"

DATASET="harbour_prod_staging"
TABLE="exchangerates_api_raw"

RUNTIME_SA="etl-pipeline-deployer-sa@$PROJECT_ID.iam.gserviceaccount.com"

BUILD_SA="391506331477-compute@developer.gserviceaccount.com"

PROJECT_NUMBER="391506331477"

EVENTARC_SA="service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com"
```

---

# 2. Enable Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  eventarc.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com \
  pubsub.googleapis.com \
  --project=$PROJECT_ID
```

---

# 3. Create Artifact Registry Repository

```bash
gcloud artifacts repositories create etl-images \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID
```

---

# 4. Create GCS Bucket

```bash
gsutil mb \
  -p $PROJECT_ID \
  -l $REGION \
  gs://$BUCKET
```

Verify region:

```bash
gsutil ls -L -b gs://$BUCKET | grep "Location constraint"
```

Expected:

```text
Location constraint: ASIA-SOUTHEAST1
```

---

# 5. Create BigQuery Dataset and Table

```bash
bq --project_id=$PROJECT_ID mk \
  --dataset \
  --location=$REGION \
  $DATASET
```

```bash
bq --project_id=$PROJECT_ID mk \
  --table \
  $DATASET.$TABLE \
  extracted_at:STRING,base_currency:STRING,target_currency:STRING,rate:FLOAT
```

---

# 6. IAM Setup

## A. Permissions for Cloud Build Execution Account

Grant these roles to:

```text
391506331477-compute@developer.gserviceaccount.com
```

### Cloud Run Admin

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$BUILD_SA" \
  --role="roles/run.admin"
```

### Eventarc Admin

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$BUILD_SA" \
  --role="roles/eventarc.admin"
```

### Service Account User

```bash
gcloud iam service-accounts add-iam-policy-binding \
  $RUNTIME_SA \
  --member="serviceAccount:$BUILD_SA" \
  --role="roles/iam.serviceAccountUser" \
  --project=$PROJECT_ID
```

---

## B. Permissions for Runtime Service Account

Grant these roles to:

```text
etl-pipeline-deployer-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com
```

### Storage Object Admin

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/storage.objectAdmin"
```

### BigQuery Data Editor

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/bigquery.dataEditor"
```

### BigQuery Job User

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/bigquery.jobUser"
```

### Eventarc Event Receiver

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/eventarc.eventReceiver"
```

### Cloud Run Invoker

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/run.invoker"
```

---

## C. Eventarc Service Agent Fix

Required if you see:

```text
Permission denied while using the Eventarc Service Agent
```

Grant:

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$EVENTARC_SA" \
  --role="roles/eventarc.serviceAgent"
```

Wait 1–3 minutes for IAM propagation after granting.

---

# 7. Allow GCS Service Agent to Publish Events

Cloud Storage internally uses Pub/Sub before Eventarc.

```bash
GCS_SA="$(gsutil kms serviceaccount -p $PROJECT_ID)"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$GCS_SA" \
  --role="roles/pubsub.publisher"
```

---

# 8. Deploy

```bash
gcloud builds submit --config cloudbuild.yaml .
```

Expected build steps:

```text
build-extractor
push-extractor
deploy-extractor
build-loader
push-loader
deploy-loader
create-loader-trigger
```

---

# 9. Create Cloud Scheduler Job

Get extractor URL:

```bash
EXTRACTOR_URL=$(gcloud run services describe forex-extractor-fn \
  --region=$REGION \
  --format='value(status.url)')
```

Create scheduler:

```bash
gcloud scheduler jobs create http forex-extractor-hourly \
  --location=$REGION \
  --schedule="0 * * * *" \
  --uri="$EXTRACTOR_URL" \
  --http-method=POST \
  --oidc-service-account-email="$RUNTIME_SA" \
  --oidc-token-audience="$EXTRACTOR_URL"
```

Allow scheduler/runtime SA to invoke Cloud Run:

```bash
gcloud run services add-iam-policy-binding forex-extractor-fn \
  --region=$REGION \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/run.invoker"
```

Run manually:

```bash
gcloud scheduler jobs run forex-extractor-hourly \
  --location=$REGION
```

---

# 10. Testing

## Manually invoke extractor

```bash
TOKEN=$(gcloud auth print-identity-token)

EXTRACTOR_URL=$(gcloud run services describe forex-extractor-fn \
  --region=$REGION \
  --format='value(status.url)')

curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "$EXTRACTOR_URL"
```

Expected response:

```json
{
  "status": "success"
}
```

---

## Check GCS Output

```bash
gsutil ls gs://$BUCKET/exchange_rates/
```

---

## Check Eventarc Trigger

```bash
gcloud eventarc triggers list \
  --location=$REGION
```

Expected:

```text
gcs-to-bq-loader-trigger
```

---

## Check Cloud Run Logs

```bash
gcloud run services logs read forex-extractor-fn \
  --region=$REGION \
  --limit=50

gcloud run services logs read gcs-to-bq-loader-fn \
  --region=$REGION \
  --limit=50
```

---

## Verify BigQuery Data

```bash
bq query --use_legacy_sql=false '
SELECT *
FROM `project-7abcab2d-24a7-4f5d-80a.harbour_prod_staging.exchangerates_api_raw`
ORDER BY extracted_at DESC
LIMIT 10
'
```

If rows appear, the pipeline works end-to-end.

---

# Local Development

## Extractor

```bash
cd extractor

uv venv
source .venv/bin/activate

uv sync

export GCS_BUCKET_NAME=harbour-etl-prod-raw-data-bucket-sg
export BASE_CURRENCY=USD

uv run functions-framework \
  --target=extract_data \
  --host=0.0.0.0 \
  --port=8080
```

---

## Loader

```bash
cd loader

uv venv
source .venv/bin/activate

uv sync

export GCS_BUCKET_NAME=harbour-etl-prod-raw-data-bucket-sg
export BQ_DATASET=harbour_prod_staging
export BQ_TABLE=exchangerates_api_raw

uv run functions-framework \
  --target=load_to_bq \
  --host=0.0.0.0 \
  --port=8081
```

---

# Cloud Run Jobs vs Cloud Run Services

This project currently uses:

```text
Cloud Scheduler → Cloud Run Service
```

This keeps the extractor easy to:
- invoke manually
- test with curl
- integrate with HTTP workflows

However, ETL workloads are naturally batch-oriented.

A more advanced production architecture would be:

```text
Cloud Scheduler
→ Cloud Run Job
→ GCS
→ Eventarc
→ Cloud Run Loader Service
→ BigQuery
```

Cloud Run Jobs are ideal for:
- cron workloads
- ETL
- scheduled scripts
- one-time execution containers

Unlike services, Jobs:
- do not expose HTTP endpoints
- do not require Functions Framework
- do not need to listen on port 8080

This project intentionally keeps the extractor as a Service for simplicity and easier testing.

---

# Important Notes

- This project uses Cloud Run containers, NOT Cloud Functions source deployments.
- Docker images are stored in Artifact Registry (`etl-images`).
- Eventarc triggers GCS finalize events to the loader service.
- Cloud Run containers MUST listen on `0.0.0.0:$PORT`.
- `gcf-artifacts` should NOT appear anymore in builds.
- All resources use `asia-southeast1` to avoid cross-region issues.

---

# Common Errors

## Permission denied: run.services.get

Cause:

```text
Missing roles/run.admin
```

---

## Permission denied: eventarc.triggers.create

Cause:

```text
Missing roles/eventarc.admin
```

---

## Permission denied while using the Eventarc Service Agent

Cause:

```text
Missing roles/eventarc.serviceAgent
```

Fix:

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$EVENTARC_SA" \
  --role="roles/eventarc.serviceAgent"
```

---

## Container failed to start and listen on PORT=8080

Cause:
Container not listening externally.

Correct Docker CMD:

```dockerfile
CMD ["uv", "run", "functions-framework", "--target=extract_data", "--host=0.0.0.0", "--port=8080"]
```

---

## Seeing gcf-artifacts Instead of etl-images

Cause:
Using:

```bash
gcloud functions deploy
```

instead of:

```bash
gcloud run deploy
```
