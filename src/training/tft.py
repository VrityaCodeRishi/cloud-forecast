import os
from pathlib import Path

import pandas as pd
import psycopg2
import torch
from lightning.pytorch import Trainer
from lightning.pytorch.callbacks import EarlyStopping
from pytorch_forecasting import (
    GroupNormalizer,
    QuantileLoss,
    TemporalFusionTransformer,
    TimeSeriesDataSet,
)
from pytorch_forecasting.data.encoders import NaNLabelEncoder

POSTGRES_CONN_STR = os.getenv("POSTGRES_CONN_STR", "")
PROVIDER_NAME = os.getenv("PROVIDER_NAME", "gcp").lower()
MIN_SERIES_POINTS = int(os.getenv("MIN_SERIES_POINTS", "1"))
BATCH_SIZE = 64
MAX_EPOCHS = 100
MAX_ENCODER_LENGTH = 30
MAX_PREDICTION_LENGTH = 7
MODEL_FILENAME = os.getenv("MODEL_FILENAME", "tft_cost_forecast.ckpt")
MODEL_ARTIFACT_PATH = Path(
    os.getenv(
        "MODEL_ARTIFACT_PATH",
        os.path.join("artifacts", "model", PROVIDER_NAME, MODEL_FILENAME),
    )
)
MODEL_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)

if not POSTGRES_CONN_STR:
    raise ValueError("POSTGRES_CONN_STR environment variable is required for training.")

def load_data():
    query = """
    SELECT
      date,
      provider,
      service,
      cost,
      region,
      currency
    FROM daily_costs
    WHERE date >= CURRENT_DATE - INTERVAL '180 days'
    ORDER BY date ASC
    """
    conn = psycopg2.connect(POSTGRES_CONN_STR)
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def preprocess(df):
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df['time_idx'] = (df['date'] - df['date'].min()).dt.days

    # Cast categoricals as strings for TFT embeddings
    df['provider'] = df['provider'].fillna('unknown').astype(str)
    df['service'] = df['service'].fillna('unknown').astype(str)
    df['region'] = df['region'].fillna('unknown').astype(str)
    df['currency'] = df['currency'].fillna('unknown').astype(str)

    # Target should be float
    df['cost'] = df['cost'].fillna(0).astype(float)
    return df

