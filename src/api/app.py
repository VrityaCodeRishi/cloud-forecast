import os
from pathlib import Path
from typing import Dict

import pandas as pd
import torch
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
