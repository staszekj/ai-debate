import { useEffect, useRef, useState, type FormEvent } from "react";

type Side = "dogs" | "cats";
type Status = "running" | "paused" | "stopping" | "stopped" | "done" | "error";
type Session = { session_id: string; question: string; status: Status };
type Source = { title: string; url: string; excerpt: string };
type DebateEvent =
  | { type: "status"; status: Status; message?: string }
  | { type: "error"; message: string }
  | { type: "expert_suggested"; side: Side }
  | { type: "turn_start"; speaker: Side }
  | { type: "turn_end"; speaker: Side; text: string }
  | { type: "research_start"; query: string }
  | { type: "research_end"; query: string; status: "found" | "empty" | "unavailable"; sources: Source[] }
  | { type: "summary"; text: string };

const names = { dogs: "Psy", cats: "Koty" };
const statuses = { running: "W toku", paused: "Wstrzymana", stopping: "Zatrzymywanie", stopped: "Zatrzymana", done: "Zakończona", error: "Błąd" };
const socketPath = (id: string) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/sessions/${id}`;

function LiveDebate({ session, onBack }: { session: Session; onBack: () => void }) {
  const [events, setEvents] = useState<DebateEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const socket = useRef<WebSocket>(null);

  useEffect(() => {
    const active = new WebSocket(socketPath(session.session_id));
    socket.current = active;
    let finished = false;
    active.onopen = () => setConnected(true);
    active.onmessage = (message) => {
      const event = JSON.parse(message.data) as DebateEvent;
      if (event.type === "status" && ["done", "stopped", "error"].includes(event.status)) finished = true;
      setEvents((past) => [...past, event]);
    };
    active.onclose = () => {
      setConnected(false);
      if (!finished) setConnectionError("Rozłączono. Odśwież stronę, aby wznowić podgląd.");
    };
    return () => {
      active.onopen = active.onclose = active.onmessage = null;
      active.close();
    };
  }, [session.session_id]);

  const status = events.findLast((event) => event.type === "status")?.status ?? session.status;
  const last = events.findLast((event) => event.type !== "status" && event.type !== "error" && event.type !== "expert_suggested");
  const send = (command: { type: "pause" | "resume" | "stop" } | { type: "suggest_expert"; side: Side }) =>
    socket.current?.send(JSON.stringify(command));
  const canControl = connected && (status === "running" || status === "paused");

  return (
    <main className="expert-shell">
      <header className="expert-top">
        <button onClick={onBack}>Nowa debata</button>
        <span aria-live="polite">{statuses[status]}</span>
        <div className="row">
          <button disabled={!canControl} onClick={() => send({ type: status === "paused" ? "resume" : "pause" })}>
            {status === "paused" ? "Wznów" : "Wstrzymaj"}
          </button>
          <button className="danger" disabled={!canControl} onClick={() => send({ type: "stop" })}>Zatrzymaj</button>
        </div>
      </header>
      <h1>{session.question}</h1>
      <div className="row" role="group" aria-label="Sugestia następnego eksperta">
        <button disabled={!canControl} onClick={() => send({ type: "suggest_expert", side: "dogs" })}>Zasugeruj Psy</button>
        <button disabled={!canControl} onClick={() => send({ type: "suggest_expert", side: "cats" })}>Zasugeruj Koty</button>
      </div>
      {connectionError && <p className="error" role="alert">{connectionError}</p>}
      <div className="expert-timeline" aria-live="polite">
        {events.map((event, index) => {
          if (event.type === "expert_suggested") return <p key={index}>Sugestia reżysera: {names[event.side]}</p>;
          if (event.type === "turn_end") return (
            <article key={index} className={`expert-turn expert-turn--${event.speaker}`}>
              <h2>{names[event.speaker]}</h2>
              <p>{event.text}</p>
            </article>
          );
          if (event.type === "summary") return (
            <article key={index} className="expert-turn">
              <h2>Podsumowanie debaty</h2>
              <p>{event.text}</p>
            </article>
          );
          if (event.type === "research_end") return (
            <section className="expert-research" key={index}>
              <h2>Wikipedia</h2>
              <p>{event.query}</p>
              {event.status === "unavailable" && <p>Wikipedia jest niedostępna.</p>}
              {event.status === "empty" && <p>Nie znaleziono materiałów.</p>}
              {event.sources.length > 0 && <ul>{event.sources.map((source) => (
                <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></li>
              ))}</ul>}
            </section>
          );
          if ((event.type === "error" || event.type === "status") && event.message) return <p className="error" key={index}>{event.message}</p>;
          return null;
        })}
        {status === "running" && last?.type === "research_start" && <p>Wikipedia: {last.query}…</p>}
        {status === "running" && last?.type === "turn_start" && <p>{names[last.speaker]} przygotowują wypowiedź…</p>}
      </div>
    </main>
  );
}

export function App() {
  const [session, setSession] = useState<Session>();
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const id = /^#\/sesja\/([\w-]+)$/.exec(location.hash)?.[1];
    if (!id) return;
    const controller = new AbortController();
    fetch(`/api/sessions/${id}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Nie znaleziono sesji.");
        return response.json();
      })
      .then(setSession)
      .catch(() => { if (!controller.signal.aborted) setError("Nie udało się otworzyć sesji."); });
    return () => controller.abort();
  }, []);

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const response = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
      });
      if (!response.ok) throw new Error("Nie udało się rozpocząć debaty.");
      const created = (await response.json()) as Session;
      location.hash = `/sesja/${created.session_id}`;
      setSession(created);
    } catch {
      setError("Nie udało się rozpocząć debaty.");
    } finally {
      setPending(false);
    }
  }

  if (session) return <LiveDebate key={session.session_id} session={session} onBack={() => {
    location.hash = "";
    setSession(undefined);
  }} />;

  return (
    <main className="expert-shell">
      <h1>Psy kontra Koty</h1>
      <form className="expert-form" onSubmit={start}>
        <label className="field">
          <span>Pytanie do debaty</span>
          <textarea rows={4} required maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={pending || !question.trim()}>Rozpocznij debatę</button>
      </form>
    </main>
  );
}
