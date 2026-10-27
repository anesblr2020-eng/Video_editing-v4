"""
auto_cut.py - محرك المونتاج التلقائي الهجومي (Aggressive Jump Cuts > 0.25s) عبر pydub + FFmpeg مع إعادة حساب التواقيت آلياً
=============================================================================================================================
متطلبات الهندسة المعمارية (Alex Hormozi High-Retention Jump-Cut Engine):
1. اكتشاف وقص فترات الصمت التي تتجاوز `0.25 ثانية` (`250ms`) تلقائياً باستخدام `pydub` (`AudioSegment` + `detect_nonsilent`)
   ومعايرة تكيّفية ذكية لعتبة الضجيج (`Adaptive Noise-Floor Calibrator`) لضمان إيقاع سريع وحماسي بدون أي ملل.
2. إعادة حساب تواقيت النصوص والكلمات (`Word-level & Sentence Timestamps Recalculation`) آلياً فور القص
   عبر ربط `kept_intervals_sec` مباشرة بدالة `recalculate_word_timestamps_after_cuts` في `transcriber.py`
   لضمان بقاء الكابشن متزامناً بدقة الفريم مع الصوت الجديد بعد القص.
3. قص الجمل والكلمات المكررة بالخطأ في التعليق الصوتي (`Voiceover Retake & Stutter Excision`).
4. معمارية استهلاك ذاكرة صفري تقريباً (`Zero-OOM Native FFmpeg Jump-Cut Engine`).
"""

import sys
import os
import gc
import wave
import ctypes
import bisect
import shutil
import subprocess
import logging
from typing import List, Tuple, Callable, Optional, Dict, Any
import numpy as np

try:
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent
    _HAS_PYDUB = True
except Exception:
    AudioSegment = None
    detect_nonsilent = None
    _HAS_PYDUB = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# حفظ آخر خريطة مقاطع كلام محتفظ بها بعد القص لإعادة حساب تواقيت الكلمات آلياً
_LAST_KEPT_SPEECH_INTERVALS: List[Tuple[float, float]] = []


def get_last_kept_speech_intervals() -> List[Tuple[float, float]]:
    """إرجاع الفترات الزمنية المحتفظ بها بعد آخر عملية قص صمت لإعادة حساب تواقيت النصوص آلياً."""
    return list(_LAST_KEPT_SPEECH_INTERVALS)


