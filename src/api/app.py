import os
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import torch
import psycopg2
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI()

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATE_DIR)

MODEL_ROOT = Path(os.getenv("MODEL_DIR", "artifacts/model"))
MODEL_CHECKPOINTS_ENV = os.getenv("MODEL_CHECKPOINTS")
SINGLE_CHECKPOINT_ENV = os.getenv("MODEL_CHECKPOINT")
DEFAULT_MODEL_FILENAME = "tft_cost_forecast.ckpt"
MODEL_DISCOVERY_REQUIRED = os.getenv("MODEL_REQUIRED", "1").lower() not in {"0", "false"}
SUMMARY_LOOKBACK_DAYS = int(os.getenv("SUMMARY_LOOKBACK_DAYS", "30"))
PROVIDER_CONNECTIONS = {
    "gcp": os.getenv("GCP_POSTGRES_CONN"),
    "azure": os.getenv("AZURE_POSTGRES_CONN"),
}


def _discover_model_paths() -> Dict[str, Path]:
    paths: Dict[str, Path] = {}

    if MODEL_CHECKPOINTS_ENV:
        entries = [item.strip() for item in MODEL_CHECKPOINTS_ENV.split(",") if item.strip()]
        for entry in entries:
            if "=" not in entry:
                continue
            provider, resolved_path = entry.split("=", 1)
            candidate = Path(resolved_path.strip())
            if candidate.exists():
                paths[provider.strip().lower()] = candidate

    if not paths and MODEL_ROOT.exists():
        for provider_dir in MODEL_ROOT.iterdir():
            if not provider_dir.is_dir():
                continue
            candidate = provider_dir / DEFAULT_MODEL_FILENAME
            if candidate.exists():
                paths[provider_dir.name.lower()] = candidate

    if not paths:
        fallback_path = Path(SINGLE_CHECKPOINT_ENV) if SINGLE_CHECKPOINT_ENV else Path(DEFAULT_MODEL_FILENAME)
        if fallback_path.exists():
            paths["default"] = fallback_path

    if not paths and MODEL_DISCOVERY_REQUIRED:
        raise FileNotFoundError("No model checkpoints found in MODEL_DIR or via MODEL_CHECKPOINT env vars.")

    return paths


MODEL_PATHS: Dict[str, Path] = {}
MODEL_REGISTRY: Dict[str, TemporalFusionTransformer] = {}
try:
    MODEL_PATHS = _discover_model_paths()
except FileNotFoundError as exc:
    if MODEL_DISCOVERY_REQUIRED:
        raise
    print(f"[API] Warning: {exc}. API will start without loaded models.")
else:
    for provider, checkpoint_path in MODEL_PATHS.items():
        MODEL_REGISTRY[provider] = TemporalFusionTransformer.load_from_checkpoint(checkpoint_path)
        MODEL_REGISTRY[provider].eval()


class ForecastRequest(BaseModel):
    provider: str
    service: str
    region: str
    currency: str
    recent_costs: list[float]
    time_idx_start: int


def preprocess_input(request: ForecastRequest, model: TemporalFusionTransformer):
    df = pd.DataFrame({
        "provider": [request.provider] * len(request.recent_costs),
        "service": [request.service] * len(request.recent_costs),
        "region": [request.region] * len(request.recent_costs),
        "currency": [request.currency] * len(request.recent_costs),
        "time_idx": list(range(request.time_idx_start, request.time_idx_start + len(request.recent_costs))),
        "cost": request.recent_costs,
    })

    dataset_params = getattr(model.hparams, "dataset_parameters", None)
    if not dataset_params:
        raise ValueError("Model checkpoint is missing dataset parameters; cannot build inference dataset.")

    updated_params = {**dataset_params, "max_encoder_length": len(request.recent_costs)}
    dataset = TimeSeriesDataSet.from_parameters(
        updated_params,
        df,
        predict=True,
        stop_randomization=True,
    )
    return dataset.to_dataloader(batch_size=1, train=False)


def _get_quantile_index(model: TemporalFusionTransformer, quantile: float = 0.5) -> int:
    quantiles = getattr(getattr(model, "loss", None), "quantiles", None)
    if quantiles and quantile in quantiles:
        return quantiles.index(quantile)
    if quantiles:
        return len(quantiles) // 2
    # default to middle
    return 0


