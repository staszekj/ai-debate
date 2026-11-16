import { useCallback, useEffect, useReducer, useRef } from "react";

import { commandId, sessionSocketUrl } from "./api";
import type {
  AckStatus,
  ControlCommand,
  DebateEvent,
  DebateScript,
  DirectorCommand,
  Phase,
  SessionStatus,
  Speaker,
  TurnKind,
} from "./types";

export type ChatItem =
  | {
      key: string;
      type: "turn";
      speaker: Speaker;
      kind: TurnKind;
      text: string;
      streaming: boolean;
      passed: boolean;
    }
  | { key: string; type: "separator"; label: string }
  | { key: string; type: "director"; command: DirectorCommand; status: AckStatus };

export interface DebateState {
  items: ChatItem[];
  status: SessionStatus;
  phase: Phase;
  blockIdx: number | null;
  questionNo: number; // numer pytania w bieżącym bloku (z dodatkowymi)
  speaking: { speaker: Speaker; kind: TurnKind } | null;
  connected: boolean;
  error: string | null;
}

const initial: DebateState = {
  items: [],
  status: "running",
  phase: "opening",
  blockIdx: null,
  questionNo: 0,
  speaking: null,
  connected: false,
  error: null,
};

type Action = { type: "event"; event: DebateEvent } | { type: "reset" } | { type: "connected"; value: boolean };

export function reduceEvent(state: DebateState, event: DebateEvent, script: DebateScript): DebateState {
  const n = state.items.length;
  switch (event.type) {
    case "turn_start": {
      const items = [...state.items];
      let { blockIdx, questionNo } = state;
      if (event.kind === "block_intro" && event.block_idx !== null) {
        blockIdx = event.block_idx;
        questionNo = 0;
        const topic = script.blocks[event.block_idx]?.topic ?? "";
        items.push({ key: `sep-${n}`, type: "separator", label: `Blok ${event.block_idx + 1}: ${topic}` });
      }
      if (event.kind === "closing_statement" && !items.some((i) => i.type === "separator" && i.label === "Mowy końcowe")) {
        items.push({ key: `sep-${n}`, type: "separator", label: "Mowy końcowe" });
      }
      if (event.kind === "question") questionNo += 1;
      items.push({
        key: `turn-${n}`,
        type: "turn",
        speaker: event.speaker,
        kind: event.kind,
        text: "",
        streaming: true,
        passed: false,
      });
      return { ...state, items, blockIdx, questionNo, speaking: { speaker: event.speaker, kind: event.kind } };
    }
    case "token":
    case "turn_end": {
      const idx = state.items.findLastIndex((i) => i.type === "turn" && i.streaming);
      if (idx < 0) return state;
      const item = state.items[idx];
      if (item.type !== "turn") return state;
      const updated =
        event.type === "token"
          ? { ...item, text: item.text + event.text }
          : { ...item, text: event.text, passed: event.passed, streaming: false };
      const items = state.items.with(idx, updated);
      return { ...state, items, speaking: event.type === "token" ? state.speaking : null };
    }
    case "phase":
      return { ...state, phase: event.phase };
    case "status":
      return { ...state, status: event.status, error: event.status === "error" ? (event.message ?? "błąd") : state.error };
    case "director_ack": {
      const idx = state.items.findIndex((i) => i.type === "director" && i.command.id === event.id);
      if (idx >= 0) {
        const item = state.items[idx];
        if (item.type !== "director") return state;
        return { ...state, items: state.items.with(idx, { ...item, status: event.status }) };
      }
      if (!event.command) return state;
      return {
        ...state,
        items: [...state.items, { key: `dir-${event.id}`, type: "director", command: event.command, status: event.status }],
      };
    }
    case "error":
      return { ...state, error: event.message };
    default:
      return state;
  }
}

const FINISHED: SessionStatus[] = ["stopped", "done", "error"];

export function isFinished(status: SessionStatus): boolean {
  return FINISHED.includes(status);
}

/** Połączenie WebSocket z sesją: stan czatu z historii i bieżących zdarzeń, wysyłanie komend. */
export function useDebate(sessionId: string, script: DebateScript) {
  const [state, dispatch] = useReducer((s: DebateState, a: Action): DebateState => {
    if (a.type === "reset") return initial;
    if (a.type === "connected") return { ...s, connected: a.value };
    return reduceEvent(s, a.event, script);
  }, initial);
  const socket = useRef<WebSocket | null>(null);
  const finished = useRef(false);

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const ws = new WebSocket(sessionSocketUrl(sessionId));
      socket.current = ws;
      ws.onopen = () => {
        // serwer zaczyna od pełnej historii, więc budujemy stan od zera
        dispatch({ type: "reset" });
        dispatch({ type: "connected", value: true });
      };
      ws.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as DebateEvent;
        if (event.type === "status" && isFinished(event.status)) finished.current = true;
        dispatch({ type: "event", event });
      };
      ws.onclose = () => {
        dispatch({ type: "connected", value: false });
        if (!closed && !finished.current) retry = setTimeout(connect, 1000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, [sessionId]);

  const send = useCallback((cmd: DirectorCommand | ControlCommand) => {
    socket.current?.send(JSON.stringify(cmd));
  }, []);

  const director = {
    reprimand: (target: "dogs" | "cats", reason: string) => send({ type: "reprimand", id: commandId(), target, reason }),
    extraQuestion: (text: string, target: "dogs" | "cats" | "both") =>
      send({ type: "extra_question", id: commandId(), text, target }),
    note: (text: string) => send({ type: "note", id: commandId(), text }),
    pause: () => send({ type: "pause" }),
    resume: () => send({ type: "resume" }),
    stop: () => send({ type: "stop" }),
  };

  return { state, director };
}
