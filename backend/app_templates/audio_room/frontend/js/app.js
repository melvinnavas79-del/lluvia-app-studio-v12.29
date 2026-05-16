// SPA Router + Views de {{APP_NAME}}
const view = document.getElementById("app-view");

const routes = {
  "/": viewHome,
  "/trending": viewTrending,
  "/rooms": viewRooms,
  "/profile": viewProfile,
  "/create": viewCreate,
  "/room/:id": viewRoom,
};

function navigate(){
  const hash = (location.hash||"#/").slice(1);
  const handler = matchRoute(hash);
  // active nav
  document.querySelectorAll(".nav-item").forEach(a=>{
    a.classList.toggle("active", a.getAttribute("data-route")===hash || (hash.startsWith("/room") && a.dataset.route==="/rooms"));
  });
  handler.fn(handler.params);
}
function matchRoute(path){
  for (const r of Object.keys(routes)){
    if (!r.includes(":")) { if (r===path) return {fn:routes[r], params:{}}; continue; }
    const parts = r.split("/"), p = path.split("/");
    if (parts.length!==p.length) continue;
    const params={}; let ok=true;
    for (let i=0;i<parts.length;i++){
      if (parts[i].startsWith(":")) params[parts[i].slice(1)] = p[i];
      else if (parts[i]!==p[i]){ok=false;break}
    }
    if (ok) return {fn:routes[r], params};
  }
  return {fn:viewHome, params:{}};
}
window.addEventListener("hashchange", navigate);

const CATS = ["Todas","Música","Charlas","Tecnología","Negocios","Bienestar","Deportes","Espanol","English"];
let activeCat = "Todas";

async function viewHome(){
  const u = await ensureUser();
  view.innerHTML = `
    <header class="head">
      <div>
        <h1>{{APP_NAME}}</h1>
        <div class="greet">Hola ${u.name} · descubrí salas en vivo</div>
      </div>
      <div class="avatar">${u.name.slice(0,2).toUpperCase()}</div>
    </header>
    <div class="banner">
      <div class="tag">🔴 Destacado</div>
      <h2>Hosteá tu primera sala</h2>
      <p>Hablale a una audiencia en vivo. Cobrá entrada con membresías premium si querés monetizar.</p>
      <button onclick="location.hash='#/create'">Crear sala →</button>
    </div>
    <div class="cats">${CATS.map(c=>`<div class="cat${c===activeCat?' active':''}" onclick="setCat('${c}')">${c}</div>`).join("")}</div>
    <div class="section-head"><h3>🎙 Salas en vivo</h3><a href="#/rooms">Ver todas</a></div>
    <div id="room-list"><div class="skeleton"></div><div class="skeleton"></div></div>
  `;
  loadRooms("room-list", {category: activeCat==="Todas"?null:activeCat, limit: 8});
}
window.setCat = function(c){ activeCat=c; viewHome(); };

async function viewTrending(){
  await ensureUser();
  view.innerHTML = `
    <header class="head"><div><h1>🔥 Tendencias</h1><div class="greet">Las salas más activas de hoy</div></div></header>
    <div class="section-head"><h3>Top creadores</h3></div>
    <div class="trending-row" id="top-creators"></div>
    <div class="section-head"><h3>Más escuchadas</h3></div>
    <div id="trend-rooms"><div class="skeleton"></div></div>
  `;
  try{
    const top = await api("GET","/api/users/top?limit=10");
    document.getElementById("top-creators").innerHTML = top.users.map((u,i)=>`
      <div class="trend-card" onclick="location.hash='#/profile?u=${u.id}'">
        <div class="rank">#${i+1}</div>
        <div class="ph-small" style="background:${u.color||'#1E293B'}">${u.name.slice(0,2).toUpperCase()}</div>
        <div class="title">${u.name}</div>
        <div class="host"><span>${u.followers||0} seguidores</span></div>
      </div>`).join("") || `<div class="empty"><div class="em">📭</div>Aún no hay creadores activos</div>`;
  }catch(e){toast("Error cargando top: "+e.message)}
  loadRooms("trend-rooms", {sort:"listeners", limit: 20});
}

async function viewRooms(){
  await ensureUser();
  view.innerHTML = `<header class="head"><div><h1>Salas activas</h1></div></header><div id="all-rooms"><div class="skeleton"></div></div>`;
  loadRooms("all-rooms", {limit:50});
}

async function loadRooms(containerId, params){
  try{
    const q = new URLSearchParams();
    Object.entries(params||{}).forEach(([k,v])=>v!=null && q.append(k,v));
    const data = await api("GET","/api/rooms?"+q.toString());
    const c = document.getElementById(containerId);
    if (!data.rooms.length){
      c.innerHTML = `<div class="empty"><div class="em">🎙</div>No hay salas activas. <br/>Sé el primero en crear una.</div>`;
      return;
    }
    c.innerHTML = `<div class="room-grid">${data.rooms.map(roomCard).join("")}</div>`;
  }catch(e){toast("Error: "+e.message)}
}

function roomCard(r){
  const isPremium = r.monetization === "premium";
  return `<div class="room-card ${r.is_live?'live':''}" onclick="location.hash='#/room/${r.id}'">
    <div class="room-avatars">
      <div class="ph" style="background:${stringToColor(r.host_name||'?')}">${(r.host_name||'?').slice(0,2).toUpperCase()}</div>
      ${r.speakers_count>1?`<div class="ph" style="background:${stringToColor(r.title)}">+${r.speakers_count-1}</div>`:''}
    </div>
    <div class="room-info">
      <div class="title">${escapeHtml(r.title)}</div>
      <div class="meta">
        ${r.is_live?'<span class="live-dot"></span><span>EN VIVO</span>':'<span>Próximamente</span>'}
        <span>·</span><span>👥 ${r.listeners_count||0}</span>
        ${isPremium?'<span class="badge premium">💎 PREMIUM</span>':''}
        ${r.category?'<span class="badge">'+r.category+'</span>':''}
      </div>
    </div>
  </div>`;
}

async function viewRoom({id}){
  const u = await ensureUser();
  view.innerHTML = `<div class="room-view"><div class="empty"><div class="em">⏳</div>Cargando sala...</div></div>`;
  let room;
  try{
    room = await api("GET","/api/rooms/"+id);
    if (room.monetization==="premium" && !room.has_access && room.host_id!==u.id){
      view.innerHTML = `<div class="room-view"><div class="empty">
        <div class="em">💎</div>
        <h3>Sala premium</h3>
        <p style="margin:1rem 0">El host pide ${room.price_credits||100} oros para entrar.</p>
        <button class="btn-primary" onclick="payAccess('${id}', ${room.price_credits||100})">Comprar acceso</button>
        <a href="#/" style="display:block;margin-top:1rem;color:var(--text-muted)">← Volver</a>
      </div></div>`;
      return;
    }
  }catch(e){toast("No pude cargar la sala: "+e.message);location.hash='#/';return}

  const role = room.host_id === u.id ? "host" : "listener";
  view.innerHTML = `
    <div class="room-view">
      <div class="room-header">
        <button class="back" onclick="leaveAndGoBack()">←</button>
        <div class="info"><h2>${escapeHtml(room.title)}</h2><div class="desc">${room.is_live?'🔴 EN VIVO · ':''}${(room.listeners_count||0)+(room.speakers_count||0)} personas</div></div>
        <button class="leave" onclick="leaveAndGoBack()">Salir</button>
      </div>
      <div class="role-section">
        <h4>🎙 Hablando ahora (${(room.speakers||[]).length})</h4>
        <div class="speakers-grid" id="speakers"></div>
        <h4>👂 Escuchando (${(room.listeners||[]).length})</h4>
        <div class="listener-grid" id="listeners"></div>
      </div>
      <div class="controls">
        ${role==="host"||role==="speaker" ? '<button id="mute-btn" class="control-btn" onclick="onMute()" title="Silenciar">🎤</button>' : '<button class="control-btn" onclick="requestSpeak()" title="Pedir hablar">✋</button>'}
        <button class="control-btn primary" onclick="reactRoom('❤️')" title="Reaccionar">❤️</button>
        ${role==="host" ? '<button class="control-btn live" onclick="endRoom(\\''+id+'\\')" title="Terminar sala">⏹</button>' : ''}
      </div>
    </div>`;
  renderMembers(room);
  await joinRoom(id, role);
  toast(role==="host"?"Sos el host de esta sala":"Conectado como oyente");
}

function renderMembers(room){
  const sp = document.getElementById("speakers");
  const ls = document.getElementById("listeners");
  if (sp) sp.innerHTML = (room.speakers||[]).map(s=>`
    <div class="member ${s.is_speaking?'speaking':''} ${s.muted?'muted':''}">
      <div class="av" style="background:${stringToColor(s.name)}">${s.name.slice(0,2).toUpperCase()}${s.role==='host'?'<span class="crown">👑</span>':''}</div>
      <div class="name">${escapeHtml(s.name)}</div>
    </div>`).join("") || '<div style="grid-column:1/-1;color:var(--text-muted);text-align:center;padding:1rem">Nadie habla aún</div>';
  if (ls) ls.innerHTML = (room.listeners||[]).map(l=>`
    <div class="member">
      <div class="av" style="background:${stringToColor(l.name)}">${l.name.slice(0,2).toUpperCase()}</div>
      <div class="name">${escapeHtml(l.name)}</div>
    </div>`).join("") || '';
}

