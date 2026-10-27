# -*- coding: utf-8 -*-
"""Local first-pass semantic scene planner for Arabic and Algerian Darija.

This module plans scenes only. It deliberately does not render images/video and
has no dependency on the retired visual engines or paid APIs. Its keyword and
sentence heuristics are a baseline to validate before adding an optional LLM.
"""
from __future__ import annotations

import json
import re
from typing import Any

_WORD_RE = re.compile(r"[\wـ]+(?:['’][\w]+)?", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!؟?؛…])\s+|[\n\r]+")

_INTENTS: list[tuple[str, str, tuple[str, ...], str, list[str], str, str]] = [
    ("problem", "مشكلة أو تحدٍّ", ("مشكلة", "مشكل", "صعب", "صعوبة", "ما نقدرش", "ما عنديش", "ماكانش", "تعب", "خايف", "قلق", "علاش", "عائق"),
     "إظهار مصدر المشكلة بشكل ملموس في بيئته الطبيعية، مع إبراز العنصر الذي يسبب التحدي.", ["الشخص المعني", "العنصر المسبب للمشكلة", "تفصيل من البيئة"], "تكوين قريب يوضح المشكلة ثم يكشف سياقها.", "حركة كاميرا هادئة نحو العنصر المسبب، مع فعل بصري واضح."),
    ("beginning", "بداية أو انطلاق", ("بدأ", "بديت", "نبدا", "من الصفر", "أول مرة", "اول مرة", "انطلقت", "البداية", "مشروعي"),
     "تصوير لحظة البداية بأدوات وموارد واقعية مرتبطة بما يقوله المتحدث.", ["الشخص الذي يبدأ", "أدوات البداية", "مكان العمل"], "لقطة متوسطة تُظهر الشخص والأدوات والسياق في إطار واحد.", "حركة دخول تدريجية أو انتقال من التفاصيل إلى المشهد الكامل."),
    ("process", "خطوات أو عملية", ("خطوة", "خطوات", "كيفاش", "طريقة", "نقوم", "ندير", "نخدم", "نصنع", "نركب", "نجهز", "بعدها", "ثم", "أولا", "ثانيا"),
     "إظهار الفعل أو الخطوة التي يصفها النص، مع أدواتها ونتيجتها الجزئية، لا الاكتفاء برمز عام.", ["الشخص المنفذ", "الأداة المستخدمة", "نتيجة الخطوة"], "لقطة عملية تُظهر اليدين والأداة والنتيجة ضمن بيئة العمل المناسبة.", "حركة فعلية للأداة أو اليدين مع تتبع بصري للعملية."),
    ("product", "منتج أو شيء ملموس", ("منتج", "كابل", "عطر", "قارورة", "هاتف", "جهاز", "سلعة", "ماركة", "علامة تجارية", "عبوة", "منتجات"),
     "مشهد منتج واضح يُظهر الشيء المذكور نفسه وخصائصه أو استخدامه ضمن سياق مناسب.", ["المنتج المذكور", "تفصيل يميّزه", "سياق الاستخدام"], "المنتج هو العنصر البصري الرئيسي مع مساحة كافية لإظهار التفاصيل.", "دوران أو حركة اقتراب خفيفة حول المنتج مع إبراز تفصيل محدد."),
    ("money", "مال أو تكلفة", ("مال", "فلوس", "دينار", "سعر", "تكلفة", "ميزانية", "ربح", "خسارة", "مبلغ", "نبيع", "نشتري"),
     "تمثيل بصري واقعي للمبلغ أو قرار الشراء/البيع الذي يتحدث عنه النص، مع تجنب أرقام مختلقة.", ["نقود أو فاتورة عند الحاجة", "العنصر المالي المذكور", "بيئة المعاملة"], "لقطة واضحة على العنصر المالي مع إظهار سياق المعاملة.", "انتقال التركيز من المبلغ إلى الشيء المرتبط به."),
    ("social", "منصات أو تواصل", ("متابعين", "متابع", "إنستغرام", "انستغرام", "تيك توك", "تيكتوك", "فيسبوك", "منشور", "إعلان", "إشهار", "سبونسر", "مشاهدات", "محتوى"),
     "إظهار فعل التواصل أو نشر المحتوى على جهاز ضمن مشهد استخدام واقعي، لا خلفية تقنية مجردة.", ["هاتف أو حاسوب", "واجهة محتوى عامة غير منسوخة", "الشخص المستخدم"], "لقطة فوق الكتف أو لقطة قريبة للجهاز مع سياق المكان.", "تمرير أو نشر فعلي على الشاشة مع حركة كاميرا خفيفة."),
    ("decision", "قرار أو هدف", ("قررت", "نقرر", "هدفي", "حلمي", "حاب", "نحب", "نريد", "لازم", "سوف", "راح ندير", "نخطط"),
     "تجسيد القرار عبر فعل واضح يبيّن الاختيار أو الانتقال نحو الهدف.", ["الشخص صاحب القرار", "الخيار أو الهدف", "علامة سياقية من البيئة"], "الشخص في المقدمة والهدف واضح في عمق المشهد.", "حركة تبدأ من الشخص وتنتهي عند الهدف أو الخيار المختار."),
    ("result", "نتيجة أو نجاح", ("نجحت", "النتيجة", "ربحت", "حققنا", "وصلت", "تطور", "تحسن", "نجاح", "اكتمل", "أفضل"),
     "إظهار نتيجة ملموسة تدعم الكلام، مع عدم اختراع أرقام أو إنجازات لم يذكرها المتحدث.", ["النتيجة الموصوفة", "أثرها العملي", "الشخص أو الشيء المرتبط بها"], "تكوين يكشف النتيجة بوضوح ويتركها مركز الاهتمام.", "كشف تدريجي للنتيجة يتبعه تثبيت قصير على التفاصيل."),
    ("time", "وقت أو استعجال", ("وقت", "الوقت", "دقيقة", "ساعة", "سريع", "بسرعة", "تأخر", "متأخر", "كل يوم", "يوميا"),
     "إظهار علاقة الشخص بالوقت أو ضغط المهمة عبر نشاط حقيقي وأدوات زمنية عند الحاجة.", ["الشخص أثناء العمل", "أداة زمنية عند ملاءمتها", "المهمة المطلوبة"], "لقطة تجمع المهمة ومؤشر الوقت دون مبالغة بصرية.", "تسريع محدود لحركة العمل أو انتقال زمني واضح ومبرر."),
    ("emotion", "شعور أو تجربة شخصية", ("فرحت", "حزنت", "تعبت", "خفت", "توتر", "محبط", "حسيت", "شعوري", "تجربة", "ندمت"),
     "إظهار التجربة من خلال لغة الجسد وتفاصيل المكان والحدث المرتبط بها، لا عبر وجه تعبيري منفصل فقط.", ["الشخص", "تفصيل من الموقف", "البيئة المحيطة"], "لقطة متوسطة أو قريبة تسمح بقراءة لغة الجسد وسياق الحدث.", "حركة كاميرا بطيئة تتبع رد الفعل أو الفعل الذي ولّد الشعور."),
]

