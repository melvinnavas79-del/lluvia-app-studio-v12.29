// API client for {{APP_NAME}}
const API = (() => {
  const base = ""; // mismo origen
  let token = localStorage.getItem("token") || null;
  let me = JSON.parse(localStorage.getItem("me") || "null");

  async function _fetch(path, opts = {}) {
    const h = opts.headers || {};
    if (token) h["Authorization"] = "Bearer " + token;
    if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
      h["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const r = await fetch(base + path, { ...opts, headers: h });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return r.json();
  }

  async function ensureAuth() {
    if (token && me) return me;
    const data = await _fetch("/api/users/anonymous", { method: "POST", body: {} });
    token = data.token;
    me = { id: data.user_id, name: data.name, handle: data.handle, credits: data.credits };
    localStorage.setItem("token", token);
    localStorage.setItem("me", JSON.stringify(me));
    return me;
  }

  function getToken() { return token; }
  function getMe() { return me; }
  function setMe(u) { me = u; localStorage.setItem("me", JSON.stringify(u)); }

  return {
    ensureAuth, getToken, getMe, setMe,
    feed: (offset = 0, limit = 12) => _fetch(`/api/videos/feed?offset=${offset}&limit=${limit}`),
    trending: () => _fetch("/api/videos/trending"),
    topCreators: () => _fetch("/api/users/top"),
    videoDetail: (id) => _fetch(`/api/videos/${id}`),
    like: (id) => _fetch(`/api/videos/${id}/like`, { method: "POST" }),
    follow: (uid) => _fetch(`/api/users/${uid}/follow`, { method: "POST" }),
    user: (uid) => _fetch(`/api/users/${uid}`),
    comments: (vid) => _fetch(`/api/videos/${vid}/comments`),
    addComment: (vid, text) => _fetch(`/api/videos/${vid}/comment`, { method: "POST", body: { text } }),
    listGifts: () => _fetch("/api/gifts"),
    sendGift: (vid, gift_key) => _fetch(`/api/videos/${vid}/gift`, { method: "POST", body: { gift_key } }),
    upload: (payload) => _fetch("/api/videos", { method: "POST", body: payload }),
    topup: (uid, amount) => _fetch(`/api/users/${uid}/topup`, { method: "POST", body: { amount } }),
  };
})();
