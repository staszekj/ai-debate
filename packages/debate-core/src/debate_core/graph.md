# Graf debaty

```mermaid
flowchart TD
    Start --> Gate[Sprawdź sterowanie i wybierz stronę]
    Gate -->|Cztery wypowiedzi lub stop| End[Koniec]
    Gate -->|Limit wyszukiwań| Expert[Ekspert Psy lub Koty przez MCP]
    Gate --> Coordinate[LLM koordynuje zebranie materiałów]
    Coordinate -->|Nowa fraza| Search[Wikipedia przez MCP]
    Coordinate -->|Gotowe lub powtórzona fraza| Expert
    Search --> Gate
    Expert --> Publish[Zapisz wypowiedź i wyczyść materiały tury]
    Publish --> Gate
```

Kolejność i limit wyszukiwań wyznacza kod. Koordynator zwraca frazę lub `null`. Wikipedia zwraca fragmenty artykułów i adresy; brak wyników i błędy trafiają do kontekstu aktualnego eksperta jako notatka. Ekspert otrzymuje również pytanie i dotychczasowe publiczne wypowiedzi. Materiały badawcze nie przechodzą automatycznie na drugą stronę, ale źródła są widoczne w UI. Wypowiedź jest publikowana w całości.