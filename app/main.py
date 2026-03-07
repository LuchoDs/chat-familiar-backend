from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from jose import JWTError, jwt
from app.database import engine, SessionLocal
from app.models import Base, Family, User, Message, Device
from app.auth import hash_password, create_access_token, verify_password, SECRET_KEY, ALGORITHM
from app.manager import manager
from .services.s3_service import upload_audio_to_s3, generate_presigned_url, delete_audio_from_s3
from pywebpush import webpush, WebPushException
import uuid
import os
import json

# Obtener claves de entorno (Se configuran en Render)
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {"sub": "mailto:admin@chatfamiliar.com"}

app = FastAPI()

# =========================
# RUTAS DE INTERFAZ (FRONTEND)
# =========================
app.mount("/", StaticFiles(directory="Frontend", html=True), name="frontend")

# CORS reducido: solo lo necesario
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

# =========================
# DEPENDENCIA DB
# =========================
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
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
    
# =========================
# NOTIFICACIONES PUSH
# =========================
@app.post("/subscribe")
def subscribe(subscription_info: dict = Body(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.query(Device).filter(Device.user_id == current_user.id, Device.subscription_info == json.dumps(subscription_info)).first()
    if not existing:
        new_device = Device(user_id=current_user.id, subscription_info=json.dumps(subscription_info))
        db.add(new_device)
        db.commit()
    return {"message": "Suscripción guardada"}

# =========================
# RUTAS DE API
# =========================
@app.post("/register")
def register_family(family_name: str, username: str, password: str, db: Session = Depends(get_db)):
    existing_family = db.query(Family).filter(Family.name == family_name).first()
    if existing_family: raise HTTPException(status_code=400, detail="La familia ya existe")
    new_family = Family(name=family_name)
    db.add(new_family)
    db.commit()
    db.refresh(new_family)
    hashed_password = hash_password(password)
    new_user = User(family_id=new_family.id, username=username, password_hash=hashed_password, is_admin=True)
    db.add(new_user)
    db.commit()
    token = create_access_token({"user_id": new_user.id, "family_id": new_family.id})
    return {"access_token": token, "token_type": "bearer"}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Credenciales incorrectas")
    token = create_access_token({"user_id": user.id, "family_id": user.family_id})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username, "family_id": current_user.family_id, "is_admin": current_user.is_admin}

@app.get("/messages")
def get_last_messages(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    messages = db.query(Message, User.username).join(User, Message.user_id == User.id).filter(Message.family_id == current_user.family_id).order_by(Message.created_at.desc()).limit(10).all()
    return [{"id": m.Message.id, "username": m.username, "content": m.Message.content, "audio_url": generate_presigned_url(m.Message.audio_url) if m.Message.audio_url else None} for m in reversed(messages)]

@app.delete("/messages/{message_id}")
def delete_message(message_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message or message.family_id != current_user.family_id: raise HTTPException(status_code=404, detail="No encontrado")
    if message.audio_url: delete_audio_from_s3(message.audio_url)
    db.delete(message)
    db.commit()
    return {"message": "Eliminado"}

@app.post("/upload-audio")
def upload_audio(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {".webm", ".ogg", ".mp3"}: raise HTTPException(status_code=400, detail="Formato no permitido")
    unique_filename = f"{current_user.id}_{uuid.uuid4()}{ext}"
    if not upload_audio_to_s3(file.file, unique_filename): raise HTTPException(status_code=500, detail="Error")
    return {"audio_filename": unique_filename}

# =========================
# WEBSOCKET
# =========================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    db = SessionLocal()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = db.query(User).filter(User.id == payload.get("user_id")).first()
        if not user: await websocket.close(code=1008); return
        await manager.connect(websocket, user.family_id)
        while True:
            data = await websocket.receive_json()
            message = Message(family_id=user.family_id, user_id=user.id, content=data.get("content"), audio_url=data.get("audio_url"))
            db.add(message); db.commit(); db.refresh(message)
            other_devices = db.query(Device).join(User).filter(User.family_id == user.family_id, User.id != user.id).all()
            push_data = json.dumps({"title": f"Mensaje de {user.username}", "body": message.content if message.content else "🎤 Audio"})
            for device in other_devices:
                try:
                    webpush(subscription_info=json.loads(device.subscription_info), data=push_data, vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims=VAPID_CLAIMS)
                except WebPushException:
                    pass
            await manager.broadcast(user.family_id, {"id": message.id, "content": message.content, "username": user.username, "audio_url": generate_presigned_url(message.audio_url) if message.audio_url else None})
    except Exception:
        pass
    finally:
        db.close()