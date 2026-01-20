import httpx
from pathlib import Path
from typing import List, Dict, Any

from app.models import BatchProcessRequest, WebhookPayload, ProcessedVideoResult
from app.services.s3_service import S3Service
from app.services.video_processor_service import VideoProcessorService


class PipelineService:
    def __init__(self):
        self.video_processor = VideoProcessorService()
        self.s3_service = S3Service()
        self.upload_dir = Path("uploads")
        self.upload_dir.mkdir(exist_ok=True)

    async def execute_background_flow(self, request: BatchProcessRequest):
        print(f"[Pipeline] Started background task for Request ID: {request.request_id}")

        # --- ШАГ 1: Обработка видео ---
        results = await self._run_batch(
            video_urls=request.video_urls,
            insert_video_filename=request.insert_video_filename,
            insert_position=request.insert_position
        )

        # --- ШАГ 2: Подготовка ответа ---
        payload = WebhookPayload(
            request_id=request.request_id,
            processed_count=len(results),
            results=results
        )

        # --- ШАГ 3: Отправка Webhook ---
        await self._send_webhook(request.webhook_url, payload)

    async def _run_batch(
            self, video_urls: List[str], insert_video_filename: str, insert_position: int
    ) -> List[ProcessedVideoResult]:

        insert_path = self.upload_dir / insert_video_filename
        results = []

        for url in video_urls:
            try:
                s3_url = await self._process_single_video(url, str(insert_path), insert_position)

                results.append(ProcessedVideoResult(
                    original_url=url,
                    s3_url=s3_url,
                    status="success"
                ))
            except Exception as e:
                print(f"[Pipeline] Error processing {url}: {e}")
                results.append(ProcessedVideoResult(
                    original_url=url,
                    status="failed",
                    error=str(e)
                ))
        return results

    async def _process_single_video(self, video_url: str, insert_path: str, insert_position: int) -> str:
        """
        Обработка одного файла с гарантированным удалением.
        """
        processed_path = None
        try:
            # 1. Скачивание и монтаж
            # VideoProcessorService внутри себя почистит свои временные файлы (part1, original и т.д.)
            # и вернет путь к готовому результату.
            processed_path = await self.video_processor.process_video(
                video_url, insert_path, insert_position=insert_position
            )

            # 2. Загрузка
            s3_url = await self.s3_service.upload_file(processed_path)

            return s3_url

        finally:
            # 3. ГАРАНТИРОВАННАЯ ОЧИСТКА РЕЗУЛЬТАТА
            # Этот блок выполнится даже если s3_service выкинет ошибку.
            if processed_path:
                try:
                    p = Path(processed_path)
                    if p.exists():
                        p.unlink()
                        print(f"[Pipeline] Cleaned up: {processed_path}")
                except Exception as e:
                    print(f"[Pipeline] Warning: Failed to delete processed file {processed_path}: {e}")

    async def _send_webhook(self, url: str, payload: WebhookPayload):
        print(f"[Pipeline] Sending results to {url}...")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload.dict(), timeout=20.0)
                resp.raise_for_status()
                print(f"[Pipeline] Webhook delivered. Status: {resp.status_code}")
            except Exception as e:
                print(f"[Pipeline] FAILED to deliver webhook: {e}")