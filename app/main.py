from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from app.database import engine, SessionLocal
from app.models import Base, Family, User, Message, Device
from app.auth import hash_password, create_access_token, verify_password, SECRET_KEY, ALGORITHM
from app.manager import manager
from .services.s3_service import upload_audio_to_s3, generate_presigned_url, delete_audio_from_s3
from pywebpush import webpush, WebPushException
import uuid
import os
import json
from jose import jwt, JWTError

# Configuración VAPID
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {"sub": "mailto:admin@chatfamiliar.com"}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None: raise HTTPException(status_code=401, detail="Token inválido")
        user = db.query(User).filter(User.id == user_id).first()
        if user is None: raise HTTPException(status_code=401, detail="Usuario no encontrado")
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

# --- FUNCIÓN DE NOTIFICACIONES (Aislada para evitar caídas) ---
def enviar_notificaciones_push(db: Session, sender: User, message: Message):
    # Buscar dispositivos de otros miembros de la familia[cite: 6, 8]
    other_devices = db.query(Device).join(User).filter(
        User.family_id == sender.family_id, 
        User.id != sender.id
    ).all()
    
    payload = json.dumps({
        "title": f"Mensaje de {sender.username}",
        "body": message.content if message.content else "🎤 Audio nuevo"
    })

    for device in other_devices:
        try:
            webpush(
                subscription_info=json.loads(device.subscription_info),
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except Exception as e:
            print(f"Error enviando push: {e}")

# --- RUTAS ---

@app.post("/subscribe")
def subscribe(subscription_info: dict = Body(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Guardamos o actualizamos la suscripción[cite: 6, 8]
    existing = db.query(Device).filter(Device.user_id == current_user.id).first()
    if existing:
        existing.subscription_info = json.dumps(subscription_info)
    else:
        new_device = Device(user_id=current_user.id, subscription_info=json.dumps(subscription_info))
        db.add(new_device)
    db.commit()
    return {"message": "Suscripción guardada"}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Credenciales incorrectas")
    token = create_access_token({"user_id": user.id, "family_id": user.family_id})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/messages")
def get_last_messages(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    messages = db.query(Message, User.username).join(User, Message.user_id == User.id).filter(
        Message.family_id == current_user.family_id
    ).order_by(Message.created_at.desc()).limit(15).all()
    return [{"id": m.Message.id, "username": m.username, "content": m.Message.content, 
             "audio_url": generate_presigned_url(m.Message.audio_url) if m.Message.audio_url else None} 
            for m in reversed(messages)]

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    db = SessionLocal()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = db.query(User).filter(User.id == payload.get("user_id")).first()
        if not user:
            await websocket.close(code=1008)
            return

        await manager.connect(websocket, user.family_id) #[cite: 7]
        
        while True:
            try:
                data = await websocket.receive_json()
                # Crear y guardar mensaje[cite: 6, 8]
                message = Message(
                    family_id=user.family_id, 
                    user_id=user.id, 
                    content=data.get("content"), 
                    audio_url=data.get("audio_url")
                )
                db.add(message)
                db.commit()
                db.refresh(message)

                msg_payload = {
                    "id": message.id, 
                    "content": message.content, 
                    "username": user.username, 
                    "audio_url": generate_presigned_url(message.audio_url) if message.audio_url else None
                }

                # Broadcast inmediato[cite: 7]
                await manager.broadcast(user.family_id, msg_payload)
                
                # Push en segundo plano
                enviar_notificaciones_push(db, user, message)

            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"Error procesando mensaje WS: {e}")
                continue 

    except Exception as e:
        print(f"Error de conexión WebSocket: {e}")
    finally:
        manager.disconnect(websocket, user.family_id) #[cite: 7]
        db.close()

# Servir archivos estáticos del frontend
app.mount("/", StaticFiles(directory="Frontend", html=True), name="frontend")