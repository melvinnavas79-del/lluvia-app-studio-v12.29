import { useState } from "react";

/**
 * FileTree — arbol recursivo de archivos del workspace.
 * Props: tree (objeto del backend), onSelectFile(path).
 */
function TreeNode({ node, onSelectFile, selected, depth = 0 }) {
  const [open, setOpen] = useState(depth < 2);
  const isDir = node.type === "dir";
  const isSelected = !isDir && node.path === selected;

  const iconForExt = (ext) => {
    const m = {
      ".py": "🐍", ".js": "📜", ".jsx": "⚛", ".ts": "📜", ".tsx": "⚛",
      ".css": "🎨", ".html": "🌐", ".md": "📝", ".json": "📦",
      ".yml": "⚙", ".yaml": "⚙", ".toml": "⚙", ".sh": "🖥",
      ".env": "🔐", ".gitignore": "🚫",
    };
    return m[ext] || "📄";
  };

  if (isDir) {
    return (
      <div>
        <div
          onClick={() => setOpen(!open)}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "3px 6px", paddingLeft: `${depth * 14 + 6}px`,
            cursor: "pointer", fontSize: "0.85rem", borderRadius: 4,
            color: "var(--text-primary, #111)",
            userSelect: "none",
          }}
          onMouseEnter={(e) => e.currentTarget.style.background = "rgba(91,141,239,0.08)"}
          onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
        >
          <span style={{ width: 12, display: "inline-block", color: "var(--text-muted)" }}>
            {open ? "▼" : "▶"}
          </span>
          <span>📁</span>
          <span style={{ fontWeight: 600 }}>{node.name || "/"}</span>
          <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginLeft: "auto" }}>
            {node.children?.length || 0}
          </span>
        </div>
        {open && (node.children || []).map((c, i) => (
          <TreeNode key={i} node={c} onSelectFile={onSelectFile}
                    selected={selected} depth={depth + 1} />
        ))}
      </div>
    );
  }

  return (
    <div
      onClick={() => onSelectFile(node.path)}
      data-testid={`file-tree-item-${node.path}`}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "3px 6px", paddingLeft: `${depth * 14 + 20}px`,
        cursor: "pointer", fontSize: "0.85rem", borderRadius: 4,
        background: isSelected ? "rgba(91,141,239,0.15)" : "transparent",
        color: isSelected ? "#5B8DEF" : "var(--text-primary, #111)",
        fontWeight: isSelected ? 600 : 400,
      }}
      onMouseEnter={(e) => !isSelected && (e.currentTarget.style.background = "rgba(91,141,239,0.06)")}
      onMouseLeave={(e) => !isSelected && (e.currentTarget.style.background = "transparent")}
    >
      <span>{iconForExt(node.ext)}</span>
      <span>{node.name}</span>
      <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginLeft: "auto" }}>
        {node.size > 1024 ? `${(node.size / 1024).toFixed(1)}K` : `${node.size}B`}
      </span>
    </div>
  );
}

export default function FileTree({ tree, onSelectFile, selectedPath }) {
  if (!tree) return <div style={{ padding: "1rem", color: "var(--text-muted)" }}>Sin archivos</div>;
  return (
    <div style={{ padding: "0.5rem 0", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}
         data-testid="file-tree">
      <TreeNode node={tree} onSelectFile={onSelectFile} selected={selectedPath} />
    </div>
  );
}
