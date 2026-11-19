// Typy odwzorowane z debate-core (script.py, state.py) i zdarzeń grafu (graph.py).

export type Side = "dogs" | "cats";
export type Speaker = "host" | Side;
export type TurnKind =
  | "intro"
  | "block_intro"
  | "question"
  | "answer"
  | "reprimand"
  | "block_summary"
  | "closing_statement"
  | "summary";
export type Phase = "opening" | "block" | "closing_statements" | "closing" | "done" | "stopped";
export type SessionStatus = "running" | "paused" | "stopping" | "stopped" | "done" | "error";

export interface Block {
  topic: string;
  guidance: string | null;
  questions_target: number;
  questions_min: number;
  questions_max: number;
}

export interface DebateScript {
  title: string;
  blocks: Block[];
  closing_statement: { enabled: boolean; words: number };
  host_summary: boolean;
}

export interface PresetInfo {
  id: string;
  title: string;
}

export interface SessionInfo {
  session_id: string;
  status: SessionStatus;
  phase: Phase;
  script: DebateScript;
}

export type DirectorCommand =
  | { type: "reprimand"; id: string; target: Side; reason: string }
  | { type: "extra_question"; id: string; text: string; target: Side | "both" }
  | { type: "note"; id: string; text: string };

export type ControlCommand = { type: "pause" | "resume" | "stop" };

export type AckStatus = "queued" | "pending" | "done";

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type ModelMessage = { type: string; content: JsonValue; [key: string]: JsonValue };
export type ModelChunk = { content: JsonValue; additional_kwargs?: JsonValue; tool_call_chunks?: JsonValue };

export type ModelEvent =
  | { type: "model_start"; id: string; model: Speaker; step: string; messages: ModelMessage[]; response_schema?: JsonValue }
  | { type: "model_chunk"; id: string; model: Speaker; chunk: ModelChunk }
  | { type: "model_result"; id: string; model: Speaker; parsed: JsonValue }
  | { type: "model_end"; id: string; model: Speaker; status: "done" | "error" | "cancelled"; retain: boolean };

export type DebateEvent =
  | ModelEvent
  | { type: "turn_start"; speaker: Speaker; kind: TurnKind; block_idx: number | null }
  | { type: "token"; text: string }
  | { type: "turn_end"; speaker: Speaker; kind: TurnKind; text: string; block_idx: number | null }
  | { type: "phase"; phase: Phase }
  | { type: "decision"; block_exhausted: boolean; next_question?: string | null }
  | { type: "director_ack"; id: string; status: AckStatus; command?: DirectorCommand }
  | { type: "status"; status: SessionStatus; message?: string }
  | { type: "control_ack"; command: ControlCommand["type"] }
  | { type: "error"; message: string };
