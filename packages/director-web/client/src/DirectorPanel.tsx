import { useState } from "react";

import type { SessionStatus, Side } from "./types";
import type { useDebate } from "./useDebate";

type Director = ReturnType<typeof useDebate>["director"];

export function DirectorPanel({
  director,
  status,
  disabled,
}: {
  director: Director;
  status: SessionStatus;
  disabled: boolean;
}) {
  const [reason, setReason] = useState("");
  const [question, setQuestion] = useState("");
  const [target, setTarget] = useState<Side | "both">("both");
  const [note, setNote] = useState("");

  const reprimand = (side: Side) => {
    director.reprimand(side, reason.trim());
    setReason("");
  };

  return (
    <aside className="panel">
      <h2>Panel reżysera</h2>
      <p className="hint">Wszystkie interwencje realizuje prowadzący przed kolejną wypowiedzią.</p>

      <section className="card">
        <h3>Upomnienie</h3>
        <input placeholder="Powód, np. obrażanie przeciwnika" value={reason} onChange={(e) => setReason(e.target.value)} />
        <div className="row">
          <button type="button" disabled={disabled || !reason.trim()} onClick={() => reprimand("dogs")}>
            🐶 Upomnij psy
          </button>
          <button type="button" disabled={disabled || !reason.trim()} onClick={() => reprimand("cats")}>
            🐱 Upomnij koty
          </button>
        </div>
      </section>

      <section className="card">
        <h3>Dodatkowe pytanie</h3>
        <textarea
          rows={3}
          placeholder="Treść pytania (prowadzący je przeformułuje)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <div className="row">
          <select value={target} onChange={(e) => setTarget(e.target.value as Side | "both")}>
            <option value="both">do obu drużyn</option>
            <option value="dogs">do psów</option>
            <option value="cats">do kotów</option>
          </select>
          <button
            type="button"
            disabled={disabled || !question.trim()}
            onClick={() => {
              director.extraQuestion(question.trim(), target);
              setQuestion("");
            }}
          >
            Zadaj
          </button>
        </div>
      </section>

      <section className="card">
        <h3>Notatka dla prowadzącego</h3>
        <textarea
          rows={2}
          placeholder="np. dociśnij koty o alergie"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button
          type="button"
          disabled={disabled || !note.trim()}
          onClick={() => {
            director.note(note.trim());
            setNote("");
          }}
        >
          Wyślij notatkę
        </button>
      </section>

      <section className="card row controls">
        {status === "paused" ? (
          <button type="button" disabled={disabled} onClick={director.resume}>
            ▶ Wznów
          </button>
        ) : (
          <button type="button" disabled={disabled} onClick={director.pause}>
            ⏸ Pauza
          </button>
        )}
        <button type="button" className="danger" disabled={disabled} onClick={director.stop}>
          ⏹ Stop
        </button>
      </section>
    </aside>
  );
}
