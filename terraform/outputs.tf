# terraform/outputs.tf

# ============================================
# GCP Outputs
# ============================================

output "gcp_enabled" {
  description = "Whether GCP resources are enabled"
  value       = var.enable_gcp
}

output "gcp_project_id" {
  description = "GCP Project ID"
  value       = var.gcp_project_id
}

output "gcp_network_name" {
  description = "GCP VPC Network Name"
  value       = try(google_compute_network.main[0].name, null)
}

output "gcp_subnet_name" {
  description = "GCP Subnet Name"
  value       = try(google_compute_subnetwork.main[0].name, null)
}

output "gcp_database_instance_name" {
  description = "GCP CloudSQL Instance Name"
  value       = try(google_sql_database_instance.postgres[0].name, null)
}

output "gcp_database_ip_address" {
  description = "GCP CloudSQL Public IP Address"
  value       = try(google_sql_database_instance.postgres[0].public_ip_address, null)
}

output "gcp_database_connection_name" {
  description = "GCP CloudSQL Connection Name (for Cloud Proxy)"
  value       = try(google_sql_database_instance.postgres[0].connection_name, null)
}

output "gcp_database_url" {
  description = "GCP PostgreSQL Connection String"
  value       = try("postgresql://admin:${var.db_admin_password}@${google_sql_database_instance.postgres[0].public_ip_address}:5432/cloud_optimizer", null)
  sensitive   = true
}

output "gcp_models_bucket" {
  description = "GCP Storage Bucket for Models"
  value       = try(google_storage_bucket.models[0].name, null)
}

# ============================================
# Azure Outputs
# ============================================

output "azure_enabled" {
  description = "Whether Azure resources are enabled"
  value       = var.enable_azure
}

output "azure_subscription_id" {
  description = "Azure Subscription ID"
  value       = var.azure_subscription_id
  sensitive   = true
}

output "azure_resource_group_name" {
  description = "Azure Resource Group Name"
  value       = try(azurerm_resource_group.main[0].name, null)
}

output "azure_resource_group_id" {
  description = "Azure Resource Group ID"
  value       = try(azurerm_resource_group.main[0].id, null)
}

output "azure_vnet_name" {
  description = "Azure Virtual Network Name"
  value       = try(azurerm_virtual_network.main[0].name, null)
}

output "azure_subnet_name" {
  description = "Azure Subnet Name"
  value       = try(azurerm_subnet.main[0].name, null)
}

output "azure_nsg_name" {
  description = "Azure Network Security Group Name"
  value       = try(azurerm_network_security_group.main[0].name, null)
}

output "azure_postgres_server_name" {
  description = "Azure PostgreSQL Server Name"
  value       = try(azurerm_postgresql_flexible_server.postgres[0].name, null)
}

output "azure_postgres_fqdn" {
  description = "Azure PostgreSQL FQDN"
  value       = try(azurerm_postgresql_flexible_server.postgres[0].fqdn, null)
}

output "azure_database_url" {
  description = "Azure PostgreSQL Connection String"
  value       = try("postgresql://${local.azure_postgres_admin}@${azurerm_postgresql_flexible_server.postgres[0].name}:${var.db_admin_password}@${azurerm_postgresql_flexible_server.postgres[0].fqdn}:5432/cloud_optimizer?sslmode=require", null)
  sensitive   = true
}

output "azure_storage_account_name" {
  description = "Azure Storage Account Name"
  value       = try(azurerm_storage_account.models[0].name, null)
}

output "azure_storage_container_name" {
  description = "Azure Storage Container Name"
  value       = try(azurerm_storage_container.models[0].name, null)
}

output "gcp_etl_service_account_email" {
  description = "Service account email used by the GitHub Actions ETL workflow"
  value       = try(google_service_account.etl[0].email, null)
}

output "gcp_etl_service_account_key" {
  description = "Base64-encoded service account key JSON for the ETL workflow (store as a GitHub secret)"
  value       = try(google_service_account_key.etl[0].private_key, null)
  sensitive   = true
}
