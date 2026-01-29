from typing import List, Optional
from pydantic import BaseModel

class BatchProcessRequest(BaseModel):
    request_id: str             # UUID, чтобы Первый сервис узнал ответ
    video_urls: List[str]
    insert_video_filename: str  # Имя файла, который уже загружен
    insert_position: int = 50
    webhook_url: str            # Куда слать результат

class ProcessedVideoResult(BaseModel):
    original_url: str
    s3_url: Optional[str] = None
    status: str                 # "success" | "failed"
    error: Optional[str] = None

class WebhookPayload(BaseModel):
    request_id: str
    processed_count: int
    results: List[ProcessedVideoResult]

class TaskAcceptedResponse(BaseModel):
    message: str
    request_id: str
    status: str


class UploadInsertRequest(BaseModel):
    video_url: str