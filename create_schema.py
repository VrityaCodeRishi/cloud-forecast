import psycopg2
from psycopg2 import sql
import os

GCP_DB_HOST = os.getenv('GCP_DB_HOST', '34.122.18.117')
GCP_DB_PORT = os.getenv('GCP_DB_PORT', '5432')
GCP_DB_NAME = os.getenv('GCP_DB_NAME', 'cloud_optimizer')
GCP_DB_USER = os.getenv('GCP_DB_USER', 'admin')
GCP_DB_PASSWORD = os.getenv('GCP_DB_PASSWORD', 'Admin123456!')
AZURE_DB_HOST = os.getenv('AZURE_DB_HOST', '20.184.145.34')
AZURE_DB_PORT = os.getenv('AZURE_DB_PORT', '5432')
AZURE_DB_NAME = os.getenv('AZURE_DB_NAME', 'cloud_optimizer')
AZURE_DB_USER = os.getenv('AZURE_DB_USER', 'psqladmin')
AZURE_DB_PASSWORD = os.getenv('AZURE_DB_PASSWORD', 'Admin123456!')

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS daily_costs (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    provider VARCHAR(16) NOT NULL,
    service VARCHAR(128),
    cost NUMERIC(18,4),
    region VARCHAR(64),
    currency VARCHAR(16),
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT daily_costs_unique UNIQUE (date, provider, service)
);

CREATE INDEX IF NOT EXISTS idx_daily_costs_date ON daily_costs(date);
CREATE INDEX IF NOT EXISTS idx_daily_costs_provider ON daily_costs(provider);
CREATE INDEX IF NOT EXISTS idx_daily_costs_service ON daily_costs(service);
CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_costs_date_provider_service ON daily_costs(date, provider, service);

CREATE TABLE IF NOT EXISTS resource_usage (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    provider VARCHAR(16) NOT NULL,
    service VARCHAR(128),
    resource_type VARCHAR(64),
    usage_amount DOUBLE PRECISION,
    unit VARCHAR(32),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_resource_usage_timestamp ON resource_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_resource_usage_provider ON resource_usage(provider);

CREATE TABLE IF NOT EXISTS model_metadata (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(64) NOT NULL,
    version VARCHAR(32) NOT NULL,
    trained_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    val_rmse DOUBLE PRECISION,
    val_mae DOUBLE PRECISION,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_model_metadata_name_version ON model_metadata(model_name, version);
"""

def create_tables_for_db(host, port, dbname, user, password, db_label):
    try:
        print(f"Connecting to {db_label} database at {host}...")
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(CREATE_TABLES_SQL)
        print(f"Schema created successfully in {db_label}.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error creating tables in {db_label}: {e}")

if __name__ == "__main__":
    # Create schema in GCP PostgreSQL
    create_tables_for_db(GCP_DB_HOST, GCP_DB_PORT, GCP_DB_NAME, GCP_DB_USER, GCP_DB_PASSWORD, "GCP PostgreSQL")
    
    # Create schema in Azure PostgreSQL
    create_tables_for_db(AZURE_DB_HOST, AZURE_DB_PORT, AZURE_DB_NAME, AZURE_DB_USER, AZURE_DB_PASSWORD, "Azure PostgreSQL")
