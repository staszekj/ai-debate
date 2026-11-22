# Węzły grafu eksperckiego

Opis dotyczy węzłów zarejestrowanych w [`graph.py`](graph.py). Krawędzie pokazuje [diagram grafu](graph.md). `after_human_control` i `after_brain_control` to funkcje routingu, nie osobne węzły.

| Węzeł | Działanie |
|---|---|
| `human_control` | Po starcie i po każdym narzędziu sprawdza pauzę i stop oraz pobiera najnowszą sugestię eksperta. Gdy debata jest wstrzymana, czeka na wznowienie albo zatrzymanie. |
| `brain_control` | Komercyjny LLM dostaje pytanie, transkrypt, materiały, frazy, dozwolone akcje i ewentualną sugestię reżysera. Wybiera `wikipedia` z frazą albo jednego eksperta. Po dwóch wypowiedziach każdego eksperta podsumowuje debatę. |
| `wikipedia` | Wyszukuje przez MCP i zapisuje źródła lub notatkę o braku wyników albo awarii. Nie przypisuje wyszukiwania z góry do strony. Każda próba zużywa limit, także nieudana. |
| `dog_expert`, `cat_expert` | Wywołują osobne narzędzia MCP z pytaniem, publicznym transkryptem i bieżącymi materiałami. Każde narzędzie może wskazywać inną instancję SLM. Wypowiedź trafia w całości do transkryptu, a materiały wyszukiwania są czyszczone. Stop w trakcie generowania blokuje publikację wypowiedzi. |

Graf weryfikuje wybraną akcję, w tym limit dwóch wyszukiwań między wypowiedziami, brak powtórzeń frazy oraz limit dwóch wypowiedzi na eksperta. Przy niedozwolonej decyzji pyta model jeszcze raz; druga niedozwolona decyzja kończy sesję błędem. Podsumowanie nie jest wypowiedzią eksperta.

Model dostaje sugestię jako silną preferencję, o ile wskazany ekspert ma jeszcze wolną turę. Sugestia obowiązuje do następnej wypowiedzi, przechodzi przez wyszukiwania i może zostać zastąpiona nowszą. Nie przerywa już rozpoczętego kroku.