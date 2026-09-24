# Piper TTS Server

A small, self-contained [Piper](https://github.com/OHF-Voice/piper1-gpl) text-to-speech
API built with FastAPI, tuned to run comfortably on Render's **free tier** (512MB RAM,
no GPU, no persistent disk).

- `GET /health` – liveness check
- `GET /voices` – list known voices and their download/load status
- `POST /tts` – synthesize text to a WAV file
- CORS enabled for all origins
- Default voice (`en_US-lessac-medium`) is downloaded automatically from
  Hugging Face on startup if it isn't already on disk

## Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/YOUR_USERNAME/YOUR_REPO)

1. Fork/push this repo to your own GitHub account.
2. Replace `YOUR_USERNAME/YOUR_REPO` in the button link above with your repo path.
3. Click the button (or use **New > Blueprint** in the Render dashboard and point it
   at your repo). Render will read `render.yaml` and provision the service on the
   free plan automatically.

First boot downloads the ~60MB voice model, so the very first request after a cold
start may take a few extra seconds — after that it's cached on disk for the life of
the instance.

> Render's free web services spin down after inactivity and have no persistent disk,
> so the voice model re-downloads on the next cold start. It's small enough that this
> stays fast; if you want to avoid re-downloads entirely, upgrade to a paid plan with
> a persistent disk and point `PIPER_MODEL_DIR` at it.

## Running locally

```bash
docker build -t piper-tts .
docker run -p 10000:10000 -e PORT=10000 piper-tts
```

Or without Docker (Linux, with `espeak-ng` installed system-wide):

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 10000
```

## API usage

### Health check

```bash
curl https://<your-app>.onrender.com/health
```

```json
{"status": "ok"}
```

### List voices

```bash
curl https://<your-app>.onrender.com/voices
```

```json
{
  "voices": [
    {"name": "en_US-lessac-medium", "downloaded": true, "loaded": true, "default": true},
    {"name": "en_US-amy-medium", "downloaded": false, "loaded": false, "default": false},
    {"name": "en_US-ryan-high", "downloaded": false, "loaded": false, "default": false},
    {"name": "en_GB-alan-medium", "downloaded": false, "loaded": false, "default": false}
  ]
}
```

### Synthesize speech

```bash
curl -X POST https://<your-app>.onrender.com/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from Piper running on Render.", "voice": "en_US-lessac-medium"}' \
  --output speech.wav
```

`voice` is optional and defaults to `en_US-lessac-medium`:

```bash
curl -X POST https://<your-app>.onrender.com/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "This uses the default voice."}' \
  --output speech.wav
```

Play it directly on macOS/Linux:

```bash
curl -X POST http://localhost:10000/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Testing one two three."}' \
  --output - | ffplay -autoexit -nodisp -
```

## Adding more voices

Edit the `VOICES` dict in `app.py` — add the voice's path from the
[piper-voices Hugging Face repo](https://huggingface.co/rhasspy/piper-voices/tree/main).
Only `PIPER_DEFAULT_VOICE` is downloaded at startup; any other registered voice is
downloaded automatically the first time it's requested via `/tts`.

## Configuration

| Env var                 | Default                | Description                                   |
|--------------------------|-------------------------|------------------------------------------------|
| `PORT`                   | `10000`                 | Port uvicorn binds to (set by Render)          |
| `PIPER_DEFAULT_VOICE`    | `en_US-lessac-medium`   | Voice pre-downloaded on startup                |
| `PIPER_MODEL_DIR`        | `/app/voices`           | Where `.onnx` / `.onnx.json` files are stored  |
| `PIPER_MAX_TEXT_LENGTH`  | `2000`                  | Max characters accepted per `/tts` request     |

## Notes on memory

- Only the voices you actually request get loaded into memory; each medium-quality
  voice model uses roughly 60–100MB resident once loaded.
- Loaded voices are cached for the process lifetime — repeat requests for the same
  voice don't re-read the model file.
- If you plan to serve several voices concurrently on the free tier, keep an eye on
  memory; loading 4–5 voices at once may approach the 512MB limit.
