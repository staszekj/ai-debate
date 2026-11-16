import { useEffect, useState } from "react";

import { api } from "./api";
import type { Block, DebateScript, PresetInfo, SessionInfo } from "./types";

const emptyBlock = (): Block => ({
  topic: "",
  guidance: null,
  questions_target: 5,
  questions_min: 4,
  questions_max: 6,
});

function blockError(b: Block): string | null {
  if (!b.topic.trim()) return "podaj temat";
  if (!(b.questions_min <= b.questions_target && b.questions_target <= b.questions_max))
    return "wymagane: min ≤ docelowo ≤ max";
  if (b.questions_min < 1) return "min. 1 pytanie";
  return null;
}

function NumberField(props: { label: string; value: number; min?: number; onChange: (v: number) => void }) {
  return (
    <label className="field field--number">
      <span>{props.label}</span>
      <input
        type="number"
        min={props.min ?? 1}
        value={props.value}
        onChange={(e) => props.onChange(Number(e.target.value))}
      />
    </label>
  );
}

export function ScriptEditor({ onStarted }: { onStarted: (session: SessionInfo) => void }) {
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [presetId, setPresetId] = useState("");
  const [script, setScript] = useState<DebateScript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api
      .presets()
      .then((list) => {
        setPresets(list);
        if (list.length) setPresetId(list[0].id);
      })
      .catch((e: Error) => setError(`Nie udało się pobrać presetów: ${e.message}`));
  }, []);

  useEffect(() => {
    if (!presetId) return;
    api
      .preset(presetId)
      .then(setScript)
      .catch((e: Error) => setError(e.message));
  }, [presetId]);

  if (!script) return <div className="editor">{error ?? "Ładowanie…"}</div>;

  const update = (patch: Partial<DebateScript>) => setScript({ ...script, ...patch });
  const updateBlock = (i: number, patch: Partial<Block>) =>
    update({ blocks: script.blocks.map((b, j) => (j === i ? { ...b, ...patch } : b)) });
  const moveBlock = (i: number, delta: -1 | 1) => {
    const blocks = [...script.blocks];
    [blocks[i], blocks[i + delta]] = [blocks[i + delta], blocks[i]];
    update({ blocks });
  };
  const errors = script.blocks.map(blockError);
  const invalid = !script.title.trim() || script.blocks.length === 0 || errors.some(Boolean);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      onStarted(await api.createSession(script));
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  };

  return (
    <div className="editor">
      <h1>Schemat debaty</h1>

      <section className="card">
        <label className="field">
          <span>Preset</span>
          <select value={presetId} onChange={(e) => setPresetId(e.target.value)}>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Tytuł</span>
          <input value={script.title} onChange={(e) => update({ title: e.target.value })} />
        </label>
      </section>

      <h2>Bloki tematyczne</h2>
      {script.blocks.map((block, i) => (
        <section className="card block" key={i}>
          <div className="block__head">
            <strong>Blok {i + 1}</strong>
            <div className="block__actions">
              <button type="button" disabled={i === 0} onClick={() => moveBlock(i, -1)} title="W górę">
                ↑
              </button>
              <button
                type="button"
                disabled={i === script.blocks.length - 1}
                onClick={() => moveBlock(i, 1)}
                title="W dół"
              >
                ↓
              </button>
              <button
                type="button"
                className="danger"
                disabled={script.blocks.length === 1}
                onClick={() => update({ blocks: script.blocks.filter((_, j) => j !== i) })}
              >
                Usuń
              </button>
            </div>
          </div>
          <label className="field">
            <span>Temat</span>
            <input value={block.topic} onChange={(e) => updateBlock(i, { topic: e.target.value })} />
          </label>
          <label className="field">
            <span>Wskazówki dla prowadzącego</span>
            <textarea
              rows={2}
              value={block.guidance ?? ""}
              onChange={(e) => updateBlock(i, { guidance: e.target.value || null })}
            />
          </label>
          <div className="row">
            <NumberField label="Pytań min" value={block.questions_min} onChange={(v) => updateBlock(i, { questions_min: v })} />
            <NumberField
              label="Docelowo"
              value={block.questions_target}
              onChange={(v) => updateBlock(i, { questions_target: v })}
            />
            <NumberField label="Max" value={block.questions_max} onChange={(v) => updateBlock(i, { questions_max: v })} />
          </div>
          {errors[i] && <p className="error">{errors[i]}</p>}
        </section>
      ))}
      <button type="button" onClick={() => update({ blocks: [...script.blocks, emptyBlock()] })}>
        + Dodaj blok
      </button>

      <h2>Ustawienia</h2>
      <section className="card">
        <div className="row">
          <label className="field field--check">
            <input
              type="checkbox"
              checked={script.ad_vocem.enabled}
              onChange={(e) => update({ ad_vocem: { ...script.ad_vocem, enabled: e.target.checked } })}
            />
            <span>Ad vocem</span>
          </label>
          <NumberField
            label="maks. zdań"
            value={script.ad_vocem.max_sentences}
            onChange={(v) => update({ ad_vocem: { ...script.ad_vocem, max_sentences: v } })}
          />
        </div>
        <div className="row">
          <label className="field field--check">
            <input
              type="checkbox"
              checked={script.closing_statement.enabled}
              onChange={(e) =>
                update({ closing_statement: { ...script.closing_statement, enabled: e.target.checked } })
              }
            />
            <span>Mowy końcowe</span>
          </label>
          <NumberField
            label="około słów"
            min={20}
            value={script.closing_statement.words}
            onChange={(v) => update({ closing_statement: { ...script.closing_statement, words: v } })}
          />
        </div>
        <label className="field field--check">
          <input
            type="checkbox"
            checked={script.host_summary}
            onChange={(e) => update({ host_summary: e.target.checked })}
          />
          <span>Podsumowanie prowadzącego na koniec</span>
        </label>
      </section>

      {error && <p className="error">{error}</p>}
      <button type="button" className="primary start" disabled={invalid || starting} onClick={start}>
        {starting ? "Startuje…" : "Start"}
      </button>
    </div>
  );
}
