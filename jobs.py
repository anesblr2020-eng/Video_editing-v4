"""Lightweight background jobs for the Streamlit audio workspace.

Jobs survive Streamlit reruns and browser-tab closure while the hosting Python
process remains alive. This is intentionally not presented as a durable external
queue: a host restart/sleep can interrupt in-flight work.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "temp" / "jobs"
INPUT_DIR = BASE_DIR / "inputs"
OUTPUT_DIR = BASE_DIR / "outputs"
for _folder in (JOBS_DIR, INPUT_DIR, OUTPUT_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

_LOCK = threading.RLock()
# One heavy task at a time to avoid exhausting the memory/CPU of small hosting plans.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio-background-job")
_TERMINAL = {"completed", "failed", "interrupted"}


def _job_file(job_id: str) -> Path:
    # UUID validation prevents path traversal through user-supplied IDs.
    safe_id = str(uuid.UUID(job_id))
    return JOBS_DIR / f"{safe_id}.json"


def _write(job: dict[str, Any]) -> None:
    path = _job_file(job["id"])
    tmp = path.with_suffix(".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def get_job(job_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(_job_file(job_id).read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError):
        return None


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for path in JOBS_DIR.glob("*.json"):
        try:
            jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    jobs.sort(key=lambda item: float(item.get("created_at", 0)), reverse=True)
    return jobs[:limit]


def recover_interrupted_jobs() -> None:
    """Mark jobs left queued/running by a prior process as interrupted on startup."""
    for job in list_jobs(limit=1000):
        if job.get("status") in {"queued", "running"}:
            job["status"] = "interrupted"
            job["message"] = "توقف خادم التطبيق قبل اكتمال المهمة. أعد تشغيلها من الواجهة."
            job["updated_at"] = time.time()
            _write(job)


def _update(job_id: str, **changes: Any) -> None:
    job = get_job(job_id)
    if not job:
        return
    job.update(changes)
    job["updated_at"] = time.time()
    _write(job)


def _run_job(job_id: str, job_type: str, source_path: str, original_name: str, options: dict[str, Any]) -> None:
    _update(job_id, status="running", progress=0.02, message="بدأت المعالجة في الخلفية.")
    try:
        source = Path(source_path)
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError("ملف المصدر غير موجود أو فارغ.")

        if job_type == "transcribe":
            from transcriber import transcribe_audio

            _update(job_id, progress=0.08, message="جارٍ تحميل/تهيئة محرك التفريغ…")
            words = transcribe_audio(
                audio_path=str(source),
                model_size="small",
                language="ar",
                dialect_mode="algerian_darija",
                vad_filter=True,
            ) or []
            text_parts = []
            for item in words:
                token = str(item.get("word", item.get("text", ""))).strip() if isinstance(item, dict) else str(item).strip()
                if token:
                    text_parts.append(token)
            transcript_text = " ".join(text_parts).strip()
            txt_path = OUTPUT_DIR / f"{job_id}_transcript.txt"
            json_path = OUTPUT_DIR / f"{job_id}_transcript_words.json"
            txt_path.write_text(transcript_text, encoding="utf-8")
            json_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
            _update(
                job_id, status="completed", progress=1.0,
                message=f"اكتمل التفريغ: {len(words)} وحدة نصية." if words else "اكتمل المحرك دون كلمات قابلة للعرض.",
                result_paths={"text": str(txt_path), "json": str(json_path)},
                word_count=len(words), transcript_text=transcript_text,
            )
            return

        if job_type == "cut_silence":
            from auto_cut import remove_silence

            video_exts = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp", ".ts", ".wmv", ".flv"}
            out_ext = ".mp4" if source.suffix.lower() in video_exts else ".mp3"
            output_path = OUTPUT_DIR / f"{job_id}_silence_cut{out_ext}"

            def report_progress(value: float, message: str) -> None:
                # Keep progress below 100 until the output file is validated.
                pct = max(0.03, min(0.96, float(value)))
                _update(job_id, progress=pct, message=str(message)[:300])

            result_path = Path(remove_silence(
                str(source), str(output_path),
                silence_threshold=-42.0,
                min_silence_len=250,
                padding_ms=65,
                progress_callback=report_progress,
            ))
            if not result_path.is_file() or result_path.stat().st_size == 0:
                raise RuntimeError("لم ينتج محرك القص ملفاً صالحاً.")
            _update(
                job_id, status="completed", progress=1.0,
                message="اكتمل قص الصمت وأُنشئت نسخة جديدة.",
                result_paths={"media": str(result_path)},
                result_size=result_path.stat().st_size,
            )
            return

        raise ValueError(f"نوع المهمة غير مدعوم: {job_type}")
    except Exception as exc:
        _update(
            job_id, status="failed", progress=1.0,
            message=f"تعذر إكمال المهمة: {type(exc).__name__}: {exc}",
            error_type=type(exc).__name__,
        )


def submit_job(job_type: str, source_path: str, original_name: str) -> str:
    if job_type not in {"transcribe", "cut_silence"}:
        raise ValueError("نوع المهمة غير مدعوم")
    job_id = str(uuid.uuid4())
    now = time.time()
    job = {
        "id": job_id,
        "type": job_type,
        "original_name": Path(original_name).name,
        "source_path": str(Path(source_path).resolve()),
        "status": "queued",
        "progress": 0.0,
        "message": "أُضيفت إلى قائمة الانتظار.",
        "created_at": now,
        "updated_at": now,
        "result_paths": {},
    }
    _write(job)
    _EXECUTOR.submit(_run_job, job_id, job_type, source_path, original_name, {})
    return job_id


# Detect leftovers from an earlier server process. This module is imported once
# per live Python process, not on each ordinary Streamlit rerun.
recover_interrupted_jobs()