_GENERIC = ("explanation", "شرح أو فكرة عامة", (),
    "اختيار مشهد ملموس من الأسماء والأفعال الواردة في النص. إذا لم يذكر النص شيئًا ملموسًا، تُعرض بيئة مرتبطة بموضوعه دون اختلاق تفاصيل محددة.",
    ["الشخص أو الشيء المذكور في النص", "فعل يطابق العبارة", "بيئة منطقية للسياق"],
    "تكوين يوضح العلاقة بين الفاعل والفعل والشيء، مع تجنب الزخارف غير المرتبطة بالمعنى.",
    "حركة كاميرا خفيفة تتبع الفعل الرئيسي؛ لا تُضاف حركة لمجرد الزينة.")


def _normalise(text: str) -> str:
    text = text.lower().replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _classify(text: str) -> tuple[str, str, str, list[str], str, str]:
    norm = _normalise(text)
    scored: list[tuple[int, tuple[str, str, tuple[str, ...], str, list[str], str, str]]] = []
    for spec in _INTENTS:
        hits = sum(1 for phrase in spec[2] if _normalise(phrase) in norm)
        if hits:
            scored.append((hits, spec))
    if not scored:
        spec = _GENERIC
    else:
        # Stable ordering breaks ties consistently; avoid random scene classifications.
        spec = sorted(scored, key=lambda item: (-item[0], _INTENTS.index(item[1])))[0][1]
    return spec[0], spec[1], spec[3], list(spec[4]), spec[5], spec[6]


