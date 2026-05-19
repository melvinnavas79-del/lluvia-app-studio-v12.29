// App SPA for {{APP_NAME}} - hash router + 4 vistas
const $ = (s, ctx = document) => ctx.querySelector(s);
const $$ = (s, ctx = document) => Array.from(ctx.querySelectorAll(s));
const app = $("#app");

let socket = null;
let currentVideoId = null;
let drawerOpen = false;

// ============================================================
// Helpers
// ============================================================
function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2200);
}

function fmt(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

function avatar(user) {
  const letter = (user.name || user.author_name || "?")[0].toUpperCase();
  const color = user.avatar_color || user.author_color || "#5B8DEF";
  return `<div class="author-avatar" style="background:${color}">${letter}</div>`;
}

function bigAvatar(user) {
  const letter = (user.name || "?")[0].toUpperCase();
  const color = user.avatar_color || "#5B8DEF";
  return `<div class="big-avatar" style="background:${color}">${letter}</div>`;
}

function setActiveNav(route) {
  $$(".nav-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.route === route);
  });
}

// ============================================================
// Socket.IO
// ============================================================
function initSocket() {
  if (socket) return socket;
  socket = io({ transports: ["websocket", "polling"] });
  socket.on("comment", (c) => {
    if (drawerOpen) {
      const list = $(".drawer-list");
      if (list) {
        list.insertAdjacentHTML("afterbegin", renderComment(c));
      }
    }
  });
  socket.on("gift", (g) => {
    flashGift(g);
  });
  socket.on("viewer-count", (d) => {
    const el = $(".viewer-count");
    if (el) el.textContent = fmt(d.count) + " viendo";
  });
  return socket;
}

function flashGift(g) {
  const el = document.createElement("div");
  el.style.cssText = "position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);font-size:6rem;z-index:200;pointer-events:none;animation:burst 1.4s ease-out forwards;";
  el.textContent = g.gift.emoji;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 1500);
  toast(`${g.from_name} envió ${g.gift.name} ${g.gift.emoji} (${g.value}cr)`);
}

// ============================================================
// FEED (vertical scroll snap)
// ============================================================
async function renderFeed() {
  setActiveNav("#/feed");
  app.innerHTML = `<div class="feed-container" id="feed-container"></div>`;
  const container = $("#feed-container");

  try {
    const data = await API.feed();
    if (!data.videos.length) {
      container.innerHTML = `<div class="center-msg">No hay videos todavia.<br/>Subí el primero!</div>`;
      return;
    }
    container.innerHTML = data.videos.map(renderVideoPage).join("");
    setupVideoObserver(container);
  } catch (e) {
    container.innerHTML = `<div class="center-msg">Error: ${e.message}</div>`;
  }
}

function renderVideoPage(v) {
  const tags = (v.tags || "").split(",").filter(Boolean).map(t => "#" + t.trim()).join(" ");
  return `
    <div class="video-page" data-video-id="${v.id}" data-author-id="${v.author_id}">
      <video src="${v.video_url}" loop muted playsinline preload="metadata"></video>
      ${v.is_live ? '<div class="live-tag">LIVE</div>' : ''}
      <div class="feed-header">
        <span>Siguiendo</span>
        <span class="active">Para Ti</span>
      </div>
      <button class="video-mute" data-act="mute" aria-label="Sonido">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3z" /><path d="M16 7l5 5-5 5M21 7l-5 5 5 5" stroke="currentColor" stroke-width="2" fill="none"/></svg>
      </button>
      <div class="video-actions">
        <button class="action-btn ${v.liked ? 'liked' : ''}" data-act="like">
          <svg viewBox="0 0 24 24" fill="${v.liked ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
          <span class="count" data-likes>${fmt(v.likes)}</span>
        </button>
        <button class="action-btn" data-act="comment">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <span class="count">${fmt(v.comments_count)}</span>
        </button>
        <button class="action-btn" data-act="gift">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7zM12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/></svg>
          <span class="count">${fmt(v.gifts_total_credits || 0)}</span>
        </button>
        <button class="action-btn" data-act="share">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
          <span class="count">Share</span>
        </button>
        <button class="action-btn" data-act="profile">
          ${avatar(v)}
        </button>
      </div>
      <div class="video-overlay-bottom">
        <div class="author-line">
          <span>${v.author_name}</span>
          <span class="author-handle">${v.author_handle}</span>
        </div>
        <div class="video-caption">${escapeHtml(v.caption || "")}</div>
        <div class="video-tags">${tags}</div>
      </div>
    </div>
  `;
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
}

