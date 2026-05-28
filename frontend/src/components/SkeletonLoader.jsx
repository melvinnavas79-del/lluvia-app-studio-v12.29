/**
 * SkeletonLoader — Shimmer placeholders para estados de carga.
 * Usa el design system de App.css (CSS vars, radios, shadows).
 */

export function SkeletonLine({ width = "100%", height = "1rem", style = {} }) {
  return (
    <div
      className="sk-line"
      style={{ width, height, borderRadius: "var(--r-sm)", ...style }}
      aria-hidden="true"
    />
  );
}

export function SkeletonCard({ height = 120, style = {} }) {
  return (
    <div
      className="sk-card"
      style={{ height, borderRadius: "var(--r-lg)", ...style }}
      aria-hidden="true"
    />
  );
}

export function SkeletonAvatar({ size = 44 }) {
  return (
    <div
      className="sk-line"
      style={{ width: size, height: size, borderRadius: "50%", flexShrink: 0 }}
      aria-hidden="true"
    />
  );
}

/** Fila de agent/session en la sidebar */
export function SkeletonSessionRow() {
  return (
    <div className="sk-session-row" aria-hidden="true">
      <SkeletonAvatar size={36} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
        <SkeletonLine width="65%" height="0.85rem" />
        <SkeletonLine width="45%" height="0.75rem" />
      </div>
    </div>
  );
}

/** Stat card para el overview del dashboard */
export function SkeletonStatCard() {
  return (
    <div className="sk-stat-card" aria-hidden="true">
      <SkeletonLine width="40%" height="0.8rem" />
      <SkeletonLine width="55%" height="2rem" style={{ marginTop: "0.5rem" }} />
      <SkeletonLine width="70%" height="0.75rem" style={{ marginTop: "0.5rem" }} />
    </div>
  );
}

/** Placeholder de mensaje de chat */
export function SkeletonChatMessage({ align = "left" }) {
  const isRight = align === "right";
  return (
    <div
      className="sk-chat-msg"
      style={{ alignItems: isRight ? "flex-end" : "flex-start" }}
      aria-hidden="true"
    >
      {!isRight && <SkeletonAvatar size={32} />}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", maxWidth: "60%" }}>
        <SkeletonLine width="100%" height="0.9rem" />
        <SkeletonLine width="85%" height="0.9rem" />
        <SkeletonLine width="65%" height="0.9rem" />
      </div>
      {isRight && <SkeletonAvatar size={32} />}
    </div>
  );
}

/** Skeleton completo de la consola (lista de sesiones) */
export function SkeletonConsoleSessions({ count = 6 }) {
  return (
    <div className="sk-sessions" aria-label="Cargando sesiones...">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonSessionRow key={i} />
      ))}
    </div>
  );
}

/** Skeleton del dashboard overview */
export function SkeletonDashboard() {
  return (
    <div aria-label="Cargando datos..." style={{ padding: "1.5rem 0" }}>
      <div className="sk-stats-grid">
        {Array.from({ length: 6 }).map((_, i) => <SkeletonStatCard key={i} />)}
      </div>
      <div style={{ marginTop: "2rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        <SkeletonLine width="30%" height="1.25rem" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="sk-session-row">
            <SkeletonAvatar size={40} />
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              <SkeletonLine width={`${50 + Math.random() * 30}%`} height="0.9rem" />
              <SkeletonLine width={`${30 + Math.random() * 20}%`} height="0.75rem" />
            </div>
            <SkeletonLine width="80px" height="1.5rem" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** App-level: pantalla completa de carga */
export function SkeletonAppShell({ brandName = "Lluvia" }) {
  return (
    <div className="sk-app-shell">
      <div className="sk-app-header">
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <SkeletonAvatar size={36} />
          <SkeletonLine width="120px" height="1rem" />
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <SkeletonLine width="80px" height="36px" style={{ borderRadius: "var(--r-md)" }} />
          <SkeletonLine width="100px" height="36px" style={{ borderRadius: "var(--r-md)" }} />
        </div>
      </div>
      <div className="sk-app-body">
        <div className="sk-sidebar">
          {Array.from({ length: 8 }).map((_, i) => <SkeletonSessionRow key={i} />)}
        </div>
        <div className="sk-main-area">
          <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem", padding: "2rem" }}>
            <SkeletonChatMessage align="right" />
            <SkeletonChatMessage align="left" />
            <SkeletonChatMessage align="right" />
            <SkeletonChatMessage align="left" />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Estado vacío genérico */
export function EmptyState({ icon = "✦", title, description, action, onAction, actionLabel }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      {title && <h3 className="empty-title">{title}</h3>}
      {description && <p className="empty-desc">{description}</p>}
      {onAction && (
        <button className="cta-primary" onClick={onAction} style={{ marginTop: "1.25rem" }}>
          {actionLabel || action}
        </button>
      )}
    </div>
  );
}