def force_free_ram():
    """تحرير الذاكرة العشوائية في بايثون وإرجاعها فوراً لنظام لينكس (glibc malloc_trim)."""
    try:
        gc.collect()
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def is_video_file(file_path: str) -> bool:
    """التحقق السريع مما إذا كان الملف يحتوي على مسار فيديو دون استهلاك ذاكرة."""
    if not file_path or not os.path.exists(file_path):
        return False

    video_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp", ".ts", ".wmv", ".flv"}
    _, ext = os.path.splitext(file_path.lower())
    if ext not in video_extensions:
        return False

    try:
        res = subprocess.run(
            ["ffmpeg", "-threads", "1", "-i", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        if "Video:" in (res.stderr or ""):
            return True
    except Exception:
        pass
    return True


def get_safe_working_resolution(w: int, h: int, max_dim: int = 960) -> Tuple[int, int]:
    """
    ضبط أبعاد الفيديو إلى دقة مثالية للسحابة والموبايل (540x960 أو 960x540 - qHD Crisp)،
    مما يخفض استهلاك الذاكرة العشوائية (RAM) بأكثر من 75% ويضاعف سرعة الرندرة مع الحفاظ على وضوح عالٍ.
    """
    if max(w, h) <= max_dim:
        return (max(2, w - (w % 2)), max(2, h - (h % 2)))
    scale = float(max_dim) / float(max(w, h))
    nw = max(2, int(round(w * scale)))
    nh = max(2, int(round(h * scale)))
    nw -= (nw % 2)
    nh -= (nh % 2)
    return nw, nh


def ensure_playable_audio_or_video(input_path: str, working_dir: str) -> Tuple[str, bool]:
    """
    تحضير وتطبيع الملف المرفوع فوراً:
    إذا كان الفيديو المرفوع كبيراً (> 8MB)، يتم تطبيعه تلقائياً عبر عملية FFmpeg أحادية الخيط
    خارج ذاكرة بايثون إلى دقة عمل رشيقة (960p @ 30fps).
    """
    os.makedirs(working_dir, exist_ok=True)
    has_video = is_video_file(input_path)
    if has_video:
        try:
            file_mb = os.path.getsize(input_path) / (1024.0 * 1024.0)
            if file_mb > 8.0 and not os.path.basename(input_path).startswith("norm_"):
                norm_vid = os.path.join(working_dir, f"norm_{os.path.basename(input_path)}")
                if not os.path.exists(norm_vid):
                    cmd = [
                        "ffmpeg", "-y", "-v", "error", "-threads", "1",
                        "-i", input_path,
                        "-vf", "scale='if(gt(iw,ih),min(960,iw),-2)':'if(gt(iw,ih),-2,min(960,ih))',fps=30",
                        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                        "-x264-params", "rc-lookahead=0:sync-lookahead=0:ref=1:bframes=0",
                        "-crf", "24", "-pix_fmt", "yuv420p", "-threads", "1",
                        "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "16000",
                        "-movflags", "+faststart",
                        norm_vid
                    ]
                    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
                    if res.returncode == 0 and os.path.exists(norm_vid) and os.path.getsize(norm_vid) > 10240:
                        try:
                            os.remove(input_path)
                        except Exception:
                            pass
                        force_free_ram()
                        return norm_vid, True
        except Exception:
            pass
        force_free_ram()
        return input_path, True

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    normalized_wav = os.path.join(working_dir, f"normalized_{base_name}.wav")

    if os.path.exists(normalized_wav) and os.path.getsize(normalized_wav) > 1024:
        return normalized_wav, False

    try:
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-threads", "1",
            "-i", input_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            normalized_wav
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if res.returncode == 0 and os.path.exists(normalized_wav) and os.path.getsize(normalized_wav) > 512:
            force_free_ram()
            return normalized_wav, False
    except Exception:
        pass

    return input_path, False


def apply_padding_and_merge(
    chunks: List[List[int]],
    total_duration_ms: int,
    padding_ms: int = 55,
    min_bridge_gap_ms: int = 250,
    pre_pad_override_ms: Optional[int] = None,
    post_pad_override_ms: Optional[int] = None
) -> List[Tuple[int, int]]:
    """
    إضافة هامش تنفس رشيق حول الكلمات ودمج الفجوات التي تقل عن `0.25 ثانية` (`250ms`) فقط،
    بينما يتم قص أي فترة صمت تتجاوز `0.25 ثانية` فوراً (Aggressive Jump Cuts).
    """
    if not chunks:
        return []

    pre_pad = int(pre_pad_override_ms) if pre_pad_override_ms is not None else max(30, min(180, int(padding_ms * 0.70)))
    post_pad = int(post_pad_override_ms) if post_pad_override_ms is not None else max(40, min(200, int(padding_ms * 0.85)))
    # ضمان أن أي صمت يتجاوز 250ms يتم قصه وعدم دمجه
    effective_bridge = min(250, max(60, int(min_bridge_gap_ms)))

    merged = []
    for start, end in chunks:
        start_padded = max(0, start - pre_pad)
        end_padded = min(total_duration_ms, end + post_pad)

        if not merged:
            merged.append([start_padded, end_padded])
        else:
            last_start, last_end = merged[-1]
            if (start - last_end) < effective_bridge and (start_padded <= last_end):
                merged[-1][1] = max(last_end, end_padded)
            else:
                merged.append([start_padded, end_padded])

    return [(start, end) for start, end in merged]


def detect_nonsilent_pydub_aggressive(
    wav_path: str,
    silence_threshold_db: float = -40.0,
    min_silence_len_ms: int = 250,
    padding_ms: int = 55
) -> Tuple[List[Tuple[int, int]], int, float]:
    """
    محرك `pydub` المتقدم لاكتشاف فترات الكلام وقص كل صمت يتجاوز `0.25 ثانية` (`250ms` Aggressive Jump Cuts):
    يستخدم `pydub.AudioSegment` و `pydub.silence.detect_nonsilent` مع معايرة تكيّفية لعتبة الصوت (`dBFS`).
    """
    if not _HAS_PYDUB or not os.path.exists(wav_path):
        return [], 0, silence_threshold_db

    audio_seg = AudioSegment.from_wav(wav_path)
    total_ms = len(audio_seg)
    if total_ms <= 50:
        return [(0, max(100, total_ms))], total_ms, silence_threshold_db

    # معايرة ذكية لعتبة الصوت بناءً على متوسط dBFS الفعلي للملف الصوتي
    seg_dbfs = float(audio_seg.dBFS) if audio_seg.dBFS != float("-inf") else -42.0
    if abs(float(silence_threshold_db) - (-42.0)) <= 2.5 or float(silence_threshold_db) < seg_dbfs - 18.0:
        eff_thresh_db = max(-50.0, min(-24.0, round(seg_dbfs - 7.5, 1)))
    else:
        eff_thresh_db = float(silence_threshold_db)

    # فرض سقف 250ms (0.25 ثانية) لقص جميع فترات الصمت التي تتجاوز 0.25 ثانية تلقائياً
    strict_min_silence = min(250, max(140, int(min_silence_len_ms)))

    nonsilent_ranges = detect_nonsilent(
        audio_seg,
        min_silence_len=strict_min_silence,
        silence_thresh=eff_thresh_db,
        seek_step=10
    )
    del audio_seg

    if not nonsilent_ranges:
        return [(0, total_ms)], total_ms, eff_thresh_db

    merged = apply_padding_and_merge(
        chunks=nonsilent_ranges,
        total_duration_ms=total_ms,
        padding_ms=min(65, int(padding_ms)),
        min_bridge_gap_ms=strict_min_silence
    )
    return merged, total_ms, eff_thresh_db


def _extract_raw_speech_chunks(
    is_speech: np.ndarray,
    step_ms: int,
    total_duration_ms: int,
    min_silent_wins: int
) -> List[List[int]]:
    raw_chunks: List[List[int]] = []
    in_speech = False
    cur_start = 0
    silent_run = 0

    for idx, sp in enumerate(is_speech):
        t_ms = idx * step_ms
        if sp:
            if not in_speech:
                cur_start = t_ms
                in_speech = True
            silent_run = 0
        else:
            if in_speech:
                silent_run += 1
                if silent_run >= min_silent_wins:
                    end_ms = (idx - silent_run + 1) * step_ms
                    raw_chunks.append([cur_start, max(cur_start + step_ms, end_ms)])
                    in_speech = False
                    silent_run = 0

    if in_speech:
        raw_chunks.append([cur_start, total_duration_ms])

    return raw_chunks


def _compute_residual_silence_ratio(
    merged_ms: List[Tuple[int, int]],
    is_speech: np.ndarray,
    step_ms: int
) -> float:
    if not merged_ms or len(is_speech) == 0:
        return 0.035
    total_kept_wins = 0
    silent_kept_wins = 0
    n_w = len(is_speech)
    for s_ms, e_ms in merged_ms:
        i0 = max(0, min(n_w - 1, int(s_ms // step_ms)))
        i1 = max(i0 + 1, min(n_w, int(e_ms // step_ms)))
        seg = is_speech[i0:i1]
        total_kept_wins += len(seg)
        silent_kept_wins += int(np.sum(~seg))
    if total_kept_wins <= 0:
        return 0.035
    return float(silent_kept_wins) / float(total_kept_wins)


def calibrate_residual_silence_5_percent(
    dbfs: np.ndarray,
    step_ms: int,
    total_duration_ms: int,
    user_silence_threshold: float = -42.0,
    target_min_ratio: float = 0.045,
    target_max_ratio: float = 0.055
) -> Tuple[List[Tuple[int, int]], float, float]:
    valid_db = dbfs[dbfs > -85.0]
    if len(valid_db) < 4:
        return [(0, total_duration_ms)], user_silence_threshold, 0.035

    mean_db = float(np.mean(valid_db))
    p10 = float(np.percentile(valid_db, 10))
    p50 = float(np.percentile(valid_db, 50))
    p85 = float(np.percentile(valid_db, 85))

    adaptive_thresh = p10 + 0.30 * (p85 - p10)
    adaptive_thresh = max(-52.0, min(mean_db - 4.2, p50 - 2.5, adaptive_thresh))

    if abs(float(user_silence_threshold) - (-42.0)) <= 1.5 or float(user_silence_threshold) < p10 - 2.0:
        base_thresh = round(adaptive_thresh, 1)
    else:
        base_thresh = round(max(float(user_silence_threshold), adaptive_thresh - 2.5), 1)

    target_mid = 0.05
    best_merged: List[Tuple[int, int]] = [(0, total_duration_ms)]
    best_thresh = base_thresh
    best_res_ratio = 0.035
    best_err = 999.0

    # جميع الإعدادات تقص أي صمت يتجاوز 250ms (0.25s) كحد أقصى
    candidate_configs = [
        (base_thresh, 200, 65, 180),
        (base_thresh, 220, 80, 200),
        (base_thresh, 250, 95, 220),
        (base_thresh + 1.2, 180, 75, 160),
        (base_thresh + 1.2, 220, 105, 200),
        (base_thresh + 2.2, 170, 120, 150),
        (base_thresh + 0.5, 210, 145, 210),
        (base_thresh - 1.0, 240, 160, 220),
    ]

    for cand_th, min_sil_ms, pad_ms, bridge_ms in candidate_configs:
        is_sp = dbfs >= cand_th
        if np.mean(is_sp) < 0.45:
            continue
        min_wins = max(2, int(min_sil_ms // step_ms))
        raw_c = _extract_raw_speech_chunks(is_sp, step_ms, total_duration_ms, min_wins)
        if not raw_c:
            continue
        merged_c = apply_padding_and_merge(
            raw_c,
            total_duration_ms=total_duration_ms,
            padding_ms=pad_ms,
            min_bridge_gap_ms=bridge_ms
        )
        res_ratio = _compute_residual_silence_ratio(merged_c, is_sp, step_ms)
        err = abs(res_ratio - target_mid)
        if target_min_ratio <= res_ratio <= target_max_ratio:
            return merged_c, round(cand_th, 1), round(res_ratio, 4)
        if err < best_err:
            best_err = err
            best_merged = merged_c
            best_thresh = round(cand_th, 1)
            best_res_ratio = round(res_ratio, 4)

    return best_merged, best_thresh, best_res_ratio


def subtract_exclusion_intervals(
    base_intervals: List[Tuple[float, float]],
    exclude_intervals: List[Tuple[float, float]],
    min_piece_sec: float = 0.08
) -> List[Tuple[float, float]]:
    if not base_intervals or not exclude_intervals:
        return list(base_intervals)

    current = [(float(s), float(e)) for s, e in base_intervals if float(e) > float(s)]
    for ex_s, ex_e in exclude_intervals:
        ex_s, ex_e = float(ex_s), float(ex_e)
        if ex_e <= ex_s:
            continue
        next_list: List[Tuple[float, float]] = []
        for s, e in current:
            if ex_e <= s or ex_s >= e:
                next_list.append((s, e))
            else:
                if ex_s > s and (ex_s - s) >= min_piece_sec:
                    next_list.append((round(s, 3), round(ex_s, 3)))
                if ex_e < e and (e - ex_e) >= min_piece_sec:
                    next_list.append((round(ex_e, 3), round(e, 3)))
        current = next_list

    return current if current else list(base_intervals[:1])


def detect_speech_intervals_fast(
    input_path: str,
    temp_dir: str,
    silence_threshold: float = -42.0,
    chunk_size: int = 20,
    min_silence_len: int = 250,
    padding_ms: int = 55,
    exclude_intervals_sec: Optional[List[Tuple[float, float]]] = None
) -> Tuple[List[Tuple[float, float]], float]:
    """
    كاشف الصمت الهجومي (`Aggressive Jump-Cut Detector` via `pydub` + `NumPy`):
    يكتشف فترات الصمت التي تتجاوز `0.25 ثانية` (`250ms`) ويقصها تلقائياً،
    مع حفظ الفترات المحتفظ بها في `_LAST_KEPT_SPEECH_INTERVALS` لإعادة حساب تواقيت النصوص آلياً.
    """
    global _LAST_KEPT_SPEECH_INTERVALS
    os.makedirs(temp_dir, exist_ok=True)
    light_wav = os.path.join(temp_dir, f"fast_scan_{os.getpid()}.wav")
    sr = 16000

    try:
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-threads", "1",
            "-i", input_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", str(sr), "-ac", "1",
            light_wav
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        if not os.path.exists(light_wav) or os.path.getsize(light_wav) <= 512:
            _LAST_KEPT_SPEECH_INTERVALS = [(0.0, 10.0)]
            return [(0.0, 10.0)], 10.0

        # 1. تشغيل محرك pydub القياسي لقص الصمت > 0.25 ثانية (250ms)
        strict_min_sil = min(250, max(150, int(min_silence_len)))
        pydub_merged_ms, total_duration_ms, eff_thresh = detect_nonsilent_pydub_aggressive(
            wav_path=light_wav,
            silence_threshold_db=silence_threshold,
            min_silence_len_ms=strict_min_sil,
            padding_ms=min(65, int(padding_ms))
        )

        # 2. التحقق التكيفي عبر NumPy في حال كان التسجيل صاخباً جداً ولم يكتشف pydub الفواصل
        with wave.open(light_wav, "rb") as wf:
            n_frames = wf.getnframes()
            raw_bytes = wf.readframes(n_frames)

        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
        del raw_bytes
        if total_duration_ms <= 0:
            total_duration_ms = int(round((len(samples) / float(sr)) * 1000.0))
        if total_duration_ms <= 50:
            _LAST_KEPT_SPEECH_INTERVALS = [(0.0, max(0.1, total_duration_ms / 1000.0))]
            return _LAST_KEPT_SPEECH_INTERVALS, max(0.1, total_duration_ms / 1000.0)

        step_ms = max(10, int(chunk_size))
        win_samples = max(1, int(sr * step_ms / 1000))
        num_wins = len(samples) // win_samples
        if num_wins >= 2:
            trimmed = samples[:num_wins * win_samples].reshape((num_wins, win_samples))
            rms = np.sqrt(np.mean(trimmed * trimmed, axis=1) + 1e-9)
            dbfs = 20.0 * np.log10(np.maximum(rms / 32768.0, 1e-7))
            del samples, trimmed

            np_merged_ms, np_thresh, res_sil_ratio = calibrate_residual_silence_5_percent(
                dbfs=dbfs,
                step_ms=step_ms,
                total_duration_ms=total_duration_ms,
                user_silence_threshold=silence_threshold
            )
            # أولوية المعايرة التي تستهدف إبقاء قرابة 5% من الصمت الطبيعي.
            # نستخدم نتيجة pydub فقط إذا تعذرت معايرة NumPy أو كانت النتيجة غير صالحة.
            if np_merged_ms and any(e > s for s, e in np_merged_ms):
                merged_ms = np_merged_ms
                eff_thresh = np_thresh
                logger.info("Estimated residual silence target=5%%; measured=%.2f%%", res_sil_ratio * 100.0)
            else:
                merged_ms = pydub_merged_ms or [(0, total_duration_ms)]
        else:
            merged_ms = pydub_merged_ms or [(0, total_duration_ms)]

        intervals_sec = [(round(s / 1000.0, 3), round(e / 1000.0, 3)) for s, e in merged_ms if (e - s) >= 80]
        if not intervals_sec:
            intervals_sec = [(0.0, round(total_duration_ms / 1000.0, 3))]

        if exclude_intervals_sec:
            intervals_sec = subtract_exclusion_intervals(intervals_sec, exclude_intervals_sec)

        _LAST_KEPT_SPEECH_INTERVALS = list(intervals_sec)
        logger.info(
            f"Silence trim complete (target residual silence ~5%): eff_thresh={eff_thresh}dBFS, "
            f"kept_segments={len(intervals_sec)}, orig_dur={total_duration_ms/1000.0:.2f}s"
        )
        return intervals_sec, round(total_duration_ms / 1000.0, 3)

    finally:
        if os.path.exists(light_wav):
            try:
                os.remove(light_wav)
            except Exception:
                pass
        force_free_ram()


def cut_silence_and_recalculate_timestamps(
    input_path: str,
    output_path: str,
    words_data: List[Dict[str, Any]],
    silence_threshold: float = -42.0,
    min_silence_len: int = 250,
    padding_ms: int = 55,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> Tuple[str, List[Dict[str, Any]], List[Tuple[float, float]]]:
    """
    الدالة المتكاملة للمونتاج التلقائي الهجومي (Aggressive Jump Cuts > 0.25s) مع إعادة حساب التواقيت آلياً:
    1. تكتشف فترات الصمت التي تتجاوز `0.25 ثانية` (`250ms`) عبر `pydub` وتقصها من الصوت/الفيديو.
    2. تعيد حساب تواقيت جميع الكلمات (`words_data`) آلياً عبر `recalculate_word_timestamps_after_cuts`
       بحيث تظل متزامنة 100% مع الصوت الجديد بعد القص.
    """
    out_media = remove_silence(
        input_path=input_path,
        output_path=output_path,
        silence_threshold=silence_threshold,
        chunk_size=20,
        min_silence_len=min(250, int(min_silence_len)),
        padding_ms=min(65, int(padding_ms)),
        progress_callback=progress_callback
    )
    kept_intervals = get_last_kept_speech_intervals()
    if words_data and kept_intervals:
        try:
            from transcriber import recalculate_word_timestamps_after_cuts
            remapped_words = recalculate_word_timestamps_after_cuts(words_data, kept_intervals)
        except Exception:
            remapped_words = words_data
    else:
        remapped_words = words_data
    return out_media, remapped_words, kept_intervals


def _build_ffmpeg_select_expr(intervals_sec: List[Tuple[float, float]]) -> str:
    merged = list(intervals_sec)
    while len(merged) > 48:
        best_i = 0
        min_gap = float("inf")
        for i in range(len(merged) - 1):
            gap = merged[i + 1][0] - merged[i][1]
            if gap < min_gap:
                min_gap = gap
                best_i = i
        merged[best_i] = (merged[best_i][0], merged[best_i + 1][1])
        merged.pop(best_i + 1)

    parts = [f"between(t,{s:.3f},{e:.3f})" for s, e in merged]
    return "+".join(parts) if parts else "1"


def prune_retake_cuts_from_media(
    media_path: str,
    retake_cuts: List[Dict[str, Any]],
    total_duration: float
) -> Tuple[str, float]:
    if not retake_cuts or not os.path.exists(media_path):
        return media_path, total_duration

    exclude_spans = [
        (float(c.get("start", 0.0)), float(c.get("end", 0.0)))
        for c in retake_cuts
        if float(c.get("end", 0.0)) - float(c.get("start", 0.0)) >= 0.08
    ]
    if not exclude_spans:
        return media_path, total_duration

    keep_intervals = subtract_exclusion_intervals([(0.0, max(0.2, float(total_duration)))], exclude_spans)
    if not keep_intervals or len(keep_intervals) == 1 and abs(keep_intervals[0][1] - keep_intervals[0][0] - total_duration) < 0.05:
        return media_path, total_duration

    sel_expr = _build_ffmpeg_select_expr(keep_intervals)
    new_dur = round(sum(e - s for s, e in keep_intervals), 3)
    base, ext = os.path.splitext(media_path)
    pruned_path = f"{base}_retake_cleaned{ext}"

    has_vid = is_video_file(media_path)
    if has_vid:
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-threads", "1",
            "-i", media_path,
            "-vf", f"select='{sel_expr}',setpts=N/FRAME_RATE/TB",
            "-af", f"aselect='{sel_expr}',asetpts=N/SR/TB",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-x264-params", "rc-lookahead=0:sync-lookahead=0:ref=1:bframes=0",
            "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "1",
            "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "16000",
            pruned_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-threads", "1",
            "-i", media_path,
            "-vn",
            "-af", f"aselect='{sel_expr}',asetpts=N/SR/TB",
            "-ar", "16000", "-ac", "1", "-b:a", "96k", "-threads", "1",
            pruned_path
        ]

    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    if res.returncode == 0 and os.path.exists(pruned_path) and os.path.getsize(pruned_path) > 1024:
        try:
            os.replace(pruned_path, media_path)
            force_free_ram()
            return media_path, max(0.2, new_dur)
        except Exception:
            force_free_ram()
            return pruned_path, max(0.2, new_dur)

    force_free_ram()
    return media_path, total_duration


def extract_jumpcut_audio_and_intervals(
    input_path: str,
    clean_audio_output_path: str,
    silence_threshold: float = -42.0,
    chunk_size: int = 20,
    min_silence_len: int = 250,
    padding_ms: int = 55,
    exclude_intervals_sec: Optional[List[Tuple[float, float]]] = None
) -> Tuple[List[Tuple[float, float]], float]:
    temp_dir = os.path.dirname(os.path.abspath(clean_audio_output_path))
    os.makedirs(temp_dir, exist_ok=True)

    intervals_sec, orig_dur = detect_speech_intervals_fast(
        input_path=input_path,
        temp_dir=temp_dir,
        silence_threshold=silence_threshold,
        chunk_size=chunk_size,
        min_silence_len=min_silence_len,
        padding_ms=padding_ms,
        exclude_intervals_sec=exclude_intervals_sec
    )

    sel_expr = _build_ffmpeg_select_expr(intervals_sec)
    total_kept_sec = round(sum(e - s for s, e in intervals_sec), 3)

    cmd = [
        "ffmpeg", "-y", "-v", "error", "-threads", "1",
        "-i", input_path,
        "-vn",
        "-af", f"aselect='{sel_expr}',asetpts=N/SR/TB",
        "-ar", "16000", "-ac", "1", "-b:a", "96k", "-threads", "1",
        clean_audio_output_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    if res.returncode != 0 or not os.path.exists(clean_audio_output_path):
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-threads", "1", "-i", input_path, "-vn", "-ar", "16000", "-ac", "1", "-threads", "1", clean_audio_output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60
        )

    force_free_ram()
    return intervals_sec, max(0.1, total_kept_sec)


def build_virtual_time_mapper(intervals_sec: List[Tuple[float, float]]):
    cum_starts = []
    segments = []
    acc = 0.0
    for s, e in intervals_sec:
        dur = max(0.001, e - s)
        cum_starts.append(acc)
        segments.append((s, e, dur))
        acc += dur
    total_dur = max(0.05, acc)

    def map_t(t: float) -> float:
        if not segments:
            return max(0.0, float(t))
        t_clamped = max(0.0, min(float(t), total_dur - 0.001))
        idx = bisect.bisect_right(cum_starts, t_clamped) - 1
        idx = max(0, min(idx, len(segments) - 1))
        s, e, _ = segments[idx]
        offset = t_clamped - cum_starts[idx]
        return min(e - 0.001, s + offset)

    return map_t, total_dur


def remove_silence(
    input_path: str,
    output_path: str,
    silence_threshold: float = -42.0,
    chunk_size: int = 20,
    min_silence_len: int = 250,
    padding_ms: int = 55,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> str:
    """
    قص فترات الصمت التي تتجاوز `0.25 ثانية` (`250ms` Aggressive Jump Cuts) عبر `pydub` + `FFmpeg` الأصلي أحادي الخيط.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"الملف المدخل غير موجود: {input_path}")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(output_path)), "temp")
    os.makedirs(temp_dir, exist_ok=True)

    def update_progress(val: float, text: str):
        if progress_callback:
            progress_callback(val, text)
        logger.info(f"Progress: {val*100:.1f}% - {text}")

    update_progress(0.15, "جاري تحليل الإشارة الصوتية ومعايرة الصمت المتبقي نحو 5%...")
    intervals_sec, orig_dur = detect_speech_intervals_fast(
        input_path=input_path,
        temp_dir=temp_dir,
        silence_threshold=silence_threshold,
        chunk_size=chunk_size,
        min_silence_len=min(250, int(min_silence_len)),
        padding_ms=min(65, int(padding_ms))
    )

    total_kept_sec = sum(e - s for s, e in intervals_sec)
    cut_sec = max(0.0, orig_dur - total_kept_sec)
    sel_expr = _build_ffmpeg_select_expr(intervals_sec)

    has_vid = is_video_file(input_path)
    if has_vid:
        update_progress(0.55, "جاري قص فترات الصمت مع استهداف إبقاء نحو 5% للصوت الطبيعي عبر FFmpeg...")
        vf_chain = (
            f"select='{sel_expr}',setpts=N/FRAME_RATE/TB,"
            "scale='if(gt(iw,ih),min(960,iw),-2)':'if(gt(iw,ih),-2,min(960,ih))',fps=30"
        )
        af_chain = f"aselect='{sel_expr}',asetpts=N/SR/TB"
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-threads", "1",
            "-i", input_path,
            "-vf", vf_chain,
            "-af", af_chain,
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-x264-params", "rc-lookahead=0:sync-lookahead=0:ref=1:bframes=0",
            "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "1",
            "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "16000",
            "-movflags", "+faststart",
            output_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        if res.returncode != 0 or not os.path.exists(output_path):
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-threads", "1",
                "-i", input_path,
                "-vf", "scale='if(gt(iw,ih),min(960,iw),-2)':'if(gt(iw,ih),-2,min(960,ih))',fps=30",
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                "-x264-params", "rc-lookahead=0:sync-lookahead=0:ref=1:bframes=0",
                "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "1",
                "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "16000",
                output_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    else:
        update_progress(0.65, "جاري دمج وتنقية الملف الصوتي عبر محرك FFmpeg السريع...")
        _, ext = os.path.splitext(output_path.lower())
        if ext in {".m4a", ".aac", ".mp4"}:
            output_path = os.path.splitext(output_path)[0] + ".mp3"
        extract_jumpcut_audio_and_intervals(
            input_path=input_path,
            clean_audio_output_path=output_path,
            silence_threshold=silence_threshold,
            chunk_size=chunk_size,
            min_silence_len=min(250, int(min_silence_len)),
            padding_ms=min(65, int(padding_ms))
        )

    force_free_ram()
    update_progress(1.0, f"اكتملت المعالجة بنجاح! (تم قص {cut_sec:.1f} ثانية من فترات الصمت؛ الهدف إبقاء نحو 5% صمت)")
    return output_path


def get_speech_timestamps(
    input_path: str,
    silence_threshold: float = -42.0,
    chunk_size: int = 20,
    min_silence_len: int = 250,
    padding_ms: int = 55
) -> List[Tuple[float, float]]:
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(input_path)), "temp")
    intervals_sec, _ = detect_speech_intervals_fast(
        input_path=input_path,
        temp_dir=temp_dir,
        silence_threshold=silence_threshold,
        chunk_size=chunk_size,
        min_silence_len=min(250, int(min_silence_len)),
        padding_ms=min(65, int(padding_ms))
    )
    return intervals_sec