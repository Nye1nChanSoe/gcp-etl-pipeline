# GCP ETL Pipeline

A simple serverless ETL pipeline built on Google Cloud Platform using **Cloud Functions Gen 2**, Cloud Storage, BigQuery, Eventarc, Cloud Build, and Cloud Scheduler.

## Architecture

```text
Cloud Scheduler
  → HTTP POST → extractor Cloud Function Gen 2
                  → writes JSON to GCS
                                    → GCS finalize event via Eventarc
                                        → loader Cloud Function Gen 2
                                            → appends rows to BigQuery
```

**Data source:** `https://open.er-api.com` — free public exchange rate API.

---

## Project Structure

```text
.
├── cloudbuild.yaml
├── extractor/
│   ├── main.py
│   ├── pyproject.toml
│   └── README.md
├── loader/
│   ├── main.py
│   ├── pyproject.toml
│   └── README.md
├── .gitignore
└── README.md
```

---

## GCP Resources

| Resource | Name |
|---|---|
| Project | `project-7abcab2d-24a7-4f5d-80a` |
| Region | `asia-southeast1` |
| Service Account | `etl-pipeline-runner-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com` |
| GCS Bucket | `harbour-etl-prod-raw-data-bucket-sg` |
| BigQuery Dataset | `harbour_prod_staging` |
| BigQuery Table | `exchangerates_api_raw` |
| Extractor Function | `forex-extractor-fn` |
| Loader Function | `gcs-to-bq-loader-fn` |

---

## 1. Set Variables

```bash
PROJECT_ID="project-7abcab2d-24a7-4f5d-80a"
REGION="asia-southeast1"
BUCKET="harbour-etl-prod-raw-data-bucket-sg"
DATASET="harbour_prod_staging"
TABLE="exchangerates_api_raw"
SA="etl-pipeline-runner-sa@$PROJECT_ID.iam.gserviceaccount.com"
```

---

## 2. Enable APIs

```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  eventarc.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com \
  pubsub.googleapis.com \
  --project=$PROJECT_ID
```

---

## 3. Create GCS Bucket

```bash
gsutil mb \
  -p $PROJECT_ID \
  -l $REGION \
  gs://$BUCKET
```

Verify location:

```bash
gsutil ls -L -b gs://$BUCKET | grep "Location constraint"
```

Expected:

```text
Location constraint: ASIA-SOUTHEAST1
```

---

## 4. Create BigQuery Dataset and Table

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

## 5. IAM Setup

Grant required roles to the ETL service account:

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/bigquery.jobUser"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/cloudfunctions.developer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/artifactregistry.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/cloudbuild.builds.builder"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/eventarc.eventReceiver"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/run.invoker"
```

If GCP asks for an IAM condition, choose:

```text
[2] None
```

---

## 6. Allow Service Account to Act as Itself

This lets the deployer attach the same service account as the runtime identity.

```bash
gcloud iam service-accounts add-iam-policy-binding $SA \
  --member="serviceAccount:$SA" \
  --role="roles/iam.serviceAccountUser" \
  --project=$PROJECT_ID
```

---

## 7. Allow GCS Service Agent to Publish Eventarc Events

Cloud Storage events use Pub/Sub internally before reaching Eventarc.

```bash
GCS_SA="$(gsutil kms serviceaccount -p $PROJECT_ID)"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$GCS_SA" \
  --role="roles/pubsub.publisher"
```

---

## 8. Optional: Fix Default Compute Service Account for Gen 2 Inner Builds

Cloud Functions Gen 2 may start an internal Cloud Build using the default compute service account.

```bash
COMPUTE_SA="391506331477-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$COMPUTE_SA" \
  --role="roles/cloudbuild.builds.builder"
```

---

## 9. Deploy with Cloud Build

```bash
gcloud builds submit \
  --project=$PROJECT_ID \
  --service-account="projects/$PROJECT_ID/serviceAccounts/$SA" \
  --substitutions=_GCS_BUCKET=$BUCKET,_BQ_DATASET=$DATASET,_BQ_TABLE=$TABLE,_REGION=$REGION
```

After successful deployment:

```bash
gcloud functions list --v2 --regions=$REGION
```

Expected functions:

```text
forex-extractor-fn
gcs-to-bq-loader-fn
```

---

## 10. Cloud Build Trigger Setup with GitHub

1. Go to **Cloud Build → Triggers**.
2. Connect the GitHub repository.
3. Create a trigger on push to `main` or `master`.
4. Set build config to `cloudbuild.yaml`.
5. Set service account to:

```text
etl-pipeline-runner-sa@project-7abcab2d-24a7-4f5d-80a.iam.gserviceaccount.com
```

Then push code:

```bash
git add .
git commit -m "Add Gen2 ETL pipeline"
git push origin master
```

---

## 11. Create Cloud Scheduler Job

Get extractor URL:

```bash
FUNCTION_URL=$(gcloud functions describe forex-extractor-fn \
  --v2 \
  --region=$REGION \
  --format='value(serviceConfig.uri)')
```

Create hourly scheduler:

```bash
gcloud scheduler jobs create http etl-extractor-trigger \
  --location=$REGION \
  --schedule="0 * * * *" \
  --uri="$FUNCTION_URL" \
  --http-method=POST \
  --oidc-service-account-email=$SA \
  --oidc-token-audience="$FUNCTION_URL" \
  --description="Trigger ETL extractor every hour"
```

Run scheduler manually:

```bash
gcloud scheduler jobs run etl-extractor-trigger \
  --location=$REGION
```

---

## 12. Testing

### Manually invoke extractor

```bash
TOKEN=$(gcloud auth print-identity-token)

FUNCTION_URL=$(gcloud functions describe forex-extractor-fn \
  --v2 \
  --region=$REGION \
  --format='value(serviceConfig.uri)')

curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "$FUNCTION_URL"
```

### Check GCS output

```bash
gsutil ls gs://$BUCKET
```

### Check Eventarc trigger

```bash
gcloud eventarc triggers list \
  --location=$REGION
```

### Check logs

```bash
gcloud functions logs read forex-extractor-fn \
  --v2 \
  --region=$REGION \
  --limit=50

gcloud functions logs read gcs-to-bq-loader-fn \
  --v2 \
  --region=$REGION \
  --limit=50
```

### Verify BigQuery data

```bash
bq query --project_id=$PROJECT_ID \
'SELECT *
 FROM `harbour_prod_staging.exchangerates_api_raw`
 ORDER BY extracted_at DESC
 LIMIT 10'
```

---

## Local Development

### Extractor

```bash
cd extractor
uv venv
source .venv/bin/activate
uv pip install -e .

GCS_BUCKET_NAME=harbour-etl-prod-raw-data-bucket-sg \
BASE_CURRENCY=USD \
functions-framework --target extract_data --port 8080
```

### Loader

```bash
cd loader
uv venv
source .venv/bin/activate
uv pip install -e .

GCS_BUCKET_NAME=harbour-etl-prod-raw-data-bucket-sg \
BQ_DATASET=harbour_prod_staging \
BQ_TABLE=exchangerates_api_raw \
functions-framework --target load_to_bq --port 8081
```

---

## Notes

- `asia-southeast1` is used for all resources to avoid cross-region deployment problems.
- Cloud Functions Gen 2 runs on Cloud Run internally.
- Eventarc trigger is created automatically when deploying the loader function with GCS trigger flags.
- Cloud Scheduler must be created once after the extractor function is deployed.
- `harbour-etl-prod-raw-data-bucket-sg` is used because existing bucket regions cannot be changed after creation.
