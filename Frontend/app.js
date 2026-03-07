/// app.js

let socket = null;
let usernameGlobal = null;
let reconnectInterval = 1000;
const MAX_RECONNECT = 10000;
let mediaRecorder = null;
let audioChunks = [];

const BASE_URL = "";

const loginBtn = document.getElementById("login-btn");
const logoutBtn = document.getElementById("logout-btn");
const sendBtn = document.getElementById("send-btn");
const recordBtn = document.getElementById("record-btn");
const messageInput = document.getElementById("message-input");
const messagesDiv = document.getElementById("messages");
const loginView = document.getElementById("login-view");
const chatView = document.getElementById("chat-view");
const VAPID_PUBLIC_KEY = 'BEulalZLNf2nIjCYiJTZMlbsn_59u6Hs0BrFBwm_uN_KlU5V-dzV9vUniqxr-r1Q0wlJq-CZEF3dFJ0uN3L-H4M'

async function fetchConAuth(url, options = {}) {
    const token = localStorage.getItem("token");
    if (!token) { cerrarSesion(); return; }
    return await fetch(url, {
        ...options,
        headers: { ...options.headers, "Authorization": `Bearer ${token}` }
    });
}

function cerrarSesion() {
    localStorage.removeItem("token");
    location.reload();
}

function renderizarMensaje(data) {
    const msg = document.createElement("div");
    msg.dataset.id = data.id;
    const esMio = (data.username === usernameGlobal);
    
    msg.classList.add("message-bubble");
    msg.classList.add(esMio ? "message-mine" : "message-other");

    const nombre = document.createElement("span");
    nombre.className = "username";
    nombre.textContent = esMio ? "Yo" : (data.username || `Usuario ${data.user_id}`);
    msg.appendChild(nombre);

    const contenido = document.createElement("div");
    if (data.content) {
        contenido.textContent = data.content;
    } else if (data.audio_url) {
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.src = data.audio_url;
        contenido.appendChild(audio);
    }
    msg.appendChild(contenido);

    let pressTimer;
    msg.addEventListener("touchstart", () => pressTimer = setTimeout(() => mostrarBtnEliminar(msg), 600));
    msg.addEventListener("touchend", () => clearTimeout(pressTimer));

    return msg;
}

function mostrarBtnEliminar(msgElement) {
    if (msgElement.querySelector(".btn-delete")) return;
    const btn = document.createElement("button");
    btn.className = "btn-delete";
    btn.textContent = "🗑";
    btn.onclick = async (e) => {
        e.stopPropagation();
        const res = await fetchConAuth(`${BASE_URL}/messages/${msgElement.dataset.id}`, { method: "DELETE" });
        if (res?.ok) msgElement.remove();
    };
    msgElement.appendChild(btn);
    document.addEventListener("click", () => btn.remove(), { once: true });
}

async function cargarMensajesIniciales() {
    const res = await fetchConAuth(`${BASE_URL}/messages`);
    if (!res) return;
    const messages = await res.json();
    messagesDiv.innerHTML = "";
    messages.forEach(msg => messagesDiv.appendChild(renderizarMensaje(msg)));
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function conectarSocket() {
    const token = localStorage.getItem("token");
    socket = new WebSocket(`wss://chat-familiar-backend-spp8.onrender.com/ws?token=${token}`);
    socket.onmessage = (e) => {
        messagesDiv.appendChild(renderizarMensaje(JSON.parse(e.data)));
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    };
    socket.onclose = () => setTimeout(conectarSocket, reconnectInterval);
}

// Agrega esta función arriba de 'inicializarNotificaciones': CONVERTIR PEM EN 8Array
function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

// Llamar a esta función después de un inicio de sesión exitoso
async function inicializarNotificaciones() {
    if (!('serviceWorker' in navigator)) return;

    // 1. Pedir permiso al usuario
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
        console.log("El usuario rechazó las notificaciones");
        return;
    }

    // 2. Registrar el Service Worker
    const registration = await navigator.serviceWorker.ready;

    // 3. Suscribirse a Push
    try {
        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey : urlBase64ToUint8Array(VAPID_PUBLIC_KEY), 
        });

        // 4. Enviar la suscripción a tu backend
        await fetchConAuth(`${BASE_URL}/subscribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(subscription)
        });
        console.log("Suscrito a notificaciones exitosamente");
    } catch (err) {
        console.error("Error en la suscripción Push:", err);
    }
}

window.addEventListener("load", async () => {
    const token = localStorage.getItem("token");
    if (token) {
        const res = await fetchConAuth(`${BASE_URL}/me`);
        if (res?.ok) {
            const user = await res.json();
            usernameGlobal = user.username;
            loginView.classList.add("hidden");
            chatView.classList.remove("hidden");
            cargarMensajesIniciales();
            conectarSocket();

            // --- AGREGA ESTA LÍNEA ---
            inicializarNotificaciones();
        }
    }
});

loginBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    const fd = new URLSearchParams();
    fd.append("username", document.getElementById("username").value);
    fd.append("password", document.getElementById("password").value);
    const res = await fetch(`${BASE_URL}/login`, { method: "POST", body: fd });
    if (res.ok) {
        const data = await res.json();
        localStorage.setItem("token", data.access_token);
        location.reload();
    } else { alert("Login incorrecto"); }
});

logoutBtn.addEventListener("click", () => cerrarSesion());

sendBtn.addEventListener("click", () => {
    const txt = messageInput.value.trim();
    if (txt && socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ content: txt, audio_url: null }));
        messageInput.value = "";
    }
});

recordBtn.addEventListener("click", async () => {
    if (!mediaRecorder || mediaRecorder.state === "inactive") {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
        mediaRecorder.onstop = async () => {
            const blob = new Blob(audioChunks, { type: "audio/webm" });
            const fd = new FormData();
            fd.append("file", blob, "audio.webm");
            const res = await fetchConAuth(`${BASE_URL}/upload-audio`, { method: "POST", body: fd });
            const data = await res.json();
            socket.send(JSON.stringify({ content: null, audio_url: data.audio_filename }));
        };
        mediaRecorder.start();
        recordBtn.textContent = "⭕";
    } else { mediaRecorder.stop(); recordBtn.textContent = "🎤"; }
});