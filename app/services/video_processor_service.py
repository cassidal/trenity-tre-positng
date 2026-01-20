import logging
import uuid
from pathlib import Path

import ffmpeg
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


class VideoProcessorService:
    def __init__(self):
        self.temp_dir = Path("temp")
        self.temp_dir.mkdir(exist_ok=True)
        self.MAX_TOTAL_DURATION = 60.0

        # --- НАСТРОЙКИ GPU (NVIDIA) ---
        # Если видеокарты нет, замени 'h264_nvenc' обратно на 'libx264'
        self.codec_opts = {
            'c:v': 'h264_nvenc',  # <--- ГЛАВНОЕ ИЗМЕНЕНИЕ: аппаратный кодек NVIDIA
            'preset': 'p4',  # p1 (самый быстрый) .. p7 (самый качественный). p4 - баланс.
            'rc': 'vbr',  # Variable bitrate
            'cq': 28,  # Качество (аналог crf, чем меньше, тем лучше, 28 норм для соцсетей)
            'b:v': '5M',  # Битрейт (5-8 Мбит/с норм для рилс)
            'maxrate': '8M',
            'bufsize': '10M',
            'c:a': 'aac',
            'ar': 44100,
            'pix_fmt': 'yuv420p'
        }

    async def process_video(self, reel_url: str, insert_clip_path: str, insert_position: int = 50) -> str:
        task_id = str(uuid.uuid4())[:8]
        logger.info(f"[{task_id}] 🎬 Start processing (GPU): {reel_url} | Position: {insert_position}%")

        insert_path = Path(insert_clip_path)
        if not insert_path.exists():
            raise ValueError(f"Insert clip not found: {insert_clip_path}")

        # 1. АНАЛИЗ ВСТАВКИ
        try:
            insert_probe = ffmpeg.probe(str(insert_path))
            insert_duration = float(insert_probe["format"]["duration"])
            insert_has_audio = any(s['codec_type'] == 'audio' for s in insert_probe['streams'])
        except Exception as e:
            raise ValueError(f"Failed to probe insert video: {e}")

        # 2. СКАЧИВАНИЕ
        original_path = self.temp_dir / f"original_{task_id}.mp4"
        await self._download_file(reel_url, original_path)
        cleanup_files = [original_path]

        try:
            # 3. АНАЛИЗ ОРИГИНАЛА
            try:
                orig_probe = ffmpeg.probe(str(original_path))
                video_stream = next((s for s in orig_probe["streams"] if s["codec_type"] == "video"), None)
                orig_width = int(video_stream["width"])
                orig_height = int(video_stream["height"])
                orig_duration = float(video_stream.get("duration", orig_probe["format"]["duration"]))
                orig_has_audio = any(s['codec_type'] == 'audio' for s in orig_probe['streams'])
            except Exception as e:
                logger.error(f"FFprobe failed: {e}")
                raise ValueError("Invalid original video file")

            # 4. РАСЧЕТЫ
            allowed_orig_duration = self.MAX_TOTAL_DURATION - insert_duration
            if allowed_orig_duration <= 5:
                raise ValueError("Insert is too long!")

            final_orig_duration = min(orig_duration, allowed_orig_duration)
            split_point = final_orig_duration * (insert_position / 100.0)

            # Пути
            part1_path = self.temp_dir / f"part1_{task_id}.mp4"
            part2_path = self.temp_dir / f"part2_{task_id}.mp4"
            insert_norm_path = self.temp_dir / f"insert_norm_{task_id}.mp4"
            output_path = self.temp_dir / f"processed_{task_id}.mp4"
            cleanup_files.extend([part1_path, part2_path, insert_norm_path])

            files_to_concat = []

            # А. НОРМАЛИЗАЦИЯ ВСТАВКИ
            self._normalize_segment(
                input_path=insert_path, output_path=insert_norm_path,
                width=orig_width, height=orig_height, opts=self.codec_opts,
                has_audio=insert_has_audio, force_audio=True, duration=None
            )

            # Б. ГЕНЕРАЦИЯ ЧАСТЕЙ
            if split_point > 0.1:
                self._normalize_segment(
                    input_path=original_path, output_path=part1_path,
                    width=orig_width, height=orig_height, opts=self.codec_opts,
                    start=0, duration=split_point,
                    has_audio=orig_has_audio, force_audio=True
                )
                files_to_concat.append(part1_path)

            files_to_concat.append(insert_norm_path)

            remaining_duration = final_orig_duration - split_point
            if remaining_duration > 0.1:
                self._normalize_segment(
                    input_path=original_path, output_path=part2_path,
                    width=orig_width, height=orig_height, opts=self.codec_opts,
                    start=split_point, duration=remaining_duration,
                    has_audio=orig_has_audio, force_audio=True
                )
                files_to_concat.append(part2_path)

            # Г. СКЛЕЙКА
            streams = []
            for fpath in files_to_concat:
                inp = ffmpeg.input(str(fpath))
                streams.append(inp['v'])
                streams.append(inp['a'])

            (
                ffmpeg
                .concat(*streams, v=1, a=1)
                .output(str(output_path), **self.codec_opts)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )

            logger.info(f"🎉 Success (GPU): {output_path} ({output_path.stat().st_size} bytes)")
            return str(output_path)

        except ffmpeg.Error as e:
            error_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else str(e)
            logger.error(f"❌ FFMPEG Error: {error_msg}")
            raise ValueError(f"FFmpeg failed: {error_msg}")
        except Exception as e:
            raise e
        finally:
            self._cleanup(cleanup_files)

    def _normalize_segment(self, input_path, output_path, width, height, opts, start=0, duration=None, has_audio=True,
                           force_audio=True):
        inp = ffmpeg.input(str(input_path))

        # Scale и Pad остаются на CPU (это быстро), кодирование уходит на GPU
        vid = (
            inp['v']
            .filter("scale", width, height, force_original_aspect_ratio="decrease")
            .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2", color="black")
            .filter("setsar", "1")
        )

        if has_audio:
            aud = inp['a']
        elif force_audio:
            aud = ffmpeg.input("anullsrc=channel_layout=stereo:sample_rate=44100", f="lavfi")['a']
        else:
            aud = None

        args = opts.copy()
        if start > 0: args['ss'] = start
        if duration: args['t'] = duration
        if force_audio and not has_audio: args['shortest'] = None

        out = ffmpeg.output(vid, aud, str(output_path), **args)
        out.overwrite_output().run(capture_stdout=True, capture_stderr=True)

    async def _download_file(self, url: str, path: Path):
        logger.info(f"⬇️ Downloading: {url}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
        if not path.exists() or path.stat().st_size < 1000:
            raise ValueError("Download failed")

    def _cleanup(self, paths: list[Path]):
        for p in paths:
            try:
                if p.exists(): p.unlink()
            except Exception:
                pass