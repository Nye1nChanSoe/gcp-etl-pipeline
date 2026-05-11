"""
Cloud Run Function: load_to_bq
Reads a JSON file from GCS and loads its records into BigQuery.
Triggered by: GCS object finalize (Eventarc)
"""

import json
import logging
import os

import functions_framework
from google.cloud import bigquery, storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BQ_DATASET = os.environ["BQ_DATASET"]
BQ_TABLE = os.environ["BQ_TABLE"]
GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]

# BigQuery schema — matches the records produced by the extractor
BQ_SCHEMA = [
    bigquery.SchemaField("extracted_at", "STRING"),
    bigquery.SchemaField("base_currency", "STRING"),
    bigquery.SchemaField("target_currency", "STRING"),
    bigquery.SchemaField("rate", "FLOAT"),
]


@functions_framework.cloud_event
def load_to_bq(cloud_event):
    """
    GCS-triggered function (Eventarc finalize).
    Reads the uploaded JSON file and appends records to BigQuery.
    """
    data = cloud_event.data
    bucket_name = data.get("bucket", GCS_BUCKET_NAME)
    file_name = data["name"]

    logger.info(f"Triggered by gs://{bucket_name}/{file_name}")

    # Only process files in the exchange_rates/ prefix
    if not file_name.startswith("exchange_rates/"):
        logger.info(f"Skipping file outside exchange_rates/: {file_name}")
        return

    # --- 1. Read file from GCS ---
    try:
        gcs_client = storage.Client()
        blob = gcs_client.bucket(bucket_name).blob(file_name)
        content = blob.download_as_text()
        payload = json.loads(content)
    except Exception as e:
        logger.error(f"Failed to read gs://{bucket_name}/{file_name}: {e}")
        raise

    records = payload.get("records", [])
    if not records:
        logger.warning("No records found in file — nothing to load.")
        return

    logger.info(f"Loaded {len(records)} records from file.")

    # --- 2. Load into BigQuery ---
    bq_client = bigquery.Client()
    table_ref = f"{bq_client.project}.{BQ_DATASET}.{BQ_TABLE}"

    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )

    try:
        load_job = bq_client.load_table_from_json(
            records,
            table_ref,
            job_config=job_config,
        )
        load_job.result()  # Wait for completion
    except Exception as e:
        logger.error(f"BigQuery load failed: {e}")
        raise

    logger.info(
        f"Successfully loaded {len(records)} rows into {table_ref} "
        f"from gs://{bucket_name}/{file_name}"
    )
