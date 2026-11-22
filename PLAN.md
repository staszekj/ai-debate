# Plan debaty eksperckiej

- [x] Jeden LangGraph: `human_control`, `brain_control`, `wikipedia`, `dog_expert`, `cat_expert`.
- [x] Komercyjny LLM wybiera narzędzie i kolejność ekspertów z uwzględnieniem niewiążących sugestii reżysera. Graf pilnuje maksymalnie dwóch wyszukiwań między wypowiedziami i dwóch wypowiedzi na eksperta. `brain_control` przygotowuje podsumowanie.
- [x] Narzędzia MCP: `search_wikipedia`, `dogs_reply`, `cats_reply`. Każdy ekspert ma niezależnie konfigurowalny serwer i model. Eksperci nie wywołują narzędzi.
- [x] REST i WebSocket: pytanie, postęp wyszukiwania, źródła i kompletne wypowiedzi. Pauza, wznowienie i stop pozostają dostępne.
- [x] Test nowego przebiegu na atrapach, w tym kolejności wybranej przez model i podsumowania.
- [ ] Pokaz nowego przebiegu z dwiema uruchomionymi instancjami SLM i prawdziwą Wikipedią przez MCP.
- [ ] Osobny fine-tuning ekspertów i dobór adaptera dla strony; bez zmiany wejścia i wyjścia narzędzi MCP.

Dokładny przepływ opisuje [graf debaty](packages/debate-core/src/debate_core/graph.md).