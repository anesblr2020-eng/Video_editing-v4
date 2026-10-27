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
:root { --bg:#f4f7f5; --panel:#ffffff; --panel2:#edf3ef; --line:#dce6df; --ink:#20332c; --muted:#60736a; --accent:#287b67; --accent-soft:#e0f1eb; --blue:#426b91; }
html, body, [class*="css"] { font-family:'IBM Plex Sans Arabic',sans-serif; }
.stApp { background:linear-gradient(180deg,#f7faf8 0%,var(--bg) 45%,#eef4f0 100%); color:var(--ink); }
.block-container { max-width:1160px; padding-top:2rem; padding-bottom:4rem; }
#MainMenu, footer { visibility:hidden; }
header[data-testid="stHeader"] { background:transparent; }
.hero { border:1px solid var(--line); background:linear-gradient(120deg,#ffffff 0%,#eaf5ef 100%); border-radius:24px; padding:30px 32px; margin-bottom:22px; position:relative; overflow:hidden; box-shadow:0 8px 28px rgba(32,64,48,.055); }
.hero:after { content:'◉'; position:absolute; left:28px; top:-44px; font-size:180px; color:rgba(40,123,103,.055); }
.eyebrow { color:var(--accent); font-size:12px; letter-spacing:.8px; font-weight:700; }
.hero h1 { font-size:clamp(30px,4vw,46px); line-height:1.3; margin:12px 0 10px; color:var(--ink); font-weight:700; }
.hero p { color:var(--muted); max-width:700px; font-size:16px; line-height:1.9; margin:0; }
.step { display:flex; gap:13px; align-items:center; padding:15px 17px; border:1px solid var(--line); background:rgba(255,255,255,.88); border-radius:16px; margin-bottom:12px; box-shadow:0 3px 12px rgba(32,64,48,.025); }
.stepnum { display:grid; place-items:center; min-width:38px; height:38px; border-radius:12px; background:var(--accent-soft); color:var(--accent); font-weight:700; }
.step strong { display:block; font-size:16px; color:var(--ink); }
.step small { display:block; color:var(--muted); margin-top:3px; line-height:1.6; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:22px; margin:12px 0 18px; box-shadow:0 5px 20px rgba(32,64,48,.035); }
.panel-title { font-size:20px; font-weight:700; margin-bottom:5px; color:var(--ink); }
.panel-sub { color:var(--muted); font-size:14px; line-height:1.8; margin-bottom:18px; }
div[data-testid="stFileUploader"] { border:1px dashed #a9c4b7; border-radius:16px; padding:8px; background:#f8fbf9; }
.stButton > button, .stDownloadButton > button { border-radius:12px; min-height:45px; font-weight:700; border:1px solid #c8d8cf; color:var(--ink); background:#fff; transition:all .15s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color:var(--accent); color:var(--accent); background:#f2faf6; }
.stButton > button[kind="primary"] { background:var(--accent); color:#fff; border:1px solid var(--accent); }
.stButton > button[kind="primary"]:hover { background:#206b59; color:#fff; }
div[data-testid="stTabs"] button { font-weight:600; color:var(--muted); }
div[data-testid="stAlert"] { border-radius:14px; }
.metric-card { border:1px solid var(--line); background:var(--panel2); border-radius:15px; padding:14px 16px; }
.metric-card span { color:var(--muted); font-size:12px; }
.metric-card b { display:block; color:var(--accent); font-size:23px; margin-top:5px; }
div[data-testid="stProgress"] > div > div { background:var(--accent); }
.stTextArea textarea { background:#fbfdfb; color:var(--ink); border-color:var(--line); line-height:1.9; }
small, .stCaption { color:var(--muted) !important; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition:none !important; animation:none !important; scroll-behavior:auto !important; } }
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

from jobs import get_job, list_jobs, submit_job

st.markdown("""
<section class="hero" dir="rtl">
  <div class="eyebrow">إعادة البناء · المرحلة 02</div>
  <h1>مختبر الصوت</h1>
  <p>أرسل مهمة التفريغ أو قص الصمت لتعمل في الخلفية. يمكنك تحديث الصفحة أو إغلاق تبويب المتصفح؛ ستواصل المهمة العمل ما دام خادم التطبيق نفسه يعمل.</p>
</section>
""", unsafe_allow_html=True)

cols = st.columns(3)
for col, number, title, desc in [
    (cols[0], "01", "معالجة بالخلفية", "لا تحتاج إلى إبقاء شاشة التقدم مفتوحة."),
    (cols[1], "02", "قائمة مهام", "حالة المهمة محفوظة ويمكن العودة إليها."),
    (cols[2], "03", "إعدادات تلقائية", "تفريغ عربي/دارجة وقص الصمت بهامش 65ms."),
]:
    with col:
        st.markdown(f'<div class="step" dir="rtl"><div class="stepnum">{number}</div><div><strong>{title}</strong><small>{desc}</small></div></div>', unsafe_allow_html=True)

st.markdown('<div class="panel" dir="rtl"><div class="panel-title">1 · الملف المصدر</div><div class="panel-sub">ارفع ملف صوت أو فيديو. يُحفظ الملف في مجلد inputs ويُعالج في الخلفية دون تغيير الأصل.</div></div>', unsafe_allow_html=True)
upload = st.file_uploader("اختر ملف الصوت أو الفيديو", type=["wav", "mp3", "m4a", "aac", "flac", "ogg", "mp4", "mov", "mkv", "webm", "avi"], label_visibility="collapsed")

if upload:
    st.success(f"تم اختيار الملف: {upload.name} · {upload.size / (1024 * 1024):.2f} MB")
    left, right = st.columns(2)
    with left:
        st.markdown('<div class="panel" dir="rtl"><div class="panel-title">2 · تفريغ الكلام</div><div class="panel-sub">الإعدادات تلقائية: نموذج small، اللغة العربية، وتوجيه للدارجة الجزائرية.</div></div>', unsafe_allow_html=True)
        if st.button("إرسال التفريغ إلى الخلفية", type="primary", use_container_width=True):
            source_path = save_upload(upload)
            job_id = submit_job("transcribe", str(source_path), upload.name)
            st.session_state["last_submitted_job"] = job_id
            st.success("أُضيفت مهمة التفريغ إلى قائمة الانتظار.")
    with right:
        st.markdown('<div class="panel" dir="rtl"><div class="panel-title">3 · قص الصمت تلقائيًا</div><div class="panel-sub">قص الصمت بإعدادات ثابتة، وهامش أمان 65 مللي ثانية حول الكلام.</div></div>', unsafe_allow_html=True)
        if st.button("إرسال قص الصمت إلى الخلفية", use_container_width=True):
            source_path = save_upload(upload)
            job_id = submit_job("cut_silence", str(source_path), upload.name)
            st.session_state["last_submitted_job"] = job_id
            st.success("أُضيفت مهمة قص الصمت إلى قائمة الانتظار.")

st.markdown('<div class="panel" dir="rtl"><div class="panel-title">قائمة المهام</div><div class="panel-sub">تتحدّث الحالة تلقائيًا كل ثانيتين أثناء فتح الصفحة. يمكن للمعالجة الاستمرار بعد إغلاق التبويب ما دام خادم التطبيق يعمل ولم يدخل في السكون أو يُعد تشغيله.</div></div>', unsafe_allow_html=True)

STATUS_LABELS = {
    "queued": "في قائمة الانتظار",
    "running": "قيد التنفيذ بالخلفية",
    "completed": "اكتملت",
    "failed": "فشلت",
    "interrupted": "توقفت بسبب إعادة تشغيل الخادم",
}

@st.fragment(run_every="2s")
def render_jobs():
    jobs = list_jobs(limit=20)
    if not jobs:
        st.info("لا توجد مهام بعد. ارفع ملفًا وأرسل التفريغ أو قص الصمت إلى الخلفية.")
        return
    for job in jobs:
        title = "تفريغ الكلام" if job.get("type") == "transcribe" else "قص الصمت"
        status = job.get("status", "queued")
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(job.get("created_at", time.time())))
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{title}** · `{job.get('original_name', 'ملف')}`")
                st.caption(f"بدأت/أُرسلت: {created} · {job.get('message', '')}")
            with c2:
                st.markdown(f"**{STATUS_LABELS.get(status, status)}**")
            if status in {"queued", "running"}:
                st.progress(float(job.get("progress", 0.0)), text=f"التقدم المسجل: {int(float(job.get('progress', 0.0))*100)}%")
            elif status == "failed":
                st.error(job.get("message", "حدث خطأ غير معروف."))
            elif status == "interrupted":
                st.warning(job.get("message", "توقفت المهمة."))
            elif status == "completed":
                paths = job.get("result_paths", {})
                if job.get("type") == "transcribe":
                    transcript = job.get("transcript_text", "")
                    if transcript:
                        st.text_area("النص المستخرج", value=transcript, height=130, key=f"transcript_{job['id']}")
                    for key, label, mime in [("text", "تنزيل النص TXT", "text/plain"), ("json", "تنزيل الكلمات والتوقيتات JSON", "application/json")]:
                        result = Path(paths.get(key, "")) if paths.get(key) else None
                        if result and result.is_file():
                            st.download_button(label, data=result.read_bytes(), file_name=result.name, mime=mime, key=f"download_{key}_{job['id']}")
                else:
                    result = Path(paths.get("media", "")) if paths.get("media") else None
                    if result and result.is_file():
                        ext = result.suffix.lower()
                        if ext in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
                            st.video(str(result))
                        else:
                            st.audio(str(result))
                        st.download_button("تنزيل الملف الناتج", data=result.read_bytes(), file_name=result.name, mime="application/octet-stream", key=f"download_media_{job['id']}")

render_jobs()

with st.expander("مهم حول العمل في الخلفية"):
    st.markdown("""
    - تستمر المهمة عند إعادة تحميل الصفحة أو إغلاق تبويب المتصفح **ما دام خادم Python مستمرًا في العمل**.
    - هذا الإصدار يستخدم عاملًا خلفيًا داخل عملية التطبيق، مع قائمة مهام محفوظة في `temp/jobs/`؛ ولا يحتاج خدمة خارجية إضافية.
    - إذا أوقفت منصة الاستضافة الخادم أو أعادت تشغيله أو وضعته في السكون، فقد تتوقف المهمة الجارية. المهام التي لم تنتهِ تُعلَّم عند بدء الخادم التالي بأنها متوقفة، ويمكن إرسالها من جديد.
    - هذه ليست بعدُ قائمة مهام موزعة/مضمونة الاستمرار عبر إعادة تشغيل الخادم؛ لذلك لا نعد باستمرار المعالجة إذا أُغلق الخادم نفسه.
    """)

st.markdown('<div style="text-align:center;color:#60736a;font-size:12px;padding:28px 0 4px">إعادة البناء — المرحلة 02: مهام صوتية تعمل في الخلفية</div>', unsafe_allow_html=True)
