import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
after(() => server.close());
const { reduceEvent } = await server.ssrLoadModule("/src/useDebate.ts");

const script = { blocks: [] };
const initial = () => ({
  items: [],
  status: "running",
  phase: "opening",
  blockIdx: null,
  questionNo: 0,
  speaking: null,
  connected: true,
  error: null,
  models: { host: null, dogs: null, cats: null },
});
const start = (id, model, step = "answer") => ({
  type: "model_start", id, model, step, messages: [{ type: "system", content: "pełny kontekst" }],
});

test("oddziela modele, zachowuje fragmenty i czyści zakończone wywołanie", () => {
  let state = reduceEvent(initial(), start("dogs-1", "dogs"), script);
  state = reduceEvent(state, start("cats-1", "cats"), script);
  state = reduceEvent(state, {
    type: "model_chunk", id: "dogs-1", model: "dogs", chunk: { content: "  odpowiedź\n" },
  }, script);
  state = reduceEvent(state, {
    type: "model_chunk", id: "wrong", model: "dogs", chunk: { content: "błędny fragment" },
  }, script);
  assert.deepEqual(state.models.dogs.chunks, [{ content: "  odpowiedź\n" }]);
  assert.equal(state.models.cats.id, "cats-1");
  state = reduceEvent(state, {
    type: "model_end", id: "dogs-1", model: "dogs", status: "done", retain: false,
  }, script);
  assert.equal(state.models.dogs, null);
  assert.equal(state.models.cats.id, "cats-1");
});

test("zachowuje sparsowaną decyzję do następnego wywołania prowadzącego", () => {
  let state = reduceEvent(initial(), start("host-1", "host", "decide"), script);
  state = reduceEvent(state, {
    type: "model_result", id: "host-1", model: "host", parsed: { block_exhausted: false, next_question: "?" },
  }, script);
  state = reduceEvent(state, {
    type: "model_end", id: "host-1", model: "host", status: "done", retain: true,
  }, script);
  assert.equal(state.models.host.finished, true);
  assert.deepEqual(state.models.host.parsed, { block_exhausted: false, next_question: "?" });
  state = reduceEvent(state, start("host-2", "host", "summary"), script);
  assert.equal(state.models.host.id, "host-2");
  assert.equal(state.models.host.parsed, undefined);
});
