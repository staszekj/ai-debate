# Plan debaty eksperckiej

- [x] Jeden LangGraph: jedno pytanie, cztery tury (Psy, Koty, Psy, Koty), bez hosta na scenie.
- [x] Komercyjny LLM jako koordynator: wyszukanie albo gotowość do wypowiedzi. Graf wymusza najwyżej dwa wyszukania na turę.
- [x] Narzędzia MCP: `search_wikipedia`, `dogs_reply`, `cats_reply`. Obaj eksperci korzystają z jednej instancji Bielika w vLLM. Eksperci nie wywołują narzędzi.
- [x] REST i WebSocket: pytanie, postęp wyszukiwania, źródła i kompletne wypowiedzi. Pauza, wznowienie i stop pozostają dostępne.
- [x] Test przebiegu na atrapach i pokaz z prawdziwą Wikipedią przez MCP.
- [ ] Osobny fine-tuning ekspertów i dobór adaptera dla strony; bez zmiany wejścia i wyjścia narzędzi MCP.

Dokładny przepływ opisuje [graf debaty](packages/debate-core/src/debate_core/graph.md).