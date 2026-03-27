# WaveSpeed AI Image Generator – Cloud Run (FastAPI)

A FastAPI microservice that accepts one or more text prompts, concurrently submits image jobs to the WaveSpeed AI API, polls **every** job until done, and only returns the JSON response once **all** images are complete.

---

## Endpoint

### `POST /generate`

**Request body**
```json
{
  "prompts": ["a golden retriever on the moon", "a futuristic Tokyo skyline"],
  "seed": -1,
  "size": "1024*1024"
}
```

**Response** (returned only after every image is finished)
```json
{
  "results": [
    {
      "prompt": "a golden retriever on the moon",
      "status": "completed",
      "urls": ["https://cdn.wavespeed.ai/..."]
    },
    {
      "prompt": "a futuristic Tokyo skyline",
      "status": "completed",
      "urls": ["https://cdn.wavespeed.ai/..."]
    }
  ]
}
```

### `GET /health`
Returns `{"status": "ok"}` — used by Cloud Run as a readiness probe.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `WAVESPEED_API_KEY` | *(required)* | WaveSpeed API Bearer token |
| `POLL_INTERVAL_SECONDS` | `2` | How often to poll each job |
| `POLL_TIMEOUT_SECONDS` | `300` | Max wait per job before timeout |

Copy `.env.example` → `.env` and fill in your key for local dev.

---

## Local Development

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your API key (or create a .env and load it)
$env:WAVESPEED_API_KEY = "YOUR_KEY_HERE"

# 3. Start the dev server
uvicorn main:app --reload --port 8000

# 4. Test it
Invoke-RestMethod -Method POST -Uri http://localhost:8000/generate `
  -ContentType "application/json" `
  -Body '{"prompts": ["a sunset over mountains"]}'
```

Visit `http://localhost:8000/docs` for the interactive Swagger UI.

---

## Docker

```powershell
# Build
docker build -t wavespeed-ai .

# Run
docker run -p 8080:8080 -e WAVESPEED_API_KEY=YOUR_KEY -e PORT=8080 wavespeed-ai
```

---

## Deploy to Google Cloud Run

### Option A — Direct source deploy (simplest)
```bash
gcloud run deploy wavespeed-ai \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars WAVESPEED_API_KEY=YOUR_KEY \
  --timeout 600
```

> **Note:** Set `--timeout 600` (10 min) so Cloud Run doesn't kill long polling sessions.

### Option B — Build via Artifact Registry first
```bash
# 1. Build & push
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/wavespeed-ai

# 2. Deploy
gcloud run deploy wavespeed-ai \
  --image gcr.io/YOUR_PROJECT_ID/wavespeed-ai \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars WAVESPEED_API_KEY=YOUR_KEY \
  --timeout 600
```

### Using a Secret instead of plain env var (recommended)
```bash
# Store the key as a secret
echo -n "YOUR_KEY" | gcloud secrets create wavespeed-api-key --data-file=-

# Reference it in the deploy command
gcloud run deploy wavespeed-ai \
  --source . \
  --region us-central1 \
  --set-secrets WAVESPEED_API_KEY=wavespeed-api-key:latest \
  --timeout 600
```

---

## Calling from n8n

Replace your two existing HTTP Request nodes with a single **HTTP Request** node:

- **Method:** POST  
- **URL:** `https://<your-cloud-run-url>/generate`  
- **Body (JSON):**
```json
{
  "prompts": ["={{ $json.output }}"]
}
```
- The response will already contain all completed image URLs — no need for a separate polling step.