function setupVideoObserver(container) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      const vid = e.target.querySelector("video");
      const id = e.target.dataset.videoId;
      if (e.isIntersecting && e.intersectionRatio > 0.7) {
        if (currentVideoId && currentVideoId !== id && socket) {
          socket.emit("leave-video", { video_id: currentVideoId });
        }
        currentVideoId = id;
        if (socket) socket.emit("join-video", { video_id: id });
        vid?.play().catch(() => {});
      } else {
        vid?.pause();
      }
    });
  }, { root: container, threshold: [0.7] });
  $$(".video-page", container).forEach(p => observer.observe(p));

  // Double-tap to like + actions
  container.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-act]");
    if (!btn) return;
    const page = btn.closest(".video-page");
    const vid = page?.dataset.videoId;
    const act = btn.dataset.act;
    if (act === "like") return doLike(btn, vid);
    if (act === "comment") return openComments(vid);
    if (act === "gift") return openGifts(vid);
    if (act === "share") return doShare(vid);
    if (act === "mute") return toggleMute(page, btn);
    if (act === "profile") {
      const uid = page.dataset.authorId;
      location.hash = `#/profile/${uid}`;
    }
  });

  // Double-tap heart
  let lastTap = 0;
  container.addEventListener("click", (ev) => {
    const page = ev.target.closest(".video-page");
    if (!page || ev.target.closest("[data-act]")) return;
    const now = Date.now();
    if (now - lastTap < 320) {
      const rect = page.getBoundingClientRect();
      spawnHeart(page, ev.clientX - rect.left, ev.clientY - rect.top);
      const likeBtn = $('[data-act="like"]', page);
      if (likeBtn && !likeBtn.classList.contains("liked")) {
        doLike(likeBtn, page.dataset.videoId);
      }
    } else {
      const vid = page.querySelector("video");
      if (vid.paused) vid.play(); else vid.pause();
    }
    lastTap = now;
  });
}

function spawnHeart(page, x, y) {
  const h = document.createElement("div");
  h.className = "like-burst";
  h.textContent = "❤";
  h.style.left = x + "px";
  h.style.top = y + "px";
  page.appendChild(h);
  setTimeout(() => h.remove(), 1000);
}

async function doLike(btn, vid) {
  try {
    const r = await API.like(vid);
    btn.classList.toggle("liked", r.liked);
    const c = btn.querySelector("[data-likes]");
    if (c) c.textContent = fmt(r.likes);
  } catch (e) { toast(e.message); }
}

function toggleMute(page, btn) {
  const v = page.querySelector("video");
  v.muted = !v.muted;
  btn.style.opacity = v.muted ? "1" : "0.5";
}

function doShare(vid) {
  const url = `${location.origin}/#/video/${vid}`;
  if (navigator.share) {
    navigator.share({ url, title: "Mirá este video" }).catch(() => {});
  } else {
    navigator.clipboard?.writeText(url);
    toast("Link copiado");
  }
}

// ============================================================
// COMMENTS DRAWER
// ============================================================
async function openComments(vid) {
  drawerOpen = true;
  const data = await API.comments(vid).catch(() => ({ comments: [] }));
  const drawer = document.createElement("div");
  drawer.innerHTML = `
    <div class="drawer-backdrop open" data-close></div>
    <div class="drawer open">
      <div class="drawer-handle"></div>
      <div class="drawer-title">Comentarios · ${data.comments.length}</div>
      <div class="drawer-list">
        ${data.comments.map(renderComment).join("") || '<div class="center-msg" style="height:120px">Sé el primero en comentar</div>'}
      </div>
      <form class="drawer-input" data-comment-form>
        <input placeholder="Agrega un comentario..." maxlength="300" required />
        <button type="submit">Enviar</button>
      </form>
    </div>
  `;
  document.body.appendChild(drawer);
  drawer.addEventListener("click", (e) => {
    if (e.target.dataset.close !== undefined) closeDrawer(drawer);
  });
  drawer.querySelector("[data-comment-form]").addEventListener("submit", async (e) => {
    e.preventDefault();
    const inp = e.target.querySelector("input");
    const t = inp.value.trim();
    if (!t) return;
    inp.value = "";
    try {
      await API.addComment(vid, t);
    } catch (err) { toast(err.message); }
  });
}