def _split_long(text: str, max_words: int = 32) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text.strip()] if text.strip() else []
    # Prefer conjunctions/semantic pivots when possible, then hard split as a fallback.
    pieces: list[str] = []
    current: list[str] = []
    pivots = {"لكن", "ولكن", "بصح", "ومن", "وبعدها", "بعدها", "ثم", "لأن", "باسكو", "لهذا", "باش"}
    for word in words:
        clean = re.sub(r"[^\wـ]", "", word)
        if len(current) >= 12 and clean in pivots and len(current) >= 8:
            pieces.append(" ".join(current).strip())
            current = []
        current.append(word)
        if len(current) >= max_words:
            pieces.append(" ".join(current).strip())
            current = []
    if current:
        pieces.append(" ".join(current).strip())
    return [piece for piece in pieces if piece]


def _sentences(text: str) -> list[str]:
    raw = [s.strip(" \t-–—") for s in _SENTENCE_SPLIT_RE.split(text) if s.strip(" \t-–—")]
    chunks: list[str] = []
    for sentence in raw:
        chunks.extend(_split_long(sentence))
    # Merge tiny fragments with a neighbor to avoid one-word scenes.
    merged: list[str] = []
    for chunk in chunks:
        if merged and len(chunk.split()) < 5 and len(merged[-1].split()) < 24:
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)
    return merged


def plan_scenes(text: str, words: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Create a deterministic scene-plan list from a transcript.

    Word-level timestamps are optional. If supplied, each scene receives an
    approximate time range by matching its word sequence to the transcript's
    ordered word records. Text-only mode intentionally leaves timestamps null.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    segments = _sentences(text)
    timed_words = [w for w in (words or []) if isinstance(w, dict) and str(w.get("word", w.get("text", ""))).strip()]
    word_cursor = 0
    scenes: list[dict[str, Any]] = []
    for idx, segment in enumerate(segments, 1):
        intent, label, concept, elements, composition, motion = _classify(segment)
        start_time = end_time = None
        if timed_words:
            seg_tokens = [_normalise(x) for x in _WORD_RE.findall(segment)]
            found_start = None
            found_end = None
            # Sequential approximate alignment avoids assigning the same early word to every scene.
            search_stop = min(len(timed_words), word_cursor + max(20, len(seg_tokens) * 4))
            for pos in range(word_cursor, search_stop):
                token = _normalise(str(timed_words[pos].get("word", timed_words[pos].get("text", ""))))
                target = seg_tokens[0] if seg_tokens else ""
                if token.strip(".,،؛:!?؟") == target.strip(".,،؛:!؟?") or target in token or token in target:
                    found_start = pos
                    break
            if found_start is None and word_cursor < len(timed_words):
                found_start = word_cursor
            if found_start is not None:
                found_end = min(len(timed_words) - 1, found_start + max(0, len(seg_tokens) - 1))
                try:
                    start_time = max(0.0, float(timed_words[found_start].get("start", 0.0)))
                    end_time = max(start_time, float(timed_words[found_end].get("end", start_time)))
                    word_cursor = found_end + 1
                except (TypeError, ValueError):
                    start_time = end_time = None
        scenes.append({
            "scene_number": idx,
            "spoken_text": segment,
            "intent": intent,
            "intent_label": label,
            "visual_concept": concept,
            "visual_elements": elements,
            "composition": composition,
            "motion_direction": motion,
            "start_time": round(start_time, 3) if start_time is not None else None,
            "end_time": round(end_time, 3) if end_time is not None else None,
            "planning_method": "local_heuristic_v1",
            "limitations": "خطة أولية بقواعد محلية؛ قد تحتاج مراجعة بشرية ولا تمثل فهمًا لغويًا عميقًا أو توليدًا بصريًا.",
        })
    return scenes


def scenes_to_json(scenes: list[dict[str, Any]]) -> str:
    return json.dumps({"schema_version": "1.0", "planner": "local_heuristic_v1", "scenes": scenes}, ensure_ascii=False, indent=2)
