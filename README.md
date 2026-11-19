# ai-debate

Symulacja debaty „psy vs koty” po polsku. **Prowadzący** to komercyjny LLM (domyślnie Claude Haiku 5.5), a dwaj **debatanci**, Psy i Koty, to lokalny Bielik 11B serwowany przez vLLM. **Reżyser** (człowiek) ustala schemat debaty w aplikacji webowej i wpływa na nią wyłącznie przez prowadzącego. Szczegóły w [PLAN.md](PLAN.md).

```
przeglądarka ── director-web (Express :3000 / Vite :5173) ── debate-api (FastAPI :8001) ── LangGraph
                                                                                            ├─ prowadzący: API Anthropic
                                                                                            └─ debatanci: vLLM :8000 (Bielik)
```

## Wymagania

- Linux z GPU NVIDIA (testowane: Quadro RTX 5000, 16 GiB, sm_75) i sterownikiem obsługującym CUDA 13
- [uv](https://docs.astral.sh/uv/) i Python 3.12
- Node 26 (np. przez nvm) i pnpm 12
- klucz API Anthropic (platform.claude.com → API Keys) z doładowanym kontem

## Instalacja

```bash
uv sync --all-packages              # debate-core, debate-api
uv sync --project infra/vllm        # osobne środowisko vLLM (kilka GB)
pnpm install                        # director-web
cp .env.example .env.local          # uzupełnij ANTHROPIC_API_KEY
```

Model Bielika (`speakleash/Bielik-11B-v3.1-Instruct-AWQ`, ok. 6 GB) pobiera się przy pierwszym starcie vLLM.

## Uruchomienie

Każdy proces w osobnym terminalu, z katalogu głównego repo:

```bash
infra/vllm.sh                       # 1. Bielik (gotowy po ok. 1,5 min: "Application startup complete")
uv run debate check                 # 2. sprawdzenie: prowadzący i Bielik odpowiadają
uv run debate-api                   # 3. API na 127.0.0.1:8001
pnpm --filter director-web dev      # 4. aplikacja reżysera: http://localhost:5173
```

Wersja produkcyjna aplikacji reżysera (Express serwuje zbudowany frontend i proxuje API):

```bash
pnpm --filter director-web build
pnpm --filter director-web start    # http://127.0.0.1:3000
```

### Debata w terminalu (bez aplikacji webowej)

```bash
uv run debate run --preset psy-vs-koty --out runs/debata.md
```

W trakcie można wpisywać komendy reżysera: `/upomnij koty <powód>`, `/pytanie [psy|koty|obie] <treść>`, `/notatka <treść>`, `/pauza`, `/wznow`, `/stop`. Własny schemat podaje się przez `--script schemat.json` (format jak w `packages/debate-core/src/debate_core/presets/`).

Starsze schematy zawierające pole `ad_vocem` należy zaktualizować, usuwając to pole. Starsze checkpointy i klienci korzystający z poprzedniego formatu zdarzeń nie są obsługiwani.

## Konfiguracja (`.env.local`)

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `HOST_MODEL` | `anthropic:claude-haiku-5-5` | prowadzący, dowolny model `init_chat_model` (`dostawca:model`) |
| `HOST_EFFORT` | `low` | effort dla modeli Anthropic |
| `ANTHROPIC_API_KEY` | | klucz API |
| `DEBATER_BASE_URL` | `http://127.0.0.1:8000/v1` | serwer debatantów (API zgodne z OpenAI) |
| `DEBATER_MODEL` | `bielik` | nazwa modelu na serwerze (`--served-model-name`) |
| `DEBATER_TEMPERATURE` | `0.7` | temperatura debatantów |
| `DOGS_BASE_URL`, `CATS_BASE_URL` | | opcjonalnie osobne serwery dla stron |
| `VLLM_MODEL` | `speakleash/Bielik-11B-v3.1-Instruct-AWQ` | model serwowany przez `infra/vllm.sh` |
| `VLLM_MAX_MODEL_LEN` | `16384` | kontekst serwera |

Inny dostawca prowadzącego wymaga dodatku, np. `uv sync --all-packages --extra google` i `HOST_MODEL=google_genai:...`.

## Testy

```bash
uv run pytest                               # graf, router, interwencje, API (fake modele)
pnpm --filter director-web typecheck        # TypeScript: klient i serwer
pnpm --filter director-web build
```

## Struktura

- `packages/debate-core`: schemat debaty, prompty, graf LangGraph, kanał reżysera, CLI `debate`
- `packages/debate-api`: FastAPI (REST + WebSocket) nad grafem
- `packages/director-web`: aplikacja reżysera (Express + React + Vite + chatscope)
- `infra/`: uruchomienie Bielika przez vLLM
