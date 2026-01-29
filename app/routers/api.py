import httpx
from pathlib import Path
from urllib.parse import urlparse, unquote

from fastapi import APIRouter, HTTPException, BackgroundTasks

from app.models import BatchProcessRequest, TaskAcceptedResponse, UploadInsertRequest
from app.services.pipeline_service import PipelineService

router = APIRouter(prefix="/api", tags=["api"])
pipeline_service = PipelineService()

@router.post("/process", status_code=202, response_model=TaskAcceptedResponse)
async def process_batch_videos(
    request: BatchProcessRequest,
    background_tasks: BackgroundTasks
):
    """
    Принимает задачу и запускает process_and_notify в фоне.
    """
    insert_path = pipeline_service.upload_dir / request.insert_video_filename
    if not insert_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Insert video '{request.insert_video_filename}' not found on worker."
        )

    background_tasks.add_task(pipeline_service.execute_background_flow, request)

    return TaskAcceptedResponse(
        message="Task accepted. Results will be sent via webhook.",
        request_id=request.request_id,
        status="pending"
    )

def _filename_from_url(url: str) -> str:
    """Извлекает имя файла из URL или возвращает имя по умолчанию."""
    path = urlparse(url).path
    name = unquote(Path(path).name.strip())
    return name or "insert_video.mp4"


@router.post("/upload-insert")
async def upload_insert_video(payload: UploadInsertRequest):
    """
    Принимает body {"video_url": s3_url}, скачивает видео по URL и сохраняет в uploads.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(payload.video_url, timeout=60.0)
            resp.raise_for_status()

        filename = _filename_from_url(payload.video_url)
        file_path = pipeline_service.upload_dir / filename
        file_path.write_bytes(resp.content)

        return {"status": "uploaded", "filename": filename}
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to download video: HTTP {e.response.status_code}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))