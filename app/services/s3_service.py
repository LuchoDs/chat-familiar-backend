import boto3
import os
from dotenv import load_dotenv
from botocore.exceptions import ClientError

load_dotenv()

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION"),
)

BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")

# Tiempo de expiración en segundos para la URL temporal (4 horas)
PRESIGNED_URL_EXPIRATION = 14400

def upload_audio_to_s3(file_obj, filename: str) -> bool:
    """
    Sube un archivo al bucket S3 de forma privada.
    
    Args:
        file_obj: objeto archivo (UploadFile.file de FastAPI).
        filename: nombre que se asignará al archivo en S3.
    
    Returns:
        True si se sube correctamente, False si hay error.
    """
    try:
        s3.upload_fileobj(
            file_obj,
            BUCKET_NAME,
            filename,
            ExtraArgs={
                "ContentType": "audio/mpeg",
                "ACL": "private"  # aseguramos que el objeto sea privado
            }
        )
        return True

    except Exception as e:
        print("Error subiendo a S3:", e)
        return False

def generate_presigned_url(filename: str, expiration: int = PRESIGNED_URL_EXPIRATION) -> str | None:
    """
    Genera una URL temporal para acceder al archivo privado en S3.
    
    Args:
        filename: nombre del archivo en S3.
        expiration: tiempo de expiración de la URL en segundos.
    
    Returns:
        URL pre-firmada como string si se genera correctamente, None en caso de error.
    """
    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": filename},
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        print("Error generando URL pre-firmada:", e)
        return None

def delete_audio_from_s3(filename: str) -> bool:
    """
    Elimina un archivo del bucket S3.
    
    Args:
        filename: nombre del archivo en S3.
    
    Returns:
        True si se elimina correctamente, False si hay error.
    """
    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=filename)
        return True
    except ClientError as e:
        print("Error eliminando archivo de S3:", e)
        return False