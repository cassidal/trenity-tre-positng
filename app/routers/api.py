import shutil
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File

from app.models import BatchProcessRequest, TaskAcceptedResponse
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

@router.post("/upload-insert")
async def upload_insert_video(file: UploadFile = File(...)):
    """
    Загрузка файла-вставки на сервер воркера.
    """
    try:
        file_path = pipeline_service.upload_dir / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"status": "uploaded", "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))