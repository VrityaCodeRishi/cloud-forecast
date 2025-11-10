variable "gcp_project_id" {
  description = "GCP Project ID"
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.gcp_project_id))
    error_message = "GCP project ID must be lowercase with hyphens, 6-30 characters."
  }
}

variable "gcp_region" {
  description = "GCP region for resources"
  type        = string
  default     = "us-central1"
}

variable "gcp_zone" {
  description = "GCP zone for zonal resources"
  type        = string
  default     = "us-central1-a"
}

variable "gcp_credentials_path" {
  description = "Path to GCP service account credentials JSON"
  type        = string
  default     = "~/.config/gcloud/application_default_credentials.json"
}

variable "gcp_database_instance_name" {
  description = "GCP Cloud SQL instance name"
  type        = string
  default     = "cloud-cost-postgres"
}

variable "gcp_database_tier" {
  description = "GCP Cloud SQL machine type (tier)"
  type        = string
  default     = "db-custom-2-8192"
  validation {
    condition     = can(regex("^db-", var.gcp_database_tier))
    error_message = "Must be a valid Cloud SQL tier."
  }
}

variable "gcp_database_version" {
  description = "PostgreSQL version"
  type        = string
  default     = "POSTGRES_15"
}

variable "gcp_database_disk_size" {
  description = "GCP Cloud SQL disk size in GB"
  type        = number
  default     = 100
  validation {
    condition     = var.gcp_database_disk_size >= 10
    error_message = "Minimum disk size is 10GB."
  }
}

variable "gcp_database_backup_retention" {
  description = "Number of days to retain backups"
  type        = number
  default     = 7
}

variable "gcp_vpc_network_name" {
  description = "GCP VPC network name"
  type        = string
  default     = "cloud-cost-optimizer-vpc"
}

variable "gcp_subnet_name" {
  description = "GCP subnet name"
  type        = string
  default     = "cloud-cost-optimizer-subnet"
}

variable "gcp_subnet_cidr" {
  description = "GCP subnet CIDR block"
  type        = string
  default     = "10.0.1.0/24"
}

variable "gcp_models_bucket_name" {
  description = "GCP Storage bucket name for models"
  type        = string
  default     = "cloud-cost-models"
}

variable "gcp_artifact_repository_id" {
  description = "Artifact Registry repository ID (will be suffixed with environment)"
  type        = string
  default     = "cost-forecast-api"
}

variable "gcp_artifact_location" {
  description = "Region for the Artifact Registry (defaults to gcp_region)"
  type        = string
  default     = "us-central1"
}

variable "gcp_billing_dataset_id" {
  description = "Existing BigQuery dataset ID that stores billing export tables"
  type        = string
  default     = "all_billing_data"
}

variable "gcp_enable_backup" {
  description = "Enable automated backups for Cloud SQL"
  type        = bool
  default     = true
}


# ============================================
# Azure Variables
# ============================================

variable "azure_subscription_id" {
  description = "Azure subscription ID"
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", lower(var.azure_subscription_id)))
    error_message = "Must be a valid Azure subscription ID (UUID format)."
  }
}

variable "azure_client_id" {
  description = "Azure service principal client ID"
  type        = string
  sensitive   = true
}

variable "azure_client_secret" {
  description = "Azure service principal client secret"
  type        = string
  sensitive   = true
}

variable "azure_tenant_id" {
  description = "Azure tenant ID"
  type        = string
  sensitive   = true
}

variable "azure_region" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "azure_resource_group_name" {
  description = "Azure resource group name"
  type        = string
  default     = "cloud-cost-optimizer-rg"
}

variable "azure_vnet_name" {
  description = "Azure Virtual Network name"
  type        = string
  default     = "cloud-cost-vnet"
}

variable "azure_vnet_cidr" {
  description = "Azure VNet address space"
  type        = string
  default     = "10.1.0.0/16"
}

variable "azure_subnet_name" {
  description = "Azure subnet name"
  type        = string
  default     = "cloud-cost-subnet"
}

variable "azure_subnet_cidr" {
  description = "Azure subnet address space"
  type        = string
  default     = "10.1.1.0/24"
}

variable "azure_nsg_name" {
  description = "Azure Network Security Group name"
  type        = string
  default     = "cloud-cost-nsg"
}

variable "azure_postgres_server_name" {
  description = "Azure PostgreSQL server name"
  type        = string
  default     = "cloud-cost-postgres"
}

variable "azure_postgres_sku" {
  description = "Azure PostgreSQL SKU"
  type        = string
  default     = "B_Standard_B1ms"
  validation {
    condition     = can(regex("^(B|GP|MO)_[A-Za-z0-9_]+$", var.azure_postgres_sku))
    error_message = "Use a valid Flexible Server SKU such as B_Standard_B1ms or GP_Standard_D2s_v3."
  }
}

variable "azure_postgres_version" {
  description = "PostgreSQL version on Azure"
  type        = string
  default     = "15"
}

variable "azure_postgres_storage_mb" {
  description = "Azure PostgreSQL storage in MB"
  type        = number
  default     = 131072 # 128GB (valid increment)
  validation {
    condition     = contains([32768, 65536, 131072, 262144, 524288, 1048576, 2097152, 4193280, 4194304, 8388608, 16777216, 33553408], var.azure_postgres_storage_mb)
    error_message = "Storage must be one of the supported sizes (e.g., 32768, 65536, 131072 MB, ...)."
  }
}

variable "azure_postgres_backup_retention" {
  description = "Backup retention days for Azure PostgreSQL"
  type        = number
  default     = 7
}

variable "azure_storage_account_name" {
  description = "Azure storage account name prefix"
  type        = string
  default     = "ccoptmodels"
}

variable "azure_storage_container_name" {
  description = "Azure storage container name"
  type        = string
  default     = "models"
}

# ============================================
# Common Variables
# ============================================

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Must be dev, staging, or prod."
  }
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "cloud-cost-optimizer"
}

variable "db_admin_password" {
  description = "Database admin password for both GCP and Azure"
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.db_admin_password) >= 12
    error_message = "Password must be at least 12 characters."
  }
}

variable "common_labels" {
  description = "Common labels for all resources"
  type        = map(string)
  default = {
    project    = "cloud-cost-optimizer"
    terraform  = "true"
    managed_by = "terraform"
  }
}

variable "tags" {
  description = "Tags for Azure resources"
  type        = map(string)
  default = {
    project    = "cloud-cost-optimizer"
    terraform  = "true"
    managed_by = "terraform"
  }
}

variable "enable_gcp" {
  description = "Enable GCP resources"
  type        = bool
  default     = true
}

variable "enable_azure" {
  description = "Enable Azure resources"
  type        = bool
  default     = true
}
