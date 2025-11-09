# terraform/locals.tf

locals {
  # GCP computed values
  gcp_labels = merge(
    var.common_labels,
    {
      environment = var.environment
      region      = var.gcp_region
    }
  )

  gcp_database_name = "${var.project_name}-postgres"
  gcp_models_bucket = "${var.gcp_project_id}-${var.gcp_models_bucket_name}-${var.environment}"

  # Azure computed values
  azure_tags = merge(
    var.tags,
    {
      environment = var.environment
      region      = var.azure_region
    }
  )

  # Storage account name must be 3-24 characters, lowercase, no hyphens
  azure_storage_account_name = lower(replace(
    "${var.azure_storage_account_name}${var.environment}",
    "-",
    ""
  ))

  azure_postgres_admin = "psqladmin"
  azure_postgres_fqdn  = "${var.azure_postgres_server_name}-${var.environment}.postgres.database.azure.com"
}
