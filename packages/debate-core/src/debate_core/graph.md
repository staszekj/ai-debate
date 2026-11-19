# Graf debaty

Diagram stanów UML przedstawia rzeczywiste węzły i krawędzie grafu LangGraph
z [`graph.py`](./graph.py). Po wykonaniu
każdego węzła graf wraca do `director_gate`; kolejny węzeł wybiera router na
podstawie stanu i oczekujących interwencji.

```mermaid
stateDiagram-v2
    [*] --> director_gate

    director_gate --> [*]: step = done
    director_gate --> host_reprimand: oczekuje upomnienie
    director_gate --> host_extra_question: oczekuje dodatkowe pytanie i jest punkt pytania
    director_gate --> host_opening: step = opening
    director_gate --> host_block_intro: step = block_intro
    director_gate --> host_question: step = question
    director_gate --> debater_answer: step = debater
    director_gate --> host_decide: step = decide
    director_gate --> host_block_summary: step = block_summary
    director_gate --> debater_closing: step = closing_statement
    director_gate --> host_closing: step = closing

    host_opening --> director_gate
    host_block_intro --> director_gate
    host_question --> director_gate
    debater_answer --> director_gate
    host_decide --> director_gate
    host_block_summary --> director_gate
    debater_closing --> director_gate
    host_closing --> director_gate
    host_reprimand --> director_gate
    host_extra_question --> director_gate
```

## Wybór kolejnego kroku

- `director_gate` obsługuje pauzę, zatrzymanie i komendy reżysera. Zatrzymanie
  ustawia fazę `stopped` i krok `done`. Notatki są zapisywane w stanie.
- Router najpierw kończy graf dla `done`, następnie obsługuje oczekujące
  upomnienia, a potem dodatkowe pytania. Dodatkowe pytanie może wejść przed
  zwykłym pytaniem, podsumowaniem bloku lub pierwszą mową końcową; nie przerywa
  wymiany odpowiedzi.
- `host_opening` przechodzi do `block_intro`, a `host_block_intro` do `question`.
  `host_question` rozpoczyna odpowiedzi debatantów (`debater`).
- `debater_answer` przechodzi do kolejnego
  debatanta albo do `decide`. Po dodatkowym pytaniu wraca do zapisanego kroku,
  bez zwiększania licznika zwykłych pytań w bloku.
- `host_decide` wybiera kolejne pytanie albo podsumowanie bloku. Przed osiągnięciem
  `questions_min` kontynuacja jest obowiązkowa; przy `questions_max` blok
  kończy się bez wywołania modelu decyzyjnego.
- `host_block_summary` przechodzi do następnego bloku albo, po ostatnim bloku,
  do włączonych mów końcowych, podsumowania prowadzącego lub końca. Po mowach
  końcowych następuje opcjonalne `host_closing`, a następnie koniec.
