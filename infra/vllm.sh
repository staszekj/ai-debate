#!/usr/bin/env bash
# Serwer debatantów: Bielik przez vLLM (API zgodne z OpenAI).
# Jedna instancja obsługuje obie strony (Psy i Koty różnią się tylko promptem).
#
#   infra/vllm.sh                 # uruchom z ustawieniami z .env.local
#   infra/vllm.sh --enforce-eager # dodatkowe flagi trafiają do `vllm serve`
#
# vLLM ma osobne środowisko (infra/vllm/), bo przypina własną wersję torch.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env.local" ]]; then
  set -a; source "$ROOT/.env.local"; set +a
fi

MODEL="${VLLM_MODEL:-speakleash/Bielik-11B-v3.1-Instruct-AWQ}"
SERVED_NAME="${DEBATER_MODEL:-bielik}"
PORT="${VLLM_PORT:-8000}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-16384}"
GPU_UTIL="${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"

# Quadro RTX 5000 = Turing (sm_75): bez BF16, więc wymuszamy FP16.
# max-num-seqs 4: debatanci mówią po kolei, duży batch tylko zjada VRAM.
exec uv run --project "$ROOT/infra/vllm" vllm serve "$MODEL" \
  --served-model-name "$SERVED_NAME" \
  --host 127.0.0.1 --port "$PORT" \
  --dtype half \
  --max-model-len "$MAX_LEN" \
  --max-num-seqs 4 \
  --gpu-memory-utilization "$GPU_UTIL" \
  --enable-prefix-caching \
  "$@"
