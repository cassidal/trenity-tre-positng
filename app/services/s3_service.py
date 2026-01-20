import boto3
import os
import mimetypes
from pathlib import Path


class S3Service:
    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url="https://storage.yandexcloud.net",
            aws_access_key_id=os.getenv("YANDEX_KEY_ID"),
            aws_secret_access_key=os.getenv("YANDEX_SECRET_KEY")
        )
        self.bucket_name = os.getenv("YANDEX_BUCKET_NAME")

    async def upload_file(self, file_path: str) -> str:
        print(f"Uploading {file_path} to {self.bucket_name}")
        filename = Path(file_path).name

        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = "video/mp4"

        extra_args = {
            'ContentType': content_type,
            'ContentDisposition': 'inline'
        }

        self.client.upload_file(
            file_path,
            self.bucket_name,
            filename,
            ExtraArgs=extra_args
        )

        print(self.bucket_name)
        print(filename)
        filepath = f"https://storage.yandexcloud.net/{self.bucket_name}/{filename}"
        print(filepath)
        return filepath