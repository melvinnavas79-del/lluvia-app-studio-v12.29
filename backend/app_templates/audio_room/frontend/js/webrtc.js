// WebRTC + Socket.IO signaling para {{APP_NAME}}
// Modelo: cada cliente publica audio si es host/speaker; los listeners solo reciben.
let socket=null, peers={}, localStream=null, currentRoom=null, currentRole="listener";

const ICE_SERVERS = [
  {urls:"stun:stun.l.google.com:19302"},
  {urls:"stun:stun1.l.google.com:19302"}
];

async function joinRoom(roomId, role){
  currentRoom = roomId; currentRole = role;
  if (!socket){
    socket = io(API, { auth:{ token: getToken() } });
    socket.on("user-joined", onUserJoined);
    socket.on("user-left", onUserLeft);
    socket.on("offer", onOffer);
    socket.on("answer", onAnswer);
    socket.on("ice-candidate", onIce);
    socket.on("role-changed", (d)=>{ if(d.user_id===getUser().id){ currentRole=d.role; if(d.role!=="listener")publishAudio(); } });
  }
  if (role !== "listener") await publishAudio();
  socket.emit("join-room", { room_id: roomId, role });
}

async function publishAudio(){
  if (localStream) return;
  try{
    localStream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}, video:false});
  }catch(e){
    toast("Permitime acceso al micrófono"); throw e;
  }
}

function createPeer(otherId, isInitiator){
  const pc = new RTCPeerConnection({iceServers:ICE_SERVERS});
  peers[otherId]=pc;
  if (localStream) localStream.getTracks().forEach(t=>pc.addTrack(t, localStream));
  pc.ontrack = (e)=>{
    let audio = document.getElementById("audio-"+otherId);
    if (!audio){ audio = document.createElement("audio"); audio.id="audio-"+otherId; audio.autoplay=true; document.body.appendChild(audio); }
    audio.srcObject = e.streams[0];
  };
  pc.onicecandidate = (e)=>{ if (e.candidate) socket.emit("ice-candidate",{to:otherId, candidate:e.candidate}); };
  if (isInitiator){
    pc.createOffer().then(o=>pc.setLocalDescription(o)).then(()=>socket.emit("offer",{to:otherId,sdp:pc.localDescription}));
  }
  return pc;
}

async function onUserJoined(d){ createPeer(d.user_id, true); }
async function onUserLeft(d){
  const pc = peers[d.user_id]; if (pc){ pc.close(); delete peers[d.user_id]; }
  const a = document.getElementById("audio-"+d.user_id); if (a) a.remove();
}
async function onOffer(d){
  const pc = peers[d.from] || createPeer(d.from, false);
  await pc.setRemoteDescription(d.sdp);
  const a = await pc.createAnswer(); await pc.setLocalDescription(a);
  socket.emit("answer", {to:d.from, sdp:pc.localDescription});
}
async function onAnswer(d){ const pc = peers[d.from]; if (pc) await pc.setRemoteDescription(d.sdp); }
async function onIce(d){ const pc = peers[d.from]; if (pc && d.candidate) await pc.addIceCandidate(d.candidate); }

function leaveRoom(){
  if (socket && currentRoom) socket.emit("leave-room", {room_id:currentRoom});
  Object.values(peers).forEach(p=>p.close()); peers={};
  if (localStream){ localStream.getTracks().forEach(t=>t.stop()); localStream=null; }
  document.querySelectorAll("audio[id^='audio-']").forEach(a=>a.remove());
  currentRoom=null; currentRole="listener";
}

function toggleMute(){
  if (!localStream) return false;
  const tr = localStream.getAudioTracks()[0];
  tr.enabled = !tr.enabled;
  return !tr.enabled;
}
