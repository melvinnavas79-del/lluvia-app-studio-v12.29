// API client de {{APP_NAME}}
const API = (window.APP_CONFIG && window.APP_CONFIG.API_URL) || "http://localhost:8001";
function getToken(){return localStorage.getItem("ar_token")||""}
function setToken(t){localStorage.setItem("ar_token",t||"")}
function getUser(){try{return JSON.parse(localStorage.getItem("ar_user")||"null")}catch(e){return null}}
function setUser(u){localStorage.setItem("ar_user",JSON.stringify(u||null))}

async function api(method, path, body){
  const r = await fetch(API+path, {
    method, headers:{
      "Content-Type":"application/json",
      ...(getToken()?{Authorization:"Bearer "+getToken()}:{})
    },
    body: body?JSON.stringify(body):undefined
  });
  const j = await r.json().catch(()=>({}));
  if (!r.ok) throw new Error(j.detail||r.statusText);
  return j;
}

function toast(msg, ms=2200){
  const t=document.getElementById("toast");
  t.textContent=msg; t.classList.add("show");
  setTimeout(()=>t.classList.remove("show"), ms);
}

// Auto-login anónimo si no hay token (para demo rápido)
async function ensureUser(){
  if (getUser()) return getUser();
  const name = prompt("Tu nombre para entrar:")||("Invitado-"+Math.floor(Math.random()*9999));
  const r = await api("POST","/api/users/anonymous",{name});
  setToken(r.token); setUser(r.user);
  return r.user;
}
