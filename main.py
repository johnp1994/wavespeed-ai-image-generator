import asyncio
import os
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WAVESPEED_API_KEY = os.environ.get("WAVESPEED_API_KEY", "")
SUBMIT_URL = "https://api.wavespeed.ai/api/v3/google/nano-banana-pro/text-to-image"
RESULT_URL_TEMPLATE = "https://api.wavespeed.ai/api/v3/predictions/{prediction_id}/result"
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL_SECONDS", "2"))
POLL_TIMEOUT = float(os.environ.get("POLL_TIMEOUT_SECONDS", "300"))

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="WaveSpeed AI Image Generator",
    description="Submits image generation jobs to WaveSpeed AI and returns when ALL are complete.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    prompts: list[str] = Field(..., min_length=1, description="One or more text prompts")
    seed: int = Field(-1, description="RNG seed, -1 for random")
    size: str = Field("1024*1024", description="Output image size, e.g. '1024*1024'")


class ImageResult(BaseModel):
    prompt: str
    status: str          # "completed" | "failed" | "timeout"
    urls: list[str] = []
    error: Optional[str] = None


class GenerateResponse(BaseModel):
    results: list[ImageResult]


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------
def _headers() -> dict:
    if not WAVESPEED_API_KEY:
        raise HTTPException(status_code=500, detail="WAVESPEED_API_KEY environment variable is not set.")
    return {
        "Authorization": f"Bearer {WAVESPEED_API_KEY}",
        "Content-Type": "application/json",
    }


async def _submit_job(client: httpx.AsyncClient, prompt: str, seed: int, size: str) -> str:
    """Submit a single image generation job and return its prediction ID."""
    payload = {
        "enable_base64_output": False,
        "enable_sync_mode": False,
        "prompt": prompt,
        "seed": seed,
        "size": size,
    }
    logger.info("Submitting job for prompt: %s", prompt[:80])
    resp = await client.post(SUBMIT_URL, json=payload, headers=_headers())
    resp.raise_for_status()
    data = resp.json()
    prediction_id = data["data"]["id"]
    logger.info("Job submitted. prediction_id=%s", prediction_id)
    return prediction_id


async def _poll_until_done(client: httpx.AsyncClient, prediction_id: str) -> dict:
    """
    Poll the result endpoint every POLL_INTERVAL seconds until the job is
    completed or failed, or until POLL_TIMEOUT seconds have elapsed.

    Returns the final result dict from WaveSpeed.
    """
    url = RESULT_URL_TEMPLATE.format(prediction_id=prediction_id)
    elapsed = 0.0

    while elapsed < POLL_TIMEOUT:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        body = resp.json()
        status = body.get("data", {}).get("status", "")
        logger.info("prediction_id=%s  status=%s  elapsed=%.0fs", prediction_id, status, elapsed)

        if status in ("completed", "failed", "error"):
            return body

    # Timed out
    return {"data": {"status": "timeout", "outputs": []}}


async def _generate_one(
    client: httpx.AsyncClient, prompt: str, seed: int, size: str
) -> ImageResult:
    """Submit + poll a single prompt and wrap in ImageResult."""
    try:
        prediction_id = await _submit_job(client, prompt, seed, size)
        result = await _poll_until_done(client, prediction_id)

        data = result.get("data", {})
        status = data.get("status", "unknown")

        if status == "completed":
            # outputs is typically a list of URLs
            urls = data.get("outputs", [])
            return ImageResult(prompt=prompt, status="completed", urls=urls)
        elif status == "timeout":
            return ImageResult(prompt=prompt, status="timeout", error="Polling timed out.")
        else:
            err = data.get("error") or result.get("message") or "Unknown error"
            return ImageResult(prompt=prompt, status="failed", error=str(err))

    except httpx.HTTPStatusError as exc:
        logger.error("HTTP error for prompt '%s': %s", prompt[:80], exc)
        return ImageResult(prompt=prompt, status="failed", error=str(exc))
    except Exception as exc:
        logger.error("Unexpected error for prompt '%s': %s", prompt[:80], exc)
        return ImageResult(prompt=prompt, status="failed", error=str(exc))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Cloud Run readiness / liveness probe."""
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    """
    Submit ALL prompts to WaveSpeed AI concurrently, poll EVERY job until it
    completes (or fails / times out), then return the full results as JSON.

    The response is only sent once every single job has finished.
    """
    async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 30) as client:
        # Fire all jobs concurrently and wait for ALL to finish
        tasks = [
            _generate_one(client, prompt, request.seed, request.size)
            for prompt in request.prompts
        ]
        results: list[ImageResult] = await asyncio.gather(*tasks)

    return GenerateResponse(results=results)
