# Psy kontra Koty

Debata po polsku: komercyjny LLM (`brain_control`) wybiera wyszukiwanie w Wikipedii lub eksperta MCP i na końcu podsumowuje debatę. Graf pilnuje dwóch wypowiedzi na eksperta, ale nie narzuca kolejności. Reżyser może zasugerować następnego mówcę w UI; decyzja nadal należy do koordynatora.

## Uruchomienie

Wymagania: `uv`, Node 26, `pnpm` 12 oraz serwery SLM z API zgodnym z OpenAI. Ustaw klucz dostawcy modelu komercyjnego i `HOST_MODEL` w `.env.local` według `.env.example`.

Dwie niezależne instancje ekspertów skonfigurujesz przez `DOGS_BASE_URL` i `DOGS_MODEL` oraz `CATS_BASE_URL` i `CATS_MODEL`. Adresy mogą prowadzić do różnych GPU lub maszyn. Do lokalnego demo na jednym GPU możesz pominąć te nadpisania: oba narzędzia użyją wtedy wspólnego `DEBATER_BASE_URL` i `DEBATER_MODEL`, z osobnymi promptami.

```bash
uv sync --all-packages
pnpm install --frozen-lockfile
```

Uruchom poniższe polecenia w osobnych terminalach:

```bash
./infra/vllm.sh                    # opcjonalny wspólny Bielik do lokalnego demo
uv run debate-mcp                 # narzędzia: 127.0.0.1:8002/mcp
uv run debate-api                 # REST i WebSocket: 127.0.0.1:8001
pnpm --filter director-web dev    # UI: localhost:5173
```

W devpodzie przekieruj port 5173 w VS Code. Na pokaz użyj np. pytania: „Co źródła mówią o tym, kiedy i gdzie udomowiono psa i kota, i jak wpłynęło to na ich relację z człowiekiem?”. Wyszukiwanie nie jest wymuszane; sprawdzaj trafność materiałów w linkach pokazanych przez UI.

CLI korzysta z tego samego grafu, ale nie wymaga uruchomienia API ani UI:

```bash
uv run debate 'Czym różniło się udomowienie psa i kota?'
```

`POST /api/sessions` przyjmuje `{ "question": "…" }` i zwraca identyfikator. `GET /api/sessions/{id}` zwraca stan sesji, a `/ws/sessions/{id}` dostarcza historię i bieżące zdarzenia. Pauza i stop działają na granicach kroków; stop nie publikuje wypowiedzi, jeśli jej generowanie już trwało. Historia jest przechowywana w pamięci procesu API.

## Weryfikacja

```bash
uv run --all-packages pytest -q
pnpm --filter director-web typecheck
pnpm --filter director-web build
```

Zobacz też [plan](PLAN.md) i [przebieg grafu](packages/debate-core/src/debate_core/graph.md).