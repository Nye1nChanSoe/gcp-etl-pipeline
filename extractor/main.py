"""
Cloud Run Function: extract_data
Fetches open exchange rate data and saves it to GCS as a JSON file.
Triggered by: HTTP (Cloud Scheduler)
"""

import json
import logging
import os
from datetime import datetime, timezone

import functions_framework
import requests
from google.cloud import storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
BASE_CURRENCY = os.environ.get("BASE_CURRENCY", "USD")

# Free, no-auth public exchange rate API
EXCHANGE_RATE_URL = f"https://open.er-api.com/v6/latest/{BASE_CURRENCY}"


@functions_framework.http
def extract_data(request):
    """
    HTTP-triggered function. Fetches exchange rate data and uploads it to GCS.
    Returns a JSON response with the GCS file path and record count.
    """
    logger.info("Starting extraction...")

    # --- 1. Fetch data ---
    try:
        response = requests.get(EXCHANGE_RATE_URL, timeout=10)
        response.raise_for_status()
        raw = response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch exchange rate data: {e}")
        return (
            json.dumps({"status": "error", "message": str(e)}),
            500,
            {"Content-Type": "application/json"},
        )

    if raw.get("result") != "success":
        msg = f"API returned non-success result: {raw}"
        logger.error(msg)
        return (
            json.dumps({"status": "error", "message": msg}),
            502,
            {"Content-Type": "application/json"},
        )

    # --- 2. Transform into a list of records ---
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rates = raw.get("rates", {})
    records = [
        {
            "extracted_at": timestamp,
            "base_currency": raw.get("base_code", BASE_CURRENCY),
            "target_currency": currency,
            "rate": rate,
        }
        for currency, rate in rates.items()
    ]

    payload = {
        "extracted_at": timestamp,
        "base_currency": raw.get("base_code", BASE_CURRENCY),
        "time_last_update_utc": raw.get("time_last_update_utc"),
        "record_count": len(records),
        "records": records,
    }

    # --- 3. Upload to GCS ---
    file_name = f"exchange_rates/rates_{timestamp}.json"
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(file_name)
        blob.upload_from_string(
            json.dumps(payload, indent=2),
            content_type="application/json",
        )
        logger.info(f"Uploaded {file_name} to gs://{GCS_BUCKET_NAME}")
    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")
        return (
            json.dumps({"status": "error", "message": str(e)}),
            500,
            {"Content-Type": "application/json"},
        )

    result = {
        "status": "success",
        "gcs_path": f"gs://{GCS_BUCKET_NAME}/{file_name}",
        "record_count": len(records),
        "extracted_at": timestamp,
    }
    logger.info(f"Extraction complete: {result}")
    return (json.dumps(result), 200, {"Content-Type": "application/json"})


if __name__ == "__main__":
    extract_data()
