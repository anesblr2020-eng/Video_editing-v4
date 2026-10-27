from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "inputs"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"
for folder in (INPUT_DIR, OUTPUT_DIR, TEMP_DIR):
    folder.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="مختبر الصوت | بناء جديد",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap');
:root { --bg:#0b0d12; --panel:#121620; --panel2:#171c28; --line:#282f3e; --ink:#f3f5fa; --muted:#a2aabd; --lime:#d4ff70; --violet:#9b8cff; }
html, body, [class*="css"] { font-family:'IBM Plex Sans Arabic',sans-serif; }
.stApp { background: radial-gradient(ellipse at 85% 0%, #20233b 0%, var(--bg) 38%); color:var(--ink); }
.block-container { max-width:1180px; padding-top:2rem; padding-bottom:4rem; }
#MainMenu, footer { visibility:hidden; }
header[data-testid="stHeader"] { background:transparent; }
.hero { border:1px solid var(--line); background:linear-gradient(120deg,rgba(155,140,255,.13),rgba(212,255,112,.045)),#10141d; border-radius:26px; padding:30px 32px; margin-bottom:22px; position:relative; overflow:hidden; }
.hero:after { content:'◉'; position:absolute; left:28px; top:-44px; font-size:180px; color:rgba(212,255,112,.055); }
.eyebrow { color:var(--lime); font-size:12px; letter-spacing:1.5px; font-weight:700; }
.hero h1 { font-size:clamp(30px,4vw,48px); line-height:1.3; margin:12px 0 10px; color:var(--ink); font-weight:700; }
.hero p { color:var(--muted); max-width:700px; font-size:16px; line-height:1.9; margin:0; }
.step { display:flex; gap:13px; align-items:center; padding:15px 17px; border:1px solid var(--line); background:rgba(18,22,32,.8); border-radius:17px; margin-bottom:12px; }
.stepnum { display:grid; place-items:center; min-width:38px; height:38px; border-radius:12px; background:rgba(212,255,112,.11); color:var(--lime); font-weight:700; }
.step strong { display:block; font-size:16px; }
.step small { display:block; color:var(--muted); margin-top:3px; line-height:1.6; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:22px; padding:22px; margin:12px 0 18px; }
.panel-title { font-size:20px; font-weight:700; margin-bottom:5px; }
.panel-sub { color:var(--muted); font-size:14px; line-height:1.8; margin-bottom:18px; }
div[data-testid="stFileUploader"] { border:1px dashed #4b5267; border-radius:16px; padding:8px; background:rgba(255,255,255,.015); }
.stButton > button, .stDownloadButton > button { border-radius:12px; min-height:45px; font-weight:700; border:1px solid #3a4254; }
.stButton > button[kind="primary"] { background:var(--lime); color:#11150c; border:0; }
.stButton > button[kind="primary"]:hover { background:#e2ff9e; color:#11150c; }
div[data-testid="stTabs"] button { font-weight:600; }
div[data-testid="stAlert"] { border-radius:14px; }
.metric-card { border:1px solid var(--line); background:var(--panel2); border-radius:15px; padding:14px 16px; }
.metric-card span { color:var(--muted); font-size:12px; }
.metric-card b { display:block; color:var(--lime); font-size:23px; margin-top:5px; }
div[data-testid="stProgress"] > div > div { background:var(--lime); }
</style>
""", unsafe_allow_html=True)


def save_upload(uploaded_file) -> Path:
    safe_name = Path(uploaded_file.name).name.replace(" ", "_")
    target = INPUT_DIR / f"{int(time.time())}_{safe_name}"
    target.write_bytes(uploaded_file.getbuffer())
    return target


def render_words_as_text(words: list[dict[str, Any]]) -> str:
    parts = []
    for item in words:
        token = str(item.get("word", item.get("text", ""))).strip()
        if token:
            parts.append(token)
    return " ".join(parts).strip()


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

st.markdown("""
<section class="hero" dir="rtl">
  <div class="eyebrow">إعادة بناء من الصفر · المرحلة 01</div>
  <h1>مختبر الصوت</h1>
  <p>هذه نسخة تأسيسية جديدة. لا تحتوي على محركات المشاهد أو قوالب الموشن القديمة. نثبت أولاً أن الصوت يُقرأ ويُحلّل ويُفرّغ ويُقص بشكل موثوق، ثم نبني نظام الصورة والحركة لاحقاً كمرحلة مستقلة.</p>
</section>
""", unsafe_allow_html=True)

cols = st.columns(3)
for col, number, title, desc in [
    (cols[0], "01", "التفريغ الصوتي", "تحويل الكلام إلى كلمات مع التوقيتات المتاحة."),
    (cols[1], "02", "قص الصمت", "استخراج نسخة أقصر من الصوت أو الفيديو عند وجود صمت طويل."),
    (cols[2], "03", "نتائج قابلة للتصدير", "تنزيل النص أو ملف الكلمات بصيغة JSON."),
]:
    with col:
        st.markdown(f'<div class="step" dir="rtl"><div class="stepnum">{number}</div><div><strong>{title}</strong><small>{desc}</small></div></div>', unsafe_allow_html=True)

st.markdown('<div class="panel" dir="rtl"><div class="panel-title">الملف المصدر</div><div class="panel-sub">ارفع ملفاً صوتياً أو فيديو يحتوي على كلام. الامتدادات المدعومة تعتمد أيضاً على FFmpeg وبيئة التشغيل.</div></div>', unsafe_allow_html=True)
upload = st.file_uploader("اختر ملف الصوت أو الفيديو", type=["wav", "mp3", "m4a", "aac", "flac", "ogg", "mp4", "mov", "mkv", "webm", "avi"], label_visibility="collapsed")

if upload:
    st.success(f"تم اختيار الملف: {upload.name} · {upload.size / (1024 * 1024):.2f} MB")
    left, right = st.columns(2)
    with left:
        st.markdown('<div class="panel" dir="rtl"><div class="panel-title">01 / تفريغ الكلام</div><div class="panel-sub">يستخدم محرك التفريغ الموجود في المشروع. قد يحتاج تنزيل نموذج محلي أو مفاتيح API بحسب بيئة التشغيل والإعدادات.</div></div>', unsafe_allow_html=True)
        model = st.selectbox("حجم نموذج Whisper", ["tiny", "base", "small", "medium", "large-v3"], index=2, help="النماذج الأكبر غالباً أدق لكنها أبطأ وتستهلك موارد أكثر.")
        dialect = st.selectbox("أسلوب اللغة", ["الدارجة الجزائرية", "العربية الفصحى", "العربية العامة"], index=0)
        dialect_code = {"الدارجة الجزائرية": "algerian_darija", "العربية الفصحى": "msa", "العربية العامة": "arabic"}[dialect]
        do_transcribe = st.button("ابدأ تفريغ الصوت", type="primary", use_container_width=True)
    with right:
        st.markdown('<div class="panel" dir="rtl"><div class="panel-title">02 / قص الصمت</div><div class="panel-sub">إنشاء نسخة جديدة بعد قص فترات الصمت الطويلة. لا يتم تعديل الملف الأصلي.</div></div>', unsafe_allow_html=True)
        threshold = st.slider("عتبة الصمت (dBFS)", min_value=-60, max_value=-25, value=-42, step=1)
        silence_ms = st.slider("أقل مدة للصمت (مللي ثانية)", min_value=250, max_value=1500, value=450, step=50)
        padding_ms = st.slider("الهامش حول الكلام (مللي ثانية)", min_value=0, max_value=200, value=55, step=5)
        do_cut = st.button("أنشئ نسخة بعد قص الصمت", use_container_width=True)

    if do_transcribe:
        source_path = save_upload(upload)
        progress = st.progress(0, text="تهيئة محرك التفريغ…")
        try:
            from transcriber import transcribe_audio
            progress.progress(15, text="جارٍ تحليل الملف وتفريغ الكلام…")
            words = transcribe_audio(
                audio_path=str(source_path), model_size=model, language="ar",
                dialect_mode=dialect_code, vad_filter=True,
            )
            progress.progress(100, text="اكتمل التفريغ")
            st.session_state["transcript_words"] = words or []
            st.session_state["transcript_text"] = render_words_as_text(words or [])
            st.session_state["transcript_source"] = upload.name
            if not words:
                st.warning("انتهى المحرك دون كلمات قابلة للعرض. تحقق من الصوت واللغة وإعدادات النموذج.")
            else:
                st.success(f"اكتمل التفريغ: {len(words)} وحدة نصية.")
        except Exception as exc:
            st.error(f"تعذر إكمال التفريغ: {type(exc).__name__}: {exc}")
            st.info("لم نستخدم نصاً تجريبياً بديلاً؛ يجب أن تكون النتيجة ناتجة عن الملف الذي رفعته فعلاً.")
        finally:
            progress.empty()

    if do_cut:
        source_path = save_upload(upload)
        suffix = source_path.suffix.lower()
        output_suffix = ".mp4" if suffix in {".mp4", ".mov", ".mkv", ".webm", ".avi"} else ".mp3"
        output_path = OUTPUT_DIR / f"{source_path.stem}_silence_cut{output_suffix}"
        progress = st.progress(0, text="تحليل فترات الكلام والصمت…")
        try:
            from auto_cut import remove_silence
            result_path = remove_silence(
                str(source_path), str(output_path),
                silence_threshold=float(threshold), min_silence_len=int(silence_ms),
                padding_ms=int(padding_ms),
                progress_callback=lambda value, message: progress.progress(min(99, max(0, int(value * 100))), text=message),
            )
            if not Path(result_path).exists() or Path(result_path).stat().st_size == 0:
                raise RuntimeError("لم ينتج محرك القص ملفاً صالحاً.")
            st.session_state["cut_result_path"] = str(result_path)
            progress.progress(100, text="اكتمل قص الصمت")
            st.success("تم إنشاء نسخة جديدة. الملف الأصلي لم يتغير.")
        except Exception as exc:
            st.error(f"تعذر قص الصمت: {type(exc).__name__}: {exc}")
        finally:
            progress.empty()

if st.session_state.get("transcript_words") is not None:
    words = st.session_state["transcript_words"]
    st.markdown('<div class="panel" dir="rtl"><div class="panel-title">نتيجة التفريغ</div><div class="panel-sub">يمكنك مراجعة النص وتنزيله. لا توجد هنا أي طبقة مونتاج مرئي.</div></div>', unsafe_allow_html=True)
    st.text_area("النص المستخرج", value=st.session_state.get("transcript_text", ""), height=190)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("تنزيل النص TXT", data=st.session_state.get("transcript_text", "").encode("utf-8"), file_name="transcript.txt", mime="text/plain", use_container_width=True)
    with c2:
        st.download_button("تنزيل الكلمات والتوقيتات JSON", data=json_bytes(words), file_name="transcript_words.json", mime="application/json", use_container_width=True)
    with st.expander("عرض بيانات الكلمات والتوقيتات"):
        st.json(words[:300])

if st.session_state.get("cut_result_path"):
    result = Path(st.session_state["cut_result_path"])
    if result.exists():
        st.markdown('<div class="panel" dir="rtl"><div class="panel-title">نسخة الصوت بعد القص</div><div class="panel-sub">ملف منفصل ناتج عن عملية قص الصمت.</div></div>', unsafe_allow_html=True)
        st.audio(str(result)) if result.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".avi"} else st.video(str(result))
        st.download_button("تنزيل الملف الناتج", data=result.read_bytes(), file_name=result.name, mime="application/octet-stream", use_container_width=True)

with st.expander("ما الذي بقي في هذه النسخة؟"):
    st.markdown("""
    - `transcriber.py`: محرك التفريغ وتحسين النص وتوقيت الكلمات.
    - `auto_cut.py`: تحليل الصمت وإنشاء نسخة مقصوصة من الصوت أو الفيديو.
    - `app.py`: واجهة جديدة مستقلة لتجربة هاتين الوظيفتين فقط.

    **غير موجود في واجهة التشغيل الجديدة:** محرك توليد المشاهد، قوالب الخلفيات، مكتبات الموشن القديمة، المؤثرات الصوتية، مخرج الفيديو المرئي، أو نظام الانتقالات القديم.
    """)

st.markdown('<div style="text-align:center;color:#727b8e;font-size:12px;padding:28px 0 4px">إعادة البناء — المرحلة 01: الصوت أولاً، الصورة لاحقاً</div>', unsafe_allow_html=True)
