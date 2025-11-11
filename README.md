# Cloud Cost Forecast

This repository automates ingesting GCP/Azure billing data, training Temporal Fusion Transformer (TFT) models per cloud, and hosting a FastAPI dashboard that visualizes weekly/monthly/yearly projections.

---

## Architecture Overview

```
          ┌───────────────┐      ┌────────────────────┐      ┌───────────────────────┐
          │   Terraform   │ ---> │  Cloud Resources   │ ---> │  GCP/Azure Billing    │
          │ (GCP + Azure) │      │ (VPC, Postgres, etc│      │   Export / Cost API   │
          └───────────────┘      └─────────┬──────────┘      └─────────┬────────────┘
                                           │                           │
                                           ▼                           ▼
                                   daily_costs (Postgres)      Azure Cost Mgmt API
                                           │
                                           ▼
                     ┌─────────────┐   ETL (Python)   ┌─────────────┐
                     │ GitHub      │─────────────────>│  Artifacts  │
                     │ Actions     │                  │ (model ckpt)│
                     └────┬────────┘                  └────┬────────┘
                          │                                 │
                          ▼                                 ▼
                  Train TFT per provider           Build & Deploy FastAPI
                          │                                 │
                          └──────────────> Dashboard (GCP/Azure cards)
```

---

## Terraform Deployment

Terraform provisions:

- **GCP**: VPC, subnet, firewall (SSH/API), Cloud SQL Postgres, Artifact Registry, GCS bucket.
- **Azure**: Resource group, VNet/subnet, NSG rules, Azure Database for PostgreSQL flexible server, storage account/container.

### Required `terraform.tfvars`

Minimal example (fill with real values):

```hcl
project_name               = "cloud-cost-forecast"
environment                = "dev"
enable_gcp                 = true
enable_azure               = true
db_admin_password          = "SuperSecurePassword"

# GCP specifics
gcp_project_id             = "your-gcp-project-id"
gcp_region                 = "us-central1"
gcp_zone                   = "us-central1-a"
gcp_models_bucket_name     = "cloud-cost-models"
gcp_artifact_repository_id = "cost-forecast-api"

# Azure specifics
azure_subscription_id      = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
azure_client_id            = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
azure_client_secret        = "azure-client-secret"
azure_tenant_id            = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
azure_region               = "eastus"
azure_resource_group_name  = "cloud-cost-optimizer-rg"
azure_storage_container_name = "model-artifacts"
```

Deploy:

```bash
cd terraform
terraform init
terraform apply
```

Terraform outputs include VPC/subnet names, Postgres connection strings, etc., which are needed for the ETL step and GitHub runner secrets.

### Enable Billing Exports

- **GCP**: Enable the built-in BigQuery billing export for the Google Cloud project (`all_billing_data.gcp_billing_export_resource_v1_*`). The ETL job assumes the dataset/table already exists and contains the last ~180 days of cost rows.
- **Azure**: Grant the service principal (same credentials used in Terraform/ETL) access to Cost Management. The ETL reaches the Cost Management API (`Microsoft.CostManagement/query`) using those credentials.

---

## GitHub Actions Pipeline

Workflow file: `.github/workflows/etl.yml`

Jobs:

1. **run-etl (etl-runner)**  
   - Installs Python deps, authenticates to GCP.  
   - Runs `ETL.py` which:
     - Pulls GCP billing from BigQuery.
     - Pulls Azure costs via Cost Management API.
     - Converts all costs to INR and upserts into provider-specific Postgres databases (`daily_costs` table).

2. **train-gcp / train-azure (gpu-training-runner)**  
   - Uses `src/training/tft.py` to train a TFT per provider.  
   - Saves checkpoints under `artifacts/model/<provider>/tft_cost_forecast.ckpt`.  
   - Logs final train/val loss in job output.

3. **build-and-push-image (etl-runner)**  
   - Downloads both checkpoints.  
   - Builds Docker image with FastAPI + UI + latest models.  
   - Pushes to Artifact Registry `us-central1-docker.pkg.dev/<project>/<repo>/cost-forecast-api`.

