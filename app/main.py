from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from jose import JWTError, jwt
from app.database import engine, SessionLocal
from app.models import Base, Family, User, Message
from app.auth import hash_password, create_access_token, verify_password, SECRET_KEY, ALGORITHM
from app.manager import manager
from .services.s3_service import upload_audio_to_s3, generate_presigned_url, delete_audio_from_s3
import uuid
import os

app = FastAPI()

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

# =========================
# TEST ROOT
# =========================
@app.get("/")
def root():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        return {
            "status": "Servidor funcionando 🚀",
            "database": "Conectado a Neon ✅",
            "test_query": result.scalar()
        }

# =========================
# REGISTER FAMILY + ADMIN
# =========================
@app.post("/register")
def register_family(
    family_name: str,
    username: str,
    password: str,
    db: Session = Depends(get_db)
):
    existing_family = db.query(Family).filter(Family.name == family_name).first()
    if existing_family:
        raise HTTPException(status_code=400, detail="La familia ya existe")

    new_family = Family(name=family_name)
    db.add(new_family)
    db.commit()
    db.refresh(new_family)

    hashed_password = hash_password(password)

    new_user = User(
        family_id=new_family.id,
        username=username,
        password_hash=hashed_password,
        is_admin=True
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = create_access_token({
        "user_id": new_user.id,
        "family_id": new_family.id
    })

    return {
        "message": "Familia y admin creados correctamente",
        "access_token": token,
        "token_type": "bearer"
    }

# =========================
# LOGIN
# =========================
@app.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == form_data.username).first()

    if not user:
        raise HTTPException(status_code=400, detail="Usuario no encontrado")

    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Contraseña incorrecta")

    token = create_access_token({
        "user_id": user.id,
        "family_id": user.family_id
    })

    return {
        "access_token": token,
        "token_type": "bearer"
    }

# =========================
# CARGAR UVICORN AUTOMATICO
# =========================
@app.get("/ping")
def ping():
    return {"message": "pong"}

# =========================
# GET CURRENT USER
# =========================
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")

        if user_id is None:
            raise HTTPException(status_code=401, detail="Token inválido")

        user = db.query(User).filter(User.id == user_id).first()

        if user is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")

        return user

    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")

# =========================
# PROTECTED ROUTE
# =========================
@app.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "family_id": current_user.family_id,
        "is_admin": current_user.is_admin
    }

# =========================
# CREATE USER (ADMIN ONLY)
# =========================
@app.post("/users")
def create_user(
    username: str,
    password: str,
    is_admin: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Solo administradores pueden crear usuarios")

    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="El usuario ya existe")

    hashed_password = hash_password(password)

    new_user = User(
        username=username,
        password_hash=hashed_password,
        family_id=current_user.family_id,
        is_admin=is_admin
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "Usuario creado correctamente",
        "user_id": new_user.id
    }

# =========================
# GET LAST 10 MESSAGES
# =========================
@app.get("/messages")
def get_last_messages(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    messages = (
        db.query(Message, User.username)
        .join(User, Message.user_id == User.id)
        .filter(Message.family_id == current_user.family_id)
        .order_by(Message.created_at.desc())
        .limit(10)
        .all()
    )

    messages = list(reversed(messages))

    return [
        {
            "id": m.Message.id,
            "user_id": m.Message.user_id,
            "username": m.username,
            "content": m.Message.content,
            "audio_url": generate_presigned_url(m.Message.audio_url) if m.Message.audio_url else None,
            "created_at": str(m.Message.created_at)
        }
        for m in messages
    ]

# =========================
# DELETE MESSAGE (Texto + Audio S3)
# =========================
@app.delete("/messages/{message_id}")
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    message = db.query(Message).filter(Message.id == message_id).first()

    if not message:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")

    if message.family_id != current_user.family_id:
        raise HTTPException(status_code=403, detail="No autorizado")

    if message.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No podés borrar este mensaje")

    # 🔥 Eliminar audio del bucket si existe
    if message.audio_url:
        deleted = delete_audio_from_s3(message.audio_url)
        if not deleted:
            print(f"⚠️ No se pudo eliminar el audio {message.audio_url} de S3")

    # Eliminar mensaje de la base
    db.delete(message)
    db.commit()

    return {"message": "Mensaje eliminado correctamente"}

# =========================
# UPLOAD AUDIO (PROTECTED)
# =========================
ALLOWED_EXTENSIONS = {".webm", ".ogg", ".mp3"}

@app.post("/upload-audio")
def upload_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    # 1️⃣ Obtener extensión
    _, ext = os.path.splitext(file.filename)
    ext = ext.lower()

    # 2️⃣ Validar formato permitido
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Formato no permitido. Usar webm, ogg o mp3."
        )

    # 3️⃣ Generar nombre único seguro
    unique_filename = f"{current_user.id}_{uuid.uuid4()}{ext}"

    # 4️⃣ Subir a S3 con el nuevo nombre
    file.file.seek(0)
    success = upload_audio_to_s3(file.file, unique_filename)

    if not success:
        raise HTTPException(status_code=500, detail="Error subiendo archivo")

    # 🔥 Guardamos solo el nombre real, URL se genera dinámicamente al pedir mensajes
    return {
        "message": "Audio subido correctamente",
        "audio_filename": unique_filename
    }

# =========================
# WEBSOCKET CHAT
# =========================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    family_id = None
    db = SessionLocal()
    try:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except JWTError:
            await websocket.close(code=1008)
            db.close()
            return

        user_id = payload.get("user_id")
        if user_id is None:
            await websocket.close(code=1008)
            return

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.close(code=1008)
            return

        family_id = user.family_id
        await manager.connect(websocket, family_id)

        while True:
            data = await websocket.receive_json()
            content = data.get("content")
            audio_url = data.get("audio_url")

            if not content and not audio_url:
                continue

            message = Message(
                family_id=family_id,
                user_id=user.id,
                content=content,
                audio_url=audio_url
            )

            db.add(message)
            db.commit()
            db.refresh(message)

            # Generamos pre-signed URL dinámicamente
            presigned_audio_url = generate_presigned_url(audio_url) if audio_url else None

            await manager.broadcast(
                family_id,
                {
                    "id": message.id,
                    "user_id": user.id,
                    "username": user.username,
                    "content": content,
                    "audio_url": presigned_audio_url,
                    "created_at": str(message.created_at)
                }
            )

    except WebSocketDisconnect:
        if family_id is not None:
            manager.disconnect(websocket, family_id)
    finally:
        db.close()