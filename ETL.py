import os
import logging
from datetime import datetime, timedelta
import requests
import psycopg2
from psycopg2.extras import execute_batch
from google.cloud import bigquery

GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID', '')
BIGQUERY_DATASET = os.getenv('BIGQUERY_DATASET', '')
GCP_BILLING_TABLE_PATTERN = os.getenv('GCP_BILLING_TABLE_PATTERN', 'gcp_billing_export_resource_v1_*')
GCP_POSTGRES_CONN = os.getenv('GCP_POSTGRES_CONN', '')
AZURE_SUBSCRIPTION_ID = os.getenv('AZURE_SUBSCRIPTION_ID', '')
AZURE_TENANT_ID = os.getenv('AZURE_TENANT_ID', '')
AZURE_CLIENT_ID = os.getenv('AZURE_CLIENT_ID', '')
AZURE_CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET', '')
AZURE_POSTGRES_CONN = os.getenv(
    'AZURE_POSTGRES_CONN',
    ''
)
USD_TO_INR_RATE = float(os.getenv('USD_TO_INR_RATE', '88.67'))

logging.basicConfig(level=logging.INFO)

def fetch_gcp_billing_data(days: int = 7):
    client = bigquery.Client(project=GCP_PROJECT_ID)

    query = f"""
    SELECT
      DATE(usage_start_time) AS date,
      service.description AS service,
      SUM(cost) AS cost_usd,
      ANY_VALUE(currency_conversion_rate) AS conversion_rate,
      location.region AS region,
      currency AS currency
    FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET}.{GCP_BILLING_TABLE_PATTERN}`
    WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    GROUP BY date, service, region, currency
    ORDER BY date DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", days),
        ]
    )

    query_job = client.query(query, job_config=job_config)
    rows = query_job.result()
    data = []
    for row in rows:
        rate = float(row.conversion_rate or 1.0)
        cost_in_inr = float(row.cost_usd or 0.0) * rate
        data.append((row.date, 'gcp', row.service, cost_in_inr, row.region, 'INR'))

    logging.info(f"Fetched {len(data)} records from GCP BigQuery")
    return data


def upsert_daily_costs_pg(conn_str, data, label):
    if not data:
        logging.warning(f"No data to upsert for {label}")
        return

    conn = psycopg2.connect(conn_str)
    cur = conn.cursor()

    upsert_sql = """
    INSERT INTO daily_costs (date, provider, service, cost, region, currency)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (date, provider, service) DO UPDATE
    SET cost = EXCLUDED.cost,
        region = EXCLUDED.region,
        currency = EXCLUDED.currency,
        created_at = NOW()
    """

    execute_batch(cur, upsert_sql, data, page_size=100)
    conn.commit()
    cur.close()
    conn.close()
    logging.info(f"Upserted {len(data)} records into {label} PostgreSQL")

def get_azure_access_token():
    url = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/token"
    payload = {
        'grant_type': 'client_credentials',
        'client_id': AZURE_CLIENT_ID,
        'client_secret': AZURE_CLIENT_SECRET,
        'resource': 'https://management.azure.com/'
    }
    resp = requests.post(url, data=payload)
    resp.raise_for_status()
    token = resp.json()['access_token']
    return token


def fetch_azure_cost_data(days=7):
    token = get_azure_access_token()
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    today = datetime.utcnow().date()
    start_date = today - timedelta(days=days)

    url = (f"https://management.azure.com/subscriptions/{AZURE_SUBSCRIPTION_ID}/providers/Microsoft.CostManagement/"
           f"query?api-version=2021-10-01")

    body = {
        "type": "Usage",
        "timeframe": "Custom",
        "timePeriod": {
            "from": start_date.isoformat(),
            "to": today.isoformat()
        },
        "dataset": {
            "granularity": "Daily",
            "aggregation": {
                "totalCost": {
                    "name": "PreTaxCost",
                    "function": "Sum"
                }
            },
            "grouping": [
                {
                    "type": "Dimension",
                    "name": "ServiceName"
                },
                {
                    "type": "Dimension",
                    "name": "ResourceGroup"
                }
            ]
        }
    }

    response = requests.post(url, headers=headers, json=body)
    response.raise_for_status()
    data = response.json()

    properties = data.get('properties', {})
    columns = properties.get('columns', [])
    rows = properties.get('rows', [])
    col_index = {col['name']: idx for idx, col in enumerate(columns)}

    service_idx = col_index.get('ServiceName', 0)
    rg_idx = col_index.get('ResourceGroup', 1)
    cost_idx = col_index.get('PreTaxCost')
    date_idx = col_index.get('UsageDate') or col_index.get('UsageDateTime')

    parsed = []
    for row in rows:
        service = row[service_idx] if service_idx is not None and service_idx < len(row) else "Unknown"
        resource_group = row[rg_idx] if rg_idx is not None and rg_idx < len(row) else "Unknown"

        raw_cost = row[cost_idx] if cost_idx is not None and cost_idx < len(row) else 0
        try:
            cost = float(raw_cost)
        except (ValueError, TypeError):
            cost = 0.0

        if date_idx is not None and date_idx < len(row):
            try:
                date = datetime.strptime(row[date_idx], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                date = start_date
        else:
            date = start_date

        cost_in_inr = cost * USD_TO_INR_RATE
        parsed.append((date, 'azure', service, cost_in_inr, resource_group, 'INR'))

    logging.info(f"Fetched {len(parsed)} records from Azure Cost Management API")
    return parsed


def main():
    days_to_fetch = 7

    gcp_data = fetch_gcp_billing_data(days=days_to_fetch)
    upsert_daily_costs_pg(GCP_POSTGRES_CONN, gcp_data, 'GCP')
    azure_data = fetch_azure_cost_data(days=days_to_fetch)
    upsert_daily_costs_pg(AZURE_POSTGRES_CONN, azure_data, 'Azure')

if __name__ == "__main__":
    main()