4. **deploy-api (do-deploy-runner)**  
   - Downloads checkpoints to runner (`$HOME/cost-forecast/model`).  
   - Runs container:
     ```bash
     docker run -d --name cost-forecast-api \
       -p 80:8000 \
       -v $HOME/cost-forecast/model:/app/model \
       -e GCP_POSTGRES_CONN=... \
       -e AZURE_POSTGRES_CONN=... \
       us-central1-docker.pkg.dev/.../cost-forecast-api:<sha>
     ```
   - Performs `/health` curl and fails deploy if unhealthy.

### Runner Secrets / Env Vars

Set in GitHub repository:

| Secret | Purpose |
|--------|---------|
| `GCP_PROJECT_ID` | Used by ETL + deployment |
| `GOOGLE_CREDENTIALS` | JSON key for BigQuery + Artifact Registry |
| `GCP_POSTGRES_CONN` | Cloud SQL connection string |
| `AZURE_POSTGRES_CONN` | Azure Postgres connection string |
| `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` | Azure Cost API auth |
| `GCP_AR_REPOSITORY`, `GCP_AR_LOCATION` | Artifact Registry details |

Optional env overrides (`SUMMARY_LOOKBACK_DAYS`, `ETL_LOOKBACK_DAYS`, `SUMMARY_PROVIDERS`, `USD_TO_INR_RATE`) control UI and ETL behavior.

---

## Model Details

- **Architecture**: [Temporal Fusion Transformer](https://arxiv.org/abs/1912.09363) via `pytorch-forecasting`.
- **Per-provider training**: separate checkpoints for GCP and Azure due to differing currencies and usage patterns.
- **Input features**:
  - Time index (`time_idx`)
  - Cost (target)
  - Categorical: provider, service, region, currency
  - TFT encoders add relative time index, scaling, encoder length flags.
- **Data conditioning**:
  - 180-day history window
  - Missing dates filled per service to ensure contiguous series
  - Padding ensures at least two timesteps per service
  - All costs normalized to INR using BigQuery currency conversion rate (GCP) or `USD_TO_INR_RATE` (Azure)
- **Training hyperparameters**:
  - `hidden_size=64`, `attention_head_size=4`, `dropout=0.2`
  - `max_encoder_length=30`, `max_prediction_length=7`
  - `GroupNormalizer` per `(provider, service)`
  - `QuantileLoss` with seven quantiles (`0.1 ... 0.9`)
  - Early stopping on `val_loss`
  - Metrics logged:
    ```
    [AZURE] Train metrics: {'final_train_loss': tensor(...), 'final_val_loss': tensor(...)}
    ```

### Inference/UI

- FastAPI loads checkpoints from `/app/model/<provider>` at startup.
- `/forecast/summary` loads recent costs directly from Postgres for each provider, runs batch inference, and aggregates weekly/monthly/yearly medians (clamped to zero).
- The UI (served from `/`) displays two cards (Azure, GCP) with ₹ projections based on the latest summary plus optional baselines (defaults to zero inflation).
- Manual forecast form + CSV upload have been removed—the dashboard focuses on the automated pipeline output.

---

## Local Development

```bash
python -m venv venv311
source venv311/bin/activate
pip install -r requirements.txt

# ETL (set connection strings before running)
ETL_LOOKBACK_DAYS=30 python ETL.py

# Training
PROVIDER_NAME=gcp POSTGRES_CONN_STR=... python -m src.training.tft

# API (requires checkpoints under artifacts/model/<provider>)
MODEL_DIR=artifacts/model uvicorn src.api.app:app --reload
```

---

## Health & Monitoring

- `/health` returns loaded providers and a boolean flag.
- `/forecast/summary` returns JSON used by the UI.
- Logs include inference warnings (`filters should not remove entries`) when source data lacks sufficient history—ETL lookback can be increased to mitigate.

---
