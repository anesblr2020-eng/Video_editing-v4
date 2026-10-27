from __future__ import annotations

import json
import os
import re
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
from semantic_scene_planner import plan_scenes, scenes_to_json
from github_reports import publish_scene_plan
from visual_scene_prototype import build_scene_html

st.markdown("""
<section class="hero" dir="rtl">
  <div class="eyebrow">إعادة البناء · المرحلة 05</div>
  <h1>مختبر الصوت</h1>
  <p>أرسل مهمة التفريغ أو قص الصمت لتعمل في الخلفية. يمكنك تحديث الصفحة أو إغلاق تبويب المتصفح؛ ستواصل المهمة العمل ما دام خادم التطبيق نفسه يعمل.</p>
</section>
""", unsafe_allow_html=True)

# Reset only the visible workspace; persistent files and background job records remain untouched.
reset_col, reset_note_col = st.columns([1, 2])
with reset_col:
    if st.button("مسح المشروع السابق من الواجهة", type="secondary", use_container_width=True, key="clear_visible_project"):
        st.session_state["jobs_visible_after"] = time.time()
        for state_key in ("planned_scenes", "planned_scenes_source", "last_submitted_job"):
            st.session_state.pop(state_key, None)
        for state_key in list(st.session_state.keys()):
            if state_key == "source_upload" or state_key == "scene_transcript_source" or state_key.startswith("scene_text_"):
                st.session_state.pop(state_key, None)
        st.session_state["workspace_cleared_notice"] = True
        st.rerun()
with reset_note_col:
    st.caption("يمسح النص والخطة السابقة ويخفي المهام القديمة من هذه الواجهة فقط. لا يحذف الملفات أو النتائج المحفوظة على الخادم.")
if st.session_state.pop("workspace_cleared_notice", False):
    st.success("تم تنظيف مساحة العمل في الواجهة. يمكنك بدء مشروع جديد؛ الملفات والنتائج المحفوظة لم تُحذف.")

cols = st.columns(3)
for col, number, title, desc in [
    (cols[0], "01", "معالجة بالخلفية", "لا تحتاج إلى إبقاء شاشة التقدم مفتوحة."),
    (cols[1], "02", "قائمة مهام", "حالة المهمة محفوظة ويمكن العودة إليها."),
    (cols[2], "03", "إعدادات تلقائية", "تفريغ عربي/دارجة وقص الصمت بهامش 65ms."),
]:
    with col:
        st.markdown(f'<div class="step" dir="rtl"><div class="stepnum">{number}</div><div><strong>{title}</strong><small>{desc}</small></div></div>', unsafe_allow_html=True)

st.markdown('<div class="panel" dir="rtl"><div class="panel-title">1 · الملف المصدر</div><div class="panel-sub">ارفع ملف صوت أو فيديو. يُحفظ الملف في مجلد inputs ويُعالج في الخلفية دون تغيير الأصل.</div></div>', unsafe_allow_html=True)
upload = st.file_uploader("اختر ملف الصوت أو الفيديو", type=["wav", "mp3", "m4a", "aac", "flac", "ogg", "mp4", "mov", "mkv", "webm", "avi"], label_visibility="collapsed", key="source_upload")

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
    visible_after = float(st.session_state.get("jobs_visible_after", 0.0))
    jobs = [j for j in list_jobs(limit=100) if float(j.get("created_at", 0.0)) > visible_after][:20]
    if not jobs:
        st.info("لا توجد مهام ظاهرة في مساحة العمل الحالية. ارفع ملفًا وأرسل التفريغ أو قص الصمت إلى الخلفية.")
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

st.markdown('<div class="panel" dir="rtl"><div class="panel-title">المرحلة التالية · تحويل الكلام إلى خطة مشاهد</div><div class="panel-sub">الصق النص المفرّغ هنا. سيحلل المحرك المحلي المعنى التقريبي ويقسّم النص إلى وحدات بصرية، مع اقتراح فكرة مشهد وعناصر وتوقيت مبدئي. هذه مرحلة تخطيط فقط؛ لا تنشئ صورًا أو فيديو بعد.</div></div>', unsafe_allow_html=True)

completed_transcripts = [j for j in list_jobs(limit=100) if j.get("type") == "transcribe" and j.get("status") == "completed" and j.get("transcript_text")]
transcript_options = {f"{j.get('original_name', 'ملف')} · {time.strftime('%H:%M', time.localtime(j.get('created_at', time.time())))}": j.get("transcript_text", "") for j in completed_transcripts}
selected_transcript = st.selectbox("استخدام نص من تفريغ سابق (اختياري)", ["إدخال نص يدوي"] + list(transcript_options.keys()), key="scene_transcript_source")
default_scene_text = transcript_options.get(selected_transcript, "") if selected_transcript != "إدخال نص يدوي" else ""
scene_text = st.text_area("النص المراد تحويله إلى خطة مشاهد", value=default_scene_text, height=180, placeholder="مثال: بدأت مشروعي من الصفر، وبعدها قررت بناء علامة تجارية خاصة بي...", key=f"scene_text_{selected_transcript}")
if st.button("تحليل المعنى وتقسيمه إلى مشاهد", type="primary", use_container_width=True, disabled=not scene_text.strip()):
    planned = plan_scenes(scene_text)
    st.session_state["planned_scenes"] = planned
    st.session_state["planned_scenes_source"] = scene_text

planned_scenes = st.session_state.get("planned_scenes", [])
if planned_scenes:
    st.success(f"تم إنشاء خطة أولية من {len(planned_scenes)} مشاهد. هذه خطة أولية بأسلوب تحريري مستلهم من المراجع؛ التصنيف محلي وقد يحتاج مراجعة.")
    for scene in planned_scenes:
        with st.container(border=True):
            st.markdown(f"**المشهد {scene['scene_number']:02d} · {scene['intent_label']}**")
            st.write(scene["spoken_text"])
            c1, c2 = st.columns(2)
            with c1:
                st.caption("الفكرة البصرية")
                st.write(scene["visual_concept"])
                st.caption("العناصر المقترحة")
                st.write("، ".join(scene["visual_elements"]))
            with c2:
                st.caption("توجيه التكوين")
                st.write(scene["composition"])
                st.caption("الحركة المقترحة")
                st.write(scene["motion_direction"])
            if scene.get("start_time") is not None and scene.get("end_time") is not None:
                st.caption(f"التوقيت التقديري: {scene['start_time']:.2f}s – {scene['end_time']:.2f}s")
    st.markdown('<div class="panel" dir="rtl"><div class="panel-title">المرحلة 08 · نموذج أول مشهد متحرك</div><div class="panel-sub">تم تحديث النموذج ليتبع أسلوب المراجع: تكوين تحريري عمودي، نص حركي، تباين قوي، ومشاهد مخصصة للمونتاج والذكاء الاصطناعي. المعاينة ما تزال نموذج SVG/HTML وليست فيديو واقعيًا نهائيًا.</div></div>', unsafe_allow_html=True)
    scene_labels = [f"{item['scene_number']:02d} · {item.get('intent_label', item.get('intent', 'مشهد'))} · {item.get('spoken_text', '')[:45]}" for item in planned_scenes]
    selected_scene_index = st.selectbox("اختر مشهدًا للنموذج", range(len(planned_scenes)), format_func=lambda i: scene_labels[i], key="visual_scene_pick")
    scene_image = st.file_uploader("صورة واقعية لهذا المشهد (اختياري)", type=["png", "jpg", "jpeg", "webp"], key="scene_visual_asset", help="عند رفع صورة، تستخدمها المعاينة بدل الرسم المتجهي المؤقت. تُضمّن الصورة داخل HTML الذي تنزّله.")
    if scene_image:
        st.image(scene_image, caption="الأصل البصري الذي سيُستخدم في المعاينة", use_container_width=True)
    if st.button("إنشاء معاينة المشهد", type="primary", use_container_width=True, key="build_visual_scene"):
        image_data_uri = None
        if scene_image:
            import base64
            mime = scene_image.type if scene_image.type in {"image/png", "image/jpeg", "image/webp"} else "image/png"
            image_data_uri = f"data:{mime};base64,{base64.b64encode(scene_image.getvalue()).decode('ascii')}"
        st.session_state["visual_scene_html"] = build_scene_html(planned_scenes[selected_scene_index], image_data_uri=image_data_uri)
        st.session_state["visual_scene_label"] = scene_labels[selected_scene_index]
    if st.session_state.get("visual_scene_html"):
        st.caption(f"المعاينة الحالية: {st.session_state.get('visual_scene_label', 'مشهد')}")
        st.components.v1.html(st.session_state["visual_scene_html"], height=760, scrolling=False)
        st.download_button("تنزيل معاينة المشهد HTML", data=st.session_state["visual_scene_html"].encode("utf-8"), file_name="visual_scene_prototype.html", mime="text/html", use_container_width=True)
    st.download_button("تنزيل خطة المشاهد JSON", data=scenes_to_json(planned_scenes).encode("utf-8"), file_name="semantic_scene_plan.json", mime="application/json", use_container_width=True)
    st.warning("مستودعك عام: عند النشر سيصبح نص المشاهد وخطتها متاحين للعامة. لا تنشر محتوى حساسًا.")
    if st.button("نشر تقرير المشاهد إلى GitHub ونسخ رابطه", use_container_width=True, key="publish_scene_report"):
        try:
            with st.spinner("جارٍ نشر تقرير JSON صغير إلى مستودع GitHub..."):
                published = publish_scene_plan(planned_scenes, st.session_state.get("planned_scenes_source", ""))
            st.session_state["last_github_report_url"] = published["url"]
            st.success("تم نشر التقرير بنجاح. انسخ الرابط التالي وأرسله في محادثتنا للمراجعة.")
            st.code(published["url"], language=None)
            st.link_button("فتح التقرير في GitHub", published["url"], use_container_width=True)
        except Exception as exc:
            st.error(f"تعذر نشر التقرير: {exc}")


