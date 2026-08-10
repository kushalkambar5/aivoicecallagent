# AI Voice Calling Agent

A fully **local** AI voice calling agent stack built on:

| Layer | Component | Port |
|---|---|---|
| **Orchestration** | [Dograh](https://github.com/dograh-hq/dograh) (Docker) | `3010` |
| **STT** | Qwen3-ASR-1.7B (local FastAPI) | `8001` |
| **LLM** | Groq – Llama 3.1 8B (cloud API) | — |
| **TTS** | Fun-CosyVoice3-0.5B-2512 (local FastAPI) | `8002` |
| **Telephony** | VoBiz (SIP trunk) | — |

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | `python --version` |
| Docker Desktop | Latest | Must be running |
| Git | Any | For cloning CosyVoice |
| Groq API key | — | Free at https://console.groq.com |
| VoBiz account | — | For real phone calls |

> **GPU (optional but recommended):** An NVIDIA GPU cuts STT+TTS latency from ~5s to <1s per turn. CUDA 12.x required.

---

## Project Structure

```
AIVoiceCallAgent/
├── models/
│   ├── Qwen3-ASR-1.7B/          ← STT model (already downloaded)
│   └── Fun-CosyVoice3-0.5B-2512/ ← TTS model (already downloaded)
├── services/
│   ├── stt_server/
│   │   ├── main.py              ← OpenAI-compatible STT FastAPI server
│   │   └── requirements.txt
│   └── tts_server/
│       ├── main.py              ← OpenAI-compatible TTS FastAPI server
│       ├── requirements.txt
│       └── CosyVoice/           ← Cloned by setup_cosyvoice.ps1
├── dograh/
│   └── docker-compose.yaml      ← Full Dograh stack
├── .env                         ← Your secrets (copy from .env.example)
├── .env.example                 ← Template
├── setup_cosyvoice.ps1          ← One-time dependency installer
└── start_services.ps1           ← Launch everything
```

---

## Step-by-Step Setup

### Step 1 — Configure credentials

```powershell
# Copy the template
Copy-Item .env.example .env

# Edit .env and fill in:
#   GROQ_API_KEY=gsk_...        (from console.groq.com)
#   VOBIZ_AUTH_ID=...
#   VOBIZ_AUTH_TOKEN=...
#   VOBIZ_FROM_NUMBER=+1...
notepad .env
```

### Step 2 — Install Python dependencies & CosyVoice

```powershell
# Run once — clones CosyVoice repo and installs all pip packages
.\setup_cosyvoice.ps1
```

> If you see errors about `pynini` or `WeTextProcessing` on Windows, install them from conda:
> ```powershell
> conda install -c conda-forge pynini
> pip install WeTextProcessing
> ```

### Step 3 — Start everything

```powershell
.\start_services.ps1
```

This opens 3 terminal windows:
- **STT server** (Qwen3-ASR) — loads model, then listens on `:8001`
- **TTS server** (CosyVoice3) — loads model, then listens on `:8002`
- **Dograh** (Docker) — starts all containers, UI on `:3010`

**Wait for model loading** (~1–2 min on first start). Check health:
```powershell
curl http://localhost:8001/health   # {"status":"ok","model_loaded":true}
curl http://localhost:8002/health   # {"status":"ok","model_loaded":true}
```

### Step 4 — Configure Dograh Dashboard

Open **http://localhost:3010** and complete these one-time steps:

#### 4a. Create your account
Register on first launch (stored locally in your PostgreSQL container).

#### 4b. Configure STT Provider
1. Go to **Settings → Providers → Speech to Text**
2. Select **Custom OpenAI-Compatible**
3. Set:
   - **Base URL:** `http://host.docker.internal:8001/v1`
   - **API Key:** `local`
   - **Model:** `Qwen/Qwen3-ASR-1.7B`

#### 4c. Configure LLM Provider
1. Go to **Settings → Providers → LLM**
2. Select **Groq**
3. Set:
   - **API Key:** your Groq key
   - **Model:** `llama-3.1-8b-instant`

#### 4d. Configure TTS Provider
1. Go to **Settings → Providers → Text to Speech**
2. Select **Custom OpenAI-Compatible**
3. Set:
   - **Base URL:** `http://host.docker.internal:8002/v1`
   - **API Key:** `local`
   - **Model:** `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`
   - **Voice:** `alloy` (maps to 中文女 / Chinese female by default)

#### Available TTS Voices

| Dograh Voice Name | CosyVoice3 Speaker |
|---|---|
| `alloy` | 中文女 (Chinese female) |
| `echo` | 中文男 (Chinese male) |
| `fable` | 英文女 (English female) |
| `onyx` | 英文男 (English male) |
| `nova` | 粤语女 (Cantonese female) |
| `shimmer` | 韩语女 (Korean female) |

#### 4e. Configure VoBiz Telephony
1. Go to **Settings → Telephony**
2. Click **Add Configuration → VoBiz**
3. Enter your VoBiz Auth ID and Auth Token
4. Add your DID number
5. Set the **Webhook URL** in your VoBiz console to: `http://YOUR_IP:8080/api/telephony/vobiz/webhook`
   - Use ngrok if your machine doesn't have a public IP: `ngrok http 8080`

### Step 5 — Create your first agent

1. Go to **Agents → New Agent**
2. Use the visual workflow builder to add:
   - **Greeting node:** "Hello! How can I help you today?"
   - **Listen node:** capture user speech
   - **LLM node:** process with Groq/Llama 3.1 8B
   - **Speak node:** TTS response via CosyVoice3
3. Use **Test Call** (browser microphone) to verify the full loop
4. Assign the agent to your VoBiz phone number

---

## Testing

### Test STT
```powershell
# Record a short audio clip first (or use a sample .wav)
curl -X POST http://localhost:8001/v1/audio/transcriptions `
  -F "file=@test.wav" `
  -F "model=Qwen/Qwen3-ASR-1.7B"
# Expected: {"text": "your transcribed text here"}
```

### Test TTS
```powershell
curl -X POST http://localhost:8002/v1/audio/speech `
  -H "Content-Type: application/json" `
  -d '{"input": "Hello, this is a test of CosyVoice 3.", "voice": "fable"}' `
  --output test_output.wav
# Open test_output.wav to hear the result
```

### Test LLM (Groq)
```powershell
curl -X POST https://api.groq.com/openai/v1/chat/completions `
  -H "Authorization: Bearer $env:GROQ_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"llama-3.1-8b-instant","messages":[{"role":"user","content":"Say hi"}]}'
```

---

## Troubleshooting

### STT server crashes on startup
- Check that `models/Qwen3-ASR-1.7B/` exists with `.safetensors` files
- Try: `pip install transformers --upgrade`

### TTS server says "CosyVoice library not found"
- Run `setup_cosyvoice.ps1` first
- Confirm `services/tts_server/CosyVoice/` directory exists

### Dograh can't reach STT/TTS servers
- Ensure Docker Desktop uses WSL2 backend (not Hyper-V) — `host.docker.internal` works on WSL2
- Alternatively, find your LAN IP (`ipconfig`) and replace `host.docker.internal` in `docker-compose.yaml` with your IP

### VoBiz webhooks not received
- Your Dograh instance must be reachable from the internet
- Use `ngrok http 8080` and update `PUBLIC_URL` in `.env` and the VoBiz console webhook

### High latency (>5 seconds per turn)
- CPU-only inference is slow — consider a GPU
- Use smaller text chunks in your agent prompts
- Switch Groq model to `llama-3.1-8b-instant` (already set)

---

## Architecture Diagram

```
Caller ──► VoBiz SIP Trunk ──► Dograh API (:8080)
                                    │
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
     STT :8001               Groq API (cloud)         TTS :8002
   Qwen3-ASR-1.7B           Llama 3.1 8B          CosyVoice3
  (local, your laptop)    (ultra-low latency)   (local, your laptop)
```

---

## License

This project wires together open-source components:
- **Dograh**: BSD 2-Clause
- **Qwen3-ASR**: Apache 2.0
- **CosyVoice3**: Apache 2.0
- **Groq**: Commercial API (free tier available)
- **VoBiz**: Commercial service
