locals {
  create_gcp = var.enable_gcp
}

resource "google_compute_network" "main" {
  count                   = local.create_gcp ? 1 : 0
  name                    = var.gcp_vpc_network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  count         = local.create_gcp ? 1 : 0
  name          = var.gcp_subnet_name
  ip_cidr_range = var.gcp_subnet_cidr
  network       = google_compute_network.main[0].id
  region        = var.gcp_region
}


resource "google_compute_firewall" "allow_ssh" {
  count    = local.create_gcp ? 1 : 0
  name     = "${var.project_name}-allow-ssh"
  network  = google_compute_network.main[0].name
  priority = 1000

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
}

resource "google_compute_firewall" "allow_api" {
  count    = local.create_gcp ? 1 : 0
  name     = "${var.project_name}-allow-api"
  network  = google_compute_network.main[0].name
  priority = 1001

  allow {
    protocol = "tcp"
    ports    = ["8000"]
  }

  source_ranges = ["0.0.0.0/0"]
}


resource "google_sql_database_instance" "postgres" {
  count               = local.create_gcp ? 1 : 0
  name                = "${var.gcp_database_instance_name}-${var.environment}"
  database_version    = var.gcp_database_version
  region              = var.gcp_region
  deletion_protection = false

  settings {
    tier              = var.gcp_database_tier
    availability_type = "REGIONAL"
    disk_size         = var.gcp_database_disk_size
    disk_type         = "PD_SSD"
    user_labels       = local.gcp_labels

    backup_configuration {
      enabled                        = var.gcp_enable_backup
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = var.gcp_database_backup_retention
    }

    # IP Configuration
    ip_configuration {
      ipv4_enabled                                  = true
      enable_private_path_for_google_cloud_services = false
      require_ssl                                   = false

      authorized_networks {
        name  = "all"
        value = "0.0.0.0/0" # Restrict to specific IPs in production
      }
    }

    # Database flags
    database_flags {
      name  = "max_connections"
      value = "100"
    }

    insights_config {
      query_insights_enabled = false
    }

    location_preference {
      zone = var.gcp_zone
    }
  }

}

resource "google_sql_database" "database" {
  count    = local.create_gcp ? 1 : 0
  name     = "cloud_optimizer"
  instance = google_sql_database_instance.postgres[0].name
  charset  = "UTF8"
}

resource "google_sql_user" "admin" {
  count    = local.create_gcp ? 1 : 0
  name     = "admin"
  instance = google_sql_database_instance.postgres[0].name
  password = var.db_admin_password
}

resource "google_storage_bucket" "models" {
  count         = local.create_gcp ? 1 : 0
  name          = local.gcp_models_bucket
  location      = var.gcp_region
  force_destroy = true

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      num_newer_versions = 5
    }
  }

  labels = local.gcp_labels
}

resource "google_artifact_registry_repository" "docker" {
  count         = local.create_gcp ? 1 : 0
  location      = var.gcp_artifact_location
  repository_id = local.gcp_artifact_repository
  format        = "DOCKER"
  description   = "Container images for ${var.project_name}"
  labels        = local.gcp_labels
}

# Service account for GitHub Actions ETL pipeline
resource "google_service_account" "etl" {
  count        = local.create_gcp ? 1 : 0
  account_id   = "${var.project_name}-etl"
  display_name = "GitHub Actions ETL"
}

resource "google_project_iam_member" "etl_bigquery_job" {
  count   = local.create_gcp ? 1 : 0
  project = var.gcp_project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.etl[0].email}"
}

resource "google_project_iam_member" "etl_bigquery_viewer" {
  count   = local.create_gcp ? 1 : 0
  project = var.gcp_project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.etl[0].email}"
}

resource "google_bigquery_dataset_iam_member" "etl_dataset_viewer" {
  count      = local.create_gcp ? 1 : 0
  project    = var.gcp_project_id
  dataset_id = var.gcp_billing_dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.etl[0].email}"
}

resource "google_service_account_key" "etl" {
  count              = local.create_gcp ? 1 : 0
  service_account_id = google_service_account.etl[0].name
}

resource "google_artifact_registry_repository_iam_member" "etl_writer" {
  count      = local.create_gcp ? 1 : 0
  project    = var.gcp_project_id
  location   = var.gcp_artifact_location
  repository = google_artifact_registry_repository.docker[0].repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.etl[0].email}"
}