with st.expander("إعداد النشر إلى GitHub (مرة واحدة)"):
    st.markdown(
        """
        1. أنشئ Fine-grained personal access token من إعدادات GitHub.
        2. اختر المستودع `Video_editing-v4` فقط، وامنح صلاحية **Contents: Read and write**.
        3. أضف الرمز في Secrets على منصة الاستضافة باسم `GITHUB_TOKEN`، وأضف `GITHUB_REPO_OWNER = \"anesblr2020-eng\"` و`GITHUB_REPO_NAME = \"Video_editing-v4\"` و`GITHUB_REPO_BRANCH = \"main\"`.
        4. لا تضع الرمز في الكود أو GitHub ولا ترسله في المحادثة.

        النشر يدوي عند الضغط فقط، ويحفظ ملف JSON صغيرًا داخل `reports/`؛ لا يرفع الصوت أو الفيديو.
        """
    )

with st.expander("مهم حول العمل في الخلفية"):
    st.markdown("""
    - تستمر المهمة عند إعادة تحميل الصفحة أو إغلاق تبويب المتصفح **ما دام خادم Python مستمرًا في العمل**.
    - هذا الإصدار يستخدم عاملًا خلفيًا داخل عملية التطبيق، مع قائمة مهام محفوظة في `temp/jobs/`؛ ولا يحتاج خدمة خارجية إضافية.
    - إذا أوقفت منصة الاستضافة الخادم أو أعادت تشغيله أو وضعته في السكون، فقد تتوقف المهمة الجارية. المهام التي لم تنتهِ تُعلَّم عند بدء الخادم التالي بأنها متوقفة، ويمكن إرسالها من جديد.
    - هذه ليست بعدُ قائمة مهام موزعة/مضمونة الاستمرار عبر إعادة تشغيل الخادم؛ لذلك لا نعد باستمرار المعالجة إذا أُغلق الخادم نفسه.
    """)

st.markdown('<div style="text-align:center;color:#60736a;font-size:12px;padding:28px 0 4px">إعادة البناء — المرحلة 08: الصوت والتخطيط الدلالي ونموذج المشهد</div>', unsafe_allow_html=True)