function renderComment(c) {
  return `
    <div class="comment-item">
      ${avatar({ name: c.author_name, avatar_color: c.author_color })}
      <div class="text">
        <div class="name">${c.author_handle || c.author_name}</div>
        ${escapeHtml(c.text)}
      </div>
    </div>
  `;
}

function closeDrawer(drawer) {
  drawerOpen = false;
  drawer.querySelectorAll(".open").forEach(el => el.classList.remove("open"));
  setTimeout(() => drawer.remove(), 250);
}

// ============================================================
// GIFTS DRAWER
// ============================================================
async function openGifts(vid) {
  const me = API.getMe();
  const data = await API.listGifts().catch(() => ({ gifts: [] }));
  const drawer = document.createElement("div");
  drawer.innerHTML = `
    <div class="drawer-backdrop open" data-close></div>
    <div class="drawer open">
      <div class="drawer-handle"></div>
      <div class="drawer-title">Enviar regalo · Saldo: ${me?.credits || 0} cr</div>
      <div class="gifts-grid">
        ${data.gifts.map(g => `
          <div class="gift-cell ${(me?.credits || 0) < g.credits ? 'disabled' : ''}" data-gift="${g.key}">
            <div class="emoji">${g.emoji}</div>
            <div class="nm">${g.name}</div>
            <div class="cr">${g.credits} cr</div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
  document.body.appendChild(drawer);
  drawer.addEventListener("click", async (e) => {
    if (e.target.dataset.close !== undefined) return closeDrawer(drawer);
    const cell = e.target.closest("[data-gift]");
    if (!cell || cell.classList.contains("disabled")) return;
    try {
      const r = await API.sendGift(vid, cell.dataset.gift);
      API.setMe({ ...me, credits: r.remaining_credits });
      toast(`Regalo enviado · ${r.gift.emoji}`);
      closeDrawer(drawer);
    } catch (err) { toast(err.message); }
  });
}

// ============================================================
// DISCOVER
// ============================================================
async function renderDiscover() {
  setActiveNav("#/discover");
  app.innerHTML = `
    <div class="discover-page">
      <div class="discover-search"><input placeholder="Buscar creadores, sonidos..." /></div>
      <div class="discover-section"><h3>Top creadores</h3><div id="creators-list"></div></div>
      <div class="discover-section"><h3>Trending</h3><div class="discover-grid" id="trending-grid"></div></div>
    </div>
  `;
  try {
    const [creators, trending] = await Promise.all([API.topCreators(), API.trending()]);
    $("#creators-list").innerHTML = creators.creators.map(c => `
      <div class="creator-row" onclick="location.hash='#/profile/${c.id}'">
        ${avatar(c)}
        <div class="info">
          <div class="name">${c.name}</div>
          <div class="handle">${c.handle}</div>
        </div>
        <div class="followers">${fmt(c.followers)} seguidores</div>
      </div>
    `).join("");
    $("#trending-grid").innerHTML = trending.videos.map(v => `
      <div class="grid-cell" onclick="location.hash='#/feed'">
        ${v.thumb_url ? `<img src="${v.thumb_url}" alt="" />` : ''}
        <div class="stats">▶ ${fmt(v.views)}</div>
      </div>
    `).join("");
  } catch (e) {
    $("#creators-list").innerHTML = `<div class="center-msg">${e.message}</div>`;
  }
}

// ============================================================
// UPLOAD
// ============================================================
function renderUpload() {
  setActiveNav("#/upload");
  app.innerHTML = `
    <div class="upload-page">
      <h2>Subir video</h2>
      <p class="sub">Pega la URL pública de tu video (mp4 / hls). Te llevamos al feed apenas se publique.</p>
      <form id="upload-form">
        <div class="upload-field">
          <label>URL del video (mp4 / m3u8)</label>
          <input name="video_url" required placeholder="https://..." />
        </div>
        <div class="upload-field">
          <label>Caption</label>
          <textarea name="caption" maxlength="400" placeholder="Escribi algo viral 🔥"></textarea>
        </div>
        <div class="upload-field">
          <label>Tags (coma separada)</label>
          <input name="tags" placeholder="dance, viral, live" />
        </div>
        <div class="upload-field">
          <label>Thumbnail URL (opcional)</label>
          <input name="thumb_url" placeholder="https://..." />
        </div>
        <button type="submit" class="upload-submit">Publicar</button>
        <div class="upload-tip">
          💡 <b>Tip:</b> para hacer LIVE de verdad, conectá un servidor RTMP (ej. Nginx-RTMP) o usa Mux Live / Cloudflare Stream y pega aquí el m3u8 del stream. Este template funciona con cualquier URL mp4/HLS pública.
        </div>
      </form>
    </div>
  `;
  $("#upload-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    data.duration_sec = 0;
    try {
      await API.upload(data);
      toast("Video publicado ✓");
      setTimeout(() => location.hash = "#/feed", 600);
    } catch (err) { toast(err.message); }
  });
}