window.leaveAndGoBack = function(){ leaveRoom(); location.hash='#/'; };
window.onMute = function(){ const m=toggleMute(); document.getElementById("mute-btn").textContent = m?'🔇':'🎤'; toast(m?"Silenciado":"Mic activo"); };
window.requestSpeak = function(){ socket && socket.emit("request-speak", {room_id:currentRoom}); toast("Pedido enviado al host"); };
window.reactRoom = function(emoji){ socket && socket.emit("reaction", {room_id:currentRoom, emoji}); };
window.endRoom = async function(id){ if(confirm("¿Terminar sala?")){ await api("DELETE","/api/rooms/"+id); leaveRoom(); location.hash='#/'; } };
window.payAccess = async function(id, price){
  try { await api("POST","/api/rooms/"+id+"/purchase",{}); toast("Acceso comprado"); navigate(); }
  catch(e){ toast(e.message) }
};

async function viewCreate(){
  await ensureUser();
  view.innerHTML = `
    <header class="head"><div><h1>Crear sala</h1><div class="greet">Lanzá en vivo en 30 segundos</div></div></header>
    <form class="create-form" onsubmit="return createRoom(event)">
      <label>Título de la sala</label>
      <input name="title" required maxlength="80" placeholder="Charla de tecnología latina"/>
      <label>Descripción</label>
      <textarea name="description" rows="2" maxlength="240" placeholder="¿De qué van a hablar?"></textarea>
      <div class="row">
        <div><label>Categoría</label><select name="category">${CATS.filter(c=>c!=="Todas").map(c=>`<option>${c}</option>`).join("")}</select></div>
        <div><label>Idioma</label><select name="language"><option value="es">Español</option><option value="en">English</option><option value="pt">Português</option></select></div>
      </div>
      <label>Monetización</label>
      <select name="monetization" onchange="document.getElementById('price-wrap').style.display=this.value==='premium'?'block':'none'">
        <option value="free">Gratis · pública (mejor para sponsors)</option>
        <option value="premium">💎 Premium · cobrar acceso</option>
      </select>
      <div id="price-wrap" style="display:none">
        <label>Precio en oros / créditos para entrar</label>
        <input name="price_credits" type="number" min="10" value="100"/>
      </div>
      <button type="submit" class="btn-primary">🎙 Iniciar transmisión en vivo</button>
    </form>`;
}
window.createRoom = async function(e){
  e.preventDefault();
  const f = e.target;
  const body = {
    title: f.title.value.trim(),
    description: f.description.value.trim(),
    category: f.category.value,
    language: f.language.value,
    monetization: f.monetization.value,
    price_credits: parseInt(f.price_credits?.value||0,10),
  };
  try{
    const r = await api("POST","/api/rooms", body);
    toast("Sala creada");
    location.hash = "#/room/"+r.id;
  }catch(e){ toast(e.message) }
  return false;
};

async function viewProfile(){
  const u = await ensureUser();
  const sp = new URLSearchParams(location.hash.split("?")[1]||"");
  const uid = sp.get("u") || u.id;
  let p;
  try{ p = await api("GET","/api/users/"+uid); }catch(e){ p = u; }
  view.innerHTML = `
    <div class="profile-hero">
      <div class="big-av" style="background:${stringToColor(p.name)}">${p.name.slice(0,2).toUpperCase()}</div>
      <div class="name">${escapeHtml(p.name)}</div>
      <div class="handle">@${escapeHtml((p.handle||p.name).toLowerCase().replace(/\s+/g,''))}</div>
      <div class="bio">${escapeHtml(p.bio||"Creador en {{APP_NAME}}. Hosteo charlas en vivo.")}</div>
    </div>
    <div class="stats">
      <div class="stat"><div class="n">${p.followers||0}</div><div class="lbl">Seguidores</div></div>
      <div class="stat"><div class="n">${p.rooms_hosted||0}</div><div class="lbl">Salas</div></div>
      <div class="stat"><div class="n">${p.total_listeners||0}</div><div class="lbl">Audiencia</div></div>
    </div>
    ${uid!==u.id?`
    <div class="profile-cta">
      <button class="follow" onclick="followUser('${uid}')">+ Seguir</button>
      <button class="premium" onclick="toast('Próximamente: suscripción mensual al creador')">💎 Suscribirse</button>
    </div>`:`
    <div class="profile-cta">
      <button class="follow" onclick="logout()">Cerrar sesión</button>
    </div>`}
    <div class="section-head"><h3>Próximas salas</h3></div>
    <div id="user-rooms"><div class="empty">Sin salas programadas</div></div>`;
  loadRooms("user-rooms",{host_id:uid,limit:10});
}
window.followUser = async function(id){ try{ await api("POST","/api/users/"+id+"/follow"); toast("Siguiendo ✓"); }catch(e){toast(e.message)} };
window.logout = function(){ setToken(""); setUser(null); location.hash="#/"; navigate(); };

// helpers
function stringToColor(s){ let h=0; for (const c of s) h = (h*31 + c.charCodeAt(0))%360; return `hsl(${h},65%,45%)`; }
function escapeHtml(s){ return String(s||"").replace(/[<>&"]/g,c=>({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;"}[c])); }

// boot
navigate();