def _load_recent_costs(provider: str, lookback_days: int) -> pd.DataFrame:
    conn_str = PROVIDER_CONNECTIONS.get(provider)
    if not conn_str:
        raise ValueError(f"No database connection configured for provider '{provider}'.")
    query = """
        SELECT service, region, currency, date, cost
        FROM daily_costs
        WHERE provider = %(provider)s
          AND date >= CURRENT_DATE - %(days)s * INTERVAL '1 day'
        ORDER BY service, date
    """
    with psycopg2.connect(conn_str) as conn:
        df = pd.read_sql(query, conn, params={"provider": provider, "days": lookback_days})
    return df


def _build_request_from_series(provider: str, service: str, region: str, currency: str, costs: List[float], max_encoder: int) -> ForecastRequest:
    recent = costs[-max_encoder:]
    return ForecastRequest(
        provider=provider,
        service=service,
        region=region or "unknown",
        currency=currency or "USD",
        recent_costs=recent,
        time_idx_start=0,
    )


def _summarize_provider(provider: str, model: TemporalFusionTransformer, lookback_days: int) -> Dict:
    if provider not in PROVIDER_CONNECTIONS or not PROVIDER_CONNECTIONS[provider]:
        return {}
    try:
        df = _load_recent_costs(provider, lookback_days)
    except Exception as exc:
        print(f"[API] Failed to load recent costs for {provider}: {exc}")
        return {}

    if df.empty:
        return {}

    dataset_params = getattr(model.hparams, "dataset_parameters", {}) or {}
    max_encoder = dataset_params.get("max_encoder_length", len(df))
    quantile_idx = _get_quantile_index(model, 0.5)

    provider_weekly = 0.0
    provider_monthly = 0.0
    provider_yearly = 0.0
    service_details = []

    grouped = df.groupby(["service", "region", "currency"], dropna=False)
    for (service, region, currency), service_df in grouped:
        service_df = service_df.sort_values("date")
        costs = service_df["cost"].astype(float).tolist()
        if len(costs) < 2:
            continue
        try:
            request = _build_request_from_series(provider, service or "unknown", region or "unknown", currency or "USD", costs, max_encoder)
            dataloader = preprocess_input(request, model)
            preds = model.predict(dataloader, mode="quantiles")
            median = preds[0, :, quantile_idx].tolist()
        except Exception as exc:
            print(f"[API] Forecast failed for {provider}/{service}: {exc}")
            continue

        horizon_days = max(1, len(median))
        weekly = sum(median)
        daily_avg = weekly / horizon_days
        monthly = daily_avg * 30
        yearly = monthly * 12

        provider_weekly += weekly
        provider_monthly += monthly
        provider_yearly += yearly

        service_details.append({
            "service": service or "unknown",
            "region": region or "unknown",
            "currency": currency or "USD",
            "weekly": weekly,
            "monthly": monthly,
            "yearly": yearly,
        })

    if not service_details:
        return {}

    return {
        "weekly": provider_weekly,
        "monthly": provider_monthly,
        "yearly": provider_yearly,
        "services": service_details,
    }


@app.get("/health")
async def health():
    status = {
        "providers": sorted(MODEL_REGISTRY.keys()),
        "models_loaded": bool(MODEL_REGISTRY),
    }
    return status


@app.post("/forecast")
async def forecast(request: ForecastRequest):
    provider_key = request.provider.lower()
    model = MODEL_REGISTRY.get(provider_key) or MODEL_REGISTRY.get("default")
    if not model:
        raise HTTPException(status_code=404, detail=f"No model available for provider '{request.provider}'.")

    try:
        dataloader = preprocess_input(request, model)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with torch.no_grad():
        preds = model.predict(dataloader, mode="quantiles")

    quantiles = ["0.1", "0.5", "0.9"]
    pred_list = []
    for i, q in enumerate(quantiles):
        pred_list.append((q, preds[0, :, i].tolist()))

    return {"forecast": dict(pred_list)}


@app.get("/providers")
async def list_providers():
    return {"providers": sorted(MODEL_REGISTRY.keys())}


@app.get("/forecast/summary")
async def forecast_summary(lookback_days: int = SUMMARY_LOOKBACK_DAYS):
    results = {}
    for provider, model in MODEL_REGISTRY.items():
        summary = _summarize_provider(provider, model, lookback_days)
        if summary:
            results[provider] = summary

    if not results:
        raise HTTPException(status_code=503, detail="No provider summaries available.")

    return {
        "providers": results,
        "lookback_days": lookback_days,
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    provider_list = sorted(MODEL_REGISTRY.keys())
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "providers": provider_list,
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
