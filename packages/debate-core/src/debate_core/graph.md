# Graf debaty

```mermaid
flowchart TD
    START --> human_control
    human_control -->|Stop| END
    human_control --> brain_control
    brain_control --> wikipedia
    brain_control --> dog_expert
    brain_control --> cat_expert
    brain_control -->|Podsumowanie lub stop| END
    wikipedia --> human_control
    dog_expert --> human_control
    cat_expert --> human_control
```

Kolejność ekspertów wybiera `brain_control`, biorąc pod uwagę niewiążącą sugestię przekazaną przez `human_control`. Kod ogranicza debatę do dwóch wypowiedzi każdego eksperta i najwyżej dwóch wyszukiwań między wypowiedziami. Po ostatniej wypowiedzi `brain_control` podsumowuje obie strony. Szczegóły opisuje [dokumentacja węzłów](expert_graph.md).