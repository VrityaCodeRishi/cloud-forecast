gcloud services enable compute.googleapis.com
gcloud services enable container.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable bigquery.googleapis.com
gcloud services enable cloudresourcemanager.googleapis.com

gcloud iam service-accounts create terraform \
  --display-name="Terraform automation"


gcloud projects add-iam-policy-binding buoyant-episode-386713 \
  --member=serviceAccount:terraform@buoyant-episode-386713.iam.gserviceaccount.com \
  --role=roles/editor

gcloud iam service-accounts keys create terraform-key.json \
  --iam-account=terraform@buoyant-episode-386713.iam.gserviceaccount.com

