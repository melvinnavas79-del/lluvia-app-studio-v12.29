import { useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import { api, formatError } from "../api";

const EXT_TO_LANG = {
  ".py": "python", ".js": "javascript", ".jsx": "javascript",
  ".ts": "typescript", ".tsx": "typescript", ".css": "css",
  ".html": "html", ".md": "markdown", ".json": "json",
  ".yml": "yaml", ".yaml": "yaml", ".toml": "ini",
  ".sh": "shell", ".env": "ini", ".gitignore": "ini",
};

/**
 * CodeEditor — Monaco wrapper con auto-save y resaltado de lenguaje.
 * Props: appSlug, path, onEditCreated.
 */
export default function CodeEditor({ appSlug, path, onEditCreated }) {
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [isBinary, setIsBinary] = useState(false);
  const saveTimer = useRef(null);

  useEffect(() => {
    if (!appSlug || !path) return;
    setLoading(true);
    setError("");
    api.get(`/me/apps/${appSlug}/file`, { params: { path } })
      .then(({ data }) => {
        setIsBinary(!!data.is_binary);
        setContent(data.content || "");
        setOriginalContent(data.content || "");
      })
      .catch(e => setError(formatError(e)))
      .finally(() => setLoading(false));
    return () => clearTimeout(saveTimer.current);
  }, [appSlug, path]);

  const ext = path ? "." + path.split(".").pop().toLowerCase() : "";
  const language = EXT_TO_LANG[ext] || "plaintext";
  const isDirty = content !== originalContent;

  const handleChange = (value) => {
    setContent(value || "");
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => doSave(value || ""), 1200);
  };

  const doSave = async (newValue) => {
    if (!appSlug || !path || isBinary) return;
    setSaving(true);
    try {
      const { data } = await api.put(`/me/apps/${appSlug}/file`, { path, content: newValue });
      setOriginalContent(newValue);
      onEditCreated && onEditCreated(data);
    } catch (e) {
      setError(formatError(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div style={{ padding: "2rem", color: "var(--text-muted)" }}>Cargando…</div>;
  }
  if (error) {
    return <div style={{ padding: "2rem", color: "#DC2626" }}>{error}</div>;
  }
  if (isBinary) {
    return <div style={{ padding: "2rem", color: "var(--text-muted)" }}>
      Archivo binario — no se puede mostrar en el editor.
    </div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }} data-testid="code-editor">
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "0.5rem 0.75rem", background: "#1E1E1E", color: "#fff",
        fontSize: "0.78rem", fontFamily: "monospace",
        borderBottom: "1px solid rgba(255,255,255,0.1)",
      }}>
        <span>{path}</span>
        <span style={{ color: saving ? "#FBBF24" : isDirty ? "#EF4444" : "#10B981" }}>
          {saving ? "● Guardando…" : isDirty ? "● Sin guardar" : "● Guardado"}
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <Editor
          height="100%"
          language={language}
          value={content}
          theme="vs-dark"
          onChange={handleChange}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            tabSize: 2,
            wordWrap: "on",
            scrollBeyondLastLine: false,
            automaticLayout: true,
          }}
        />
      </div>
    </div>
  );
}
