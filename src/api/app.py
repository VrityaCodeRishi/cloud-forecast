import os
from pathlib import Path

import pandas as pd
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet

app = FastAPI()

_env_checkpoint = os.getenv("MODEL_CHECKPOINT")
default_path = Path("artifacts/model/tft_cost_forecast.ckpt")
fallback_path = Path("tft_cost_forecast.ckpt")
MODEL_CHECKPOINT = Path(_env_checkpoint) if _env_checkpoint else default_path
if not MODEL_CHECKPOINT.exists():
    MODEL_CHECKPOINT = fallback_path if fallback_path.exists() else MODEL_CHECKPOINT

if not MODEL_CHECKPOINT.exists():
    raise FileNotFoundError(f"Model checkpoint not found at {MODEL_CHECKPOINT}")

# Load the trained TFT model
model = TemporalFusionTransformer.load_from_checkpoint(MODEL_CHECKPOINT)
model.eval()

# Example input schema
class ForecastRequest(BaseModel):
    provider: str
    service: str
    region: str
    currency: str
    recent_costs: list[float]  # Length should match max_encoder_length (e.g. 30)
    time_idx_start: int       # The time_idx of the first element in recent_costs

def preprocess_input(request: ForecastRequest):
    # Create dataframe matching training format for 1 sample
    df = pd.DataFrame({
        "provider": [request.provider] * len(request.recent_costs),
        "service": [request.service] * len(request.recent_costs),
        "region": [request.region] * len(request.recent_costs),
        "currency": [request.currency] * len(request.recent_costs),
        "time_idx": list(range(request.time_idx_start, request.time_idx_start + len(request.recent_costs))),
        "cost": request.recent_costs
    })

    dataset_params = getattr(model.hparams, "dataset_parameters", None)
    if not dataset_params:
        raise ValueError("Model checkpoint is missing dataset parameters; cannot build inference dataset.")

    # Ensure encoder window matches the request length
    dataset_params = {**dataset_params, "max_encoder_length": len(request.recent_costs)}
    dataset = TimeSeriesDataSet.from_parameters(
        dataset_params,
        df,
        predict=True,
        stop_randomization=True,
    )
    return dataset.to_dataloader(batch_size=1, train=False)

@app.post("/forecast")
async def forecast(request: ForecastRequest):
    try:
        dataloader = preprocess_input(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with torch.no_grad():
        preds = model.predict(dataloader, mode="quantiles")

    # preds shape: [batch_size, prediction_length, num_quantiles]
    quantiles = ["0.1", "0.5", "0.9"]
    pred_list = []
    for i, q in enumerate(quantiles):
        pred_list.append((q, preds[0, :, i].tolist()))

    return {"forecast": dict(pred_list)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
