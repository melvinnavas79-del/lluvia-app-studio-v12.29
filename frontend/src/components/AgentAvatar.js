/* AgentAvatar - Avatares corporativos de bots via DiceBear (bottts-neutral)
   Reemplaza los antiguos emoji-en-cuadrado por caras de bot estilizadas
   modernas que generan confianza enterprise. */
import { useMemo } from "react";

const PASTEL_BG = [
  "e0f2fe", // celeste
  "fef9c3", // amarillo claro
  "fce7f3", // rosa
  "dcfce7", // verde
  "ede9fe", // lila
  "fee2e2", // coral
  "ffedd5", // peach
  "e0e7ff", // indigo
];

function pickBg(seed) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return PASTEL_BG[h % PASTEL_BG.length];
}

export default function AgentAvatar({
  agent,
  size = 40,
  rounded = "circle", // "circle" | "rounded"
  className = "",
  style = {},
}) {
  const seed = (agent?.name || agent?.id || "Agent").trim();
  const bg = useMemo(() => pickBg(seed), [seed]);
  const url = `https://api.dicebear.com/8.x/bottts-neutral/svg?seed=${encodeURIComponent(seed)}&backgroundColor=${bg}&radius=${rounded === "circle" ? 50 : 18}&size=${size * 2}`;
  const radius = rounded === "circle" ? "50%" : "14px";
  return (
    <img
      src={url}
      alt={agent?.name || "Agent"}
      width={size}
      height={size}
      className={`agent-avatar ${className}`}
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: `#${bg}`,
        objectFit: "cover",
        display: "block",
        flexShrink: 0,
        ...style,
      }}
      data-testid={`agent-avatar-${agent?.id || seed}`}
    />
  );
}

export function UserAvatar({ name, size = 36, accent = "#0F172A" }) {
  const initial = (name || "U").trim().charAt(0).toUpperCase();
  return (
    <div
      className="user-avatar"
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: accent,
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 600,
        fontSize: size * 0.42,
        flexShrink: 0,
        letterSpacing: "-0.02em",
        boxShadow: "0 1px 2px rgba(0,0,0,0.08)",
      }}
      data-testid="user-avatar"
    >
      {initial}
    </div>
  );
}