def determine_window_lengths(df):
    total_periods = df['time_idx'].max() + 1
    prediction_length = min(MAX_PREDICTION_LENGTH, max(1, total_periods // 3))
    encoder_length = min(MAX_ENCODER_LENGTH, max(2, total_periods - prediction_length - 1))
    encoder_length = min(encoder_length, max(1, total_periods - 1))
    # ensure encoder length stays larger than prediction horizon
    if encoder_length <= prediction_length:
        encoder_length = prediction_length + 1
    return int(encoder_length), int(prediction_length)


def _pad_short_series(df, min_points=2):
    additions = []
    group_cols = ['provider', 'service']
    date_col = 'date'
    time_col = 'time_idx'
    for _, group in df.groupby(group_cols):
        if len(group) >= min_points:
            continue
        needed = min_points - len(group)
        first_row = group.iloc[0].copy()
        for i in range(needed):
            new_row = first_row.copy()
            if date_col in new_row:
                new_row[date_col] = new_row[date_col] - pd.Timedelta(days=i + 1)
            if time_col in new_row:
                new_row[time_col] = new_row[time_col] - (i + 1)
            additions.append(new_row)
    if additions:
        df = pd.concat([df, pd.DataFrame(additions)], ignore_index=True)
    return df


def _fill_missing_dates(df):
    frames = []
    for (provider, service), group in df.groupby(['provider', 'service']):
        group = group.sort_values('date')
        all_dates = pd.date_range(group['date'].min(), group['date'].max(), freq='D')
        expanded = group.set_index('date').reindex(all_dates).reset_index().rename(columns={'index': 'date'})
        expanded['provider'] = provider
        expanded['service'] = service
        for col in ['region', 'currency']:
            if col in expanded:
                expanded[col] = expanded[col].ffill().bfill().fillna('unknown')
        expanded['cost'] = expanded['cost'].fillna(0.0)
        frames.append(expanded)
    result = pd.concat(frames, ignore_index=True)
    result['date'] = pd.to_datetime(result['date'])
    result = result.sort_values('date')
    result['time_idx'] = (result['date'] - result['date'].min()).dt.days
    return result


def create_datasets(df):
    encoder_length, prediction_length = determine_window_lengths(df)
    training_cutoff = df['time_idx'].max() - prediction_length
    min_series_length = encoder_length + prediction_length

    counts = (
        df.groupby(['provider', 'service'])
        .size()
        .reset_index(name='num_points')
    )
    max_points = counts['num_points'].max()
    if pd.isna(max_points) or max_points <= 0:
        raise ValueError(f"[{PROVIDER_NAME.upper()}] No historical points available to train.")

    max_points = int(max_points)
    effective_min_series_length = min(min_series_length, max_points)
    if max_points >= MIN_SERIES_POINTS:
        effective_min_series_length = max(MIN_SERIES_POINTS, effective_min_series_length)
    else:
        effective_min_series_length = max_points

    effective_min_series_length = max(1, effective_min_series_length)
    keep = counts[counts['num_points'] >= effective_min_series_length][['provider', 'service']]
    df_filtered = df.merge(keep, on=['provider', 'service'], how='inner')

    if df_filtered.empty:
        raise ValueError(
            f"[{PROVIDER_NAME.upper()}] Not enough history per service to train TFT. "
            f"Need at least {effective_min_series_length} points per service."
        )

    df_filtered = _fill_missing_dates(df_filtered)

    series_lengths = (
        df_filtered.groupby(['provider', 'service'])
        .size()
        .reset_index(name='num_points')
    )
    shortest_series = int(series_lengths['num_points'].min())
    if shortest_series < 2:
        df_filtered = _pad_short_series(df_filtered, min_points=2)
        series_lengths = (
            df_filtered.groupby(['provider', 'service'])
            .size()
            .reset_index(name='num_points')
        )
        shortest_series = int(series_lengths['num_points'].min())

    if shortest_series <= prediction_length:
        prediction_length = max(1, shortest_series - 1)
    max_encoder_allowed = max(1, shortest_series - prediction_length)
    encoder_length = min(encoder_length, max_encoder_allowed)
    if encoder_length + prediction_length > shortest_series:
        prediction_length = max(1, shortest_series - encoder_length)

    max_time = df_filtered['time_idx'].max()
    min_time = df_filtered['time_idx'].min()
    training_cutoff = max_time - prediction_length
    if training_cutoff <= min_time:
        training_cutoff = max_time

    training_df = df_filtered[df_filtered.time_idx <= training_cutoff].copy()
    if training_df.empty:
        training_df = df_filtered.copy()

    training = TimeSeriesDataSet(
        training_df,
        time_idx='time_idx',
        target='cost',
        group_ids=['provider', 'service'],
        max_encoder_length=encoder_length,
        max_prediction_length=prediction_length,
        min_encoder_length=1,
        min_prediction_length=1,
        time_varying_known_categoricals=['provider', 'service', 'region', 'currency'],
        time_varying_unknown_reals=['cost'],
        target_normalizer=GroupNormalizer(groups=["provider", "service"]),
        add_relative_time_idx=True,
        add_target_scales=True,
        add_encoder_length=True,
        categorical_encoders={
            'provider': NaNLabelEncoder(add_nan=True),
            'service': NaNLabelEncoder(add_nan=True),
            'region': NaNLabelEncoder(add_nan=True),
            'currency': NaNLabelEncoder(add_nan=True),
        },
        allow_missing_timesteps=True,
    )

    validation = TimeSeriesDataSet.from_dataset(
        training,
        df_filtered,
        predict=True,
        stop_randomization=True,
        allow_missing_timesteps=True,
    )

    return training, validation

def train_model(training, validation):
    train_dataloader = training.to_dataloader(train=True, batch_size=BATCH_SIZE, num_workers=8)
    val_dataloader = validation.to_dataloader(train=False, batch_size=BATCH_SIZE, num_workers=8)

    # Prefer GPU if available, otherwise fall back to CPU
    accelerator = "gpu" if torch.cuda.is_available() else "cpu"
    devices = 1

    tft = TemporalFusionTransformer.from_dataset(
        training,
        learning_rate=0.01,
        hidden_size=64,
        attention_head_size=4,
        dropout=0.2,
        hidden_continuous_size=16,
        output_size=7,  # quantiles
        loss=QuantileLoss(),
        reduce_on_plateau_patience=5,
    )
    trainer = Trainer(
        max_epochs=MAX_EPOCHS,
        accelerator=accelerator,
        devices=devices,
        gradient_clip_val=0.1,
        callbacks=[EarlyStopping(monitor="val_loss", patience=10, mode="min")],
        limit_train_batches=1.0,
    )

    trainer.fit(tft, train_dataloader, val_dataloader)
    trainer.save_checkpoint(str(MODEL_ARTIFACT_PATH))
    metrics = {
        "final_train_loss": trainer.callback_metrics.get("train_loss")
        if trainer.callback_metrics
        else None,
        "final_val_loss": trainer.logged_metrics.get("val_loss")
        if trainer.logged_metrics
        else None,
    }
    print(
        f"[{PROVIDER_NAME.upper()}] Training complete. Model checkpoint saved to {MODEL_ARTIFACT_PATH}."
    )
    print(f"[{PROVIDER_NAME.upper()}] Train metrics: {metrics}")

    return tft, trainer

def main():
    df = load_data()
    df = preprocess(df)
    training, validation = create_datasets(df)
    model, trainer = train_model(training, validation)

if __name__ == "__main__":
    main()