// ============================================================
// PROFILE
// ============================================================
async function renderProfile(uid) {
  setActiveNav("#/profile");
  const me = API.getMe();
  const targetId = uid || me?.id;
  if (!targetId) { app.innerHTML = `<div class="center-msg">No autenticado</div>`; return; }
  try {
    const u = await API.user(targetId);
    const isMe = targetId === me?.id;
    app.innerHTML = `
      <div class="profile-page">
        <div class="profile-head">
          ${bigAvatar(u)}
          <div class="name">${u.name}</div>
          <div class="handle">${u.handle}</div>
          <div class="bio">${u.bio || "Sin bio aun"}</div>
        </div>
        <div class="profile-stats">
          <div class="stat"><div class="stat-n">${fmt(u.following)}</div><div class="stat-l">Siguiendo</div></div>
          <div class="stat"><div class="stat-n">${fmt(u.followers)}</div><div class="stat-l">Seguidores</div></div>
          <div class="stat"><div class="stat-n">${fmt(u.total_likes)}</div><div class="stat-l">Me gusta</div></div>
        </div>
        <div class="profile-cta">
          ${isMe ? `<button class="secondary" data-act="logout">Cerrar sesion</button>` :
            `<button data-act="follow">${u.is_following ? "Siguiendo ✓" : "Seguir"}</button>
             <button class="secondary" data-act="gift-creator">🎁 Regalar</button>`}
        </div>
        ${isMe ? `
          <div class="profile-credits">
            <div class="icon">💎</div>
            <div class="lbl">
              <div class="t">${u.credits} créditos</div>
              <div class="s">Recargá para enviar regalos a creadores</div>
            </div>
            <button data-act="topup">Recargar</button>
          </div>
        ` : ""}
        <div class="profile-tabs">
          <div class="tab active">Videos (${u.videos.length})</div>
          <div class="tab">Likes</div>
        </div>
        <div class="discover-grid" style="padding:8px;">
          ${u.videos.map(v => `
            <div class="grid-cell">
              ${v.thumb_url ? `<img src="${v.thumb_url}" alt=""/>` : ''}
              <div class="stats">▶ ${fmt(v.views)}</div>
            </div>
          `).join("")}
        </div>
      </div>
    `;
    app.addEventListener("click", async (e) => {
      const a = e.target.closest("[data-act]");
      if (!a) return;
      if (a.dataset.act === "follow") {
        const r = await API.follow(targetId);
        a.textContent = r.following ? "Siguiendo ✓" : "Seguir";
      } else if (a.dataset.act === "logout") {
        localStorage.clear();
        location.reload();
      } else if (a.dataset.act === "topup") {
        const amt = parseInt(prompt("Cuantos créditos querés (test)?", "500"));
        if (amt > 0) {
          const r = await API.topup(me.id, amt);
          API.setMe({ ...me, credits: r.credits });
          renderProfile();
        }
      }
    }, { once: true });
  } catch (e) {
    app.innerHTML = `<div class="center-msg">${e.message}</div>`;
  }
}

// ============================================================
// ROUTER
// ============================================================
function route() {
  const h = location.hash || "#/feed";
  if (h.startsWith("#/feed")) return renderFeed();
  if (h.startsWith("#/discover")) return renderDiscover();
  if (h.startsWith("#/upload")) return renderUpload();
  if (h.startsWith("#/profile/")) return renderProfile(h.split("/")[2]);
  if (h.startsWith("#/profile")) return renderProfile();
  return renderFeed();
}

window.addEventListener("hashchange", route);
$$(".nav-btn").forEach(b => b.addEventListener("click", () => {
  location.hash = b.dataset.route;
}));

(async () => {
  try {
    await API.ensureAuth();
    initSocket();
    route();
  } catch (e) {
    app.innerHTML = `<div class="center-msg">Error de auth: ${e.message}</div>`;
  }
})();
