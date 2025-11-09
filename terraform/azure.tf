locals {
  create_azure = var.enable_azure
}

resource "azurerm_resource_group" "main" {
  count    = local.create_azure ? 1 : 0
  name     = var.azure_resource_group_name
  location = var.azure_region

  tags = local.azure_tags
}

resource "azurerm_virtual_network" "main" {
  count               = local.create_azure ? 1 : 0
  name                = var.azure_vnet_name
  address_space       = [var.azure_vnet_cidr]
  location            = azurerm_resource_group.main[0].location
  resource_group_name = azurerm_resource_group.main[0].name

  tags = local.azure_tags
}

resource "azurerm_subnet" "main" {
  count                = local.create_azure ? 1 : 0
  name                 = var.azure_subnet_name
  resource_group_name  = azurerm_resource_group.main[0].name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = [var.azure_subnet_cidr]
}

resource "azurerm_network_security_group" "main" {
  count               = local.create_azure ? 1 : 0
  name                = var.azure_nsg_name
  location            = azurerm_resource_group.main[0].location
  resource_group_name = azurerm_resource_group.main[0].name

  security_rule {
    name                       = "AllowSSH"
    priority                   = 1001
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowAPI"
    priority                   = 1002
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8000"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  tags = local.azure_tags
}

resource "azurerm_postgresql_flexible_server" "postgres" {
  count               = local.create_azure ? 1 : 0
  name                = "${var.azure_postgres_server_name}-${var.environment}"
  location            = azurerm_resource_group.main[0].location
  resource_group_name = azurerm_resource_group.main[0].name

  administrator_login    = local.azure_postgres_admin
  administrator_password = var.db_admin_password

  sku_name                      = var.azure_postgres_sku
  version                       = var.azure_postgres_version
  storage_mb                    = var.azure_postgres_storage_mb
  backup_retention_days         = var.azure_postgres_backup_retention
  geo_redundant_backup_enabled  = false
  auto_grow_enabled             = true
  public_network_access_enabled = true

  authentication {
    password_auth_enabled = true
  }

  tags = local.azure_tags
}

resource "azurerm_postgresql_flexible_server_database" "database" {
  count     = local.create_azure ? 1 : 0
  name      = "cloud_optimizer"
  server_id = azurerm_postgresql_flexible_server.postgres[0].id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  count            = local.create_azure ? 1 : 0
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.postgres[0].id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_all" {
  count            = local.create_azure ? 1 : 0
  name             = "AllowAllIPs"
  server_id        = azurerm_postgresql_flexible_server.postgres[0].id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "255.255.255.255"
}

resource "azurerm_storage_account" "models" {
  count                      = local.create_azure ? 1 : 0
  name                       = local.azure_storage_account_name
  resource_group_name        = azurerm_resource_group.main[0].name
  location                   = azurerm_resource_group.main[0].location
  account_tier               = "Standard"
  account_replication_type   = "LRS"
  https_traffic_only_enabled = true

  tags = local.azure_tags
}

resource "azurerm_storage_container" "models" {
  count                 = local.create_azure ? 1 : 0
  name                  = var.azure_storage_container_name
  storage_account_name  = azurerm_storage_account.models[0].name
  container_access_type = "private"
}
