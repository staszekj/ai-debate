import {
  Avatar,
  ChatContainer,
  ConversationHeader,
  MainContainer,
  Message,
  MessageList,
  MessageSeparator,
  TypingIndicator,
} from "@chatscope/chat-ui-kit-react";

import { DirectorPanel } from "./DirectorPanel";
import type { DebateScript, DirectorCommand, Speaker, TurnKind } from "./types";
import { type ChatItem, isFinished, useDebate } from "./useDebate";

const SPEAKER: Record<Speaker, { name: string; emoji: string }> = {
  host: { name: "Prowadzący", emoji: "🎙️" },
  dogs: { name: "Psy", emoji: "🐶" },
  cats: { name: "Koty", emoji: "🐱" },
};
const KIND_LABEL: Partial<Record<TurnKind, string>> = {
  closing_statement: "mowa końcowa",
  reprimand: "upomnienie",
  question: "pytanie",
};
const PHASE_LABEL = {
  opening: "Otwarcie",
  block: "Bloki tematyczne",
  closing_statements: "Mowy końcowe",
  closing: "Zamknięcie",
  done: "Zakończona",
  stopped: "Przerwana",
};
const STATUS_LABEL = {
  running: "trwa",
  paused: "pauza",
  stopping: "zatrzymywanie",
  stopped: "przerwana przez reżysera",
  done: "zakończona",
  error: "błąd",
};
const SIDE_NAME = { dogs: "Psy", cats: "Koty", both: "obie drużyny" };

function avatarSrc(emoji: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="32" fill="#eef1f6"/><text x="32" y="44" font-size="34" text-anchor="middle">${emoji}</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function describeCommand(cmd: DirectorCommand): string {
  switch (cmd.type) {
    case "reprimand":
      return `Upomnij drużynę ${SIDE_NAME[cmd.target]}: ${cmd.reason}`;
    case "extra_question":
      return `Dodatkowe pytanie (${SIDE_NAME[cmd.target]}): ${cmd.text}`;
    case "note":
      return `Notatka: ${cmd.text}`;
  }
}

function renderItem(item: ChatItem) {
  if (item.type === "separator") return <MessageSeparator key={item.key} content={item.label} />;
  if (item.type === "director") {
    const status = item.status === "done" ? "zrealizowano" : "oczekuje";
    return (
      <MessageSeparator key={item.key} className={`director director--${item.status}`}>
        🎬 Reżyser → Prowadzący: {describeCommand(item.command)} · <em>{status}</em>
      </MessageSeparator>
    );
  }
  if (item.streaming && !item.text) return null;
  const who = SPEAKER[item.speaker];
  const label = KIND_LABEL[item.kind];
  return (
    <Message
      key={item.key}
      className={`turn turn--${item.speaker} turn--${item.kind}`}
      model={{ direction: item.speaker === "cats" ? "outgoing" : "incoming", position: "single", type: "custom" }}
      avatarPosition={item.speaker === "cats" ? "tr" : "tl"}
    >
      <Avatar src={avatarSrc(who.emoji)} name={who.name} />
      <Message.Header sender={label ? `${who.name} · ${label}` : who.name} />
      <Message.CustomContent>{item.text}</Message.CustomContent>
    </Message>
  );
}

export function DebateView({ sessionId, script, onBack }: { sessionId: string; script: DebateScript; onBack: () => void }) {
  const { state, director } = useDebate(sessionId, script);
  const finished = isFinished(state.status);
  const block = state.blockIdx !== null ? script.blocks[state.blockIdx] : null;
  const progress =
    state.phase === "done"
      ? 1
      : state.blockIdx === null
        ? state.phase === "opening"
          ? 0
          : 1
        : (state.blockIdx + Math.min(state.questionNo / (block?.questions_target ?? 1), 1)) / script.blocks.length;
  const typing = state.speaking ? SPEAKER[state.speaking.speaker].name : null;

  return (
    <div className="debate">
      <div className="debate__chat">
        <div className="progress">
          <div className="progress__text">
            <strong>{PHASE_LABEL[state.phase]}</strong>
            {state.phase === "block" && block && (
              <span>
                {" "}
                · blok {state.blockIdx! + 1}/{script.blocks.length} · pytanie {state.questionNo}
              </span>
            )}
            <span className={`status status--${state.status}`}>{STATUS_LABEL[state.status]}</span>
            {!state.connected && !finished && <span className="status status--offline">łączenie…</span>}
          </div>
          <div className="progress__bar">
            <div style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
        </div>
        <MainContainer>
          <ChatContainer>
            <ConversationHeader>
              <ConversationHeader.Back onClick={onBack} />
              <ConversationHeader.Content userName={script.title} info={`sesja ${sessionId}`} />
            </ConversationHeader>
            <MessageList typingIndicator={typing ? <TypingIndicator content={`${typing} mówi…`} /> : undefined}>
              {state.items.map(renderItem)}
            </MessageList>
          </ChatContainer>
        </MainContainer>
        {state.error && <p className="error">{state.error}</p>}
      </div>
      <DirectorPanel director={director} status={state.status} disabled={finished || !state.connected} />
    </div>
  );
}
