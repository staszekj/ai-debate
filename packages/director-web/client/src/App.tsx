import { useEffect, useState } from "react";

import { api } from "./api";
import { DebateView } from "./DebateView";
import { ScriptEditor } from "./ScriptEditor";
import type { DebateScript } from "./types";

type View = { type: "editor" } | { type: "debate"; sessionId: string; script: DebateScript };

const SESSION_HASH = /^#\/sesja\/([\w-]+)$/;

export function App() {
  const [view, setView] = useState<View>({ type: "editor" });

  // #/sesja/<id> pozwala odświeżyć stronę albo otworzyć debatę w drugiej karcie
  useEffect(() => {
    const match = SESSION_HASH.exec(window.location.hash);
    if (match) {
      api
        .session(match[1])
        .then((s) => setView({ type: "debate", sessionId: s.session_id, script: s.script }))
        .catch(() => (window.location.hash = ""));
    }
  }, []);

  if (view.type === "debate") {
    return (
      <DebateView
        key={view.sessionId}
        sessionId={view.sessionId}
        script={view.script}
        onBack={() => {
          window.location.hash = "";
          setView({ type: "editor" });
        }}
      />
    );
  }
  return (
    <ScriptEditor
      onStarted={(s) => {
        window.location.hash = `#/sesja/${s.session_id}`;
        setView({ type: "debate", sessionId: s.session_id, script: s.script });
      }}
    />
  );
}
