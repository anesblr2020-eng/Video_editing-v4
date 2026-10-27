# -*- coding: utf-8 -*-
"""
transcriber.py - محرك التفريغ الصوتي الهجين، إعادة جدولة التوقيت بعد القص (Word-Level Timestamp Remapping)،
ومزامنة التعديلات الحية ثنائية الاتجاه (Live Scene & Caption Override Sync)
=======================================================================================================================
التحديثات الجوهرية (Alex Hormozi High-Retention Engine - Phase 1):
1. استخراج وتنقية التوقيت الدقيق كلمة بكلمة (`Word-level Timestamps`: `word`, `start`, `end`, `probability`).
2. دالة `recalculate_word_timestamps_after_cuts`: إعادة حساب كافة الـ Timestamps للكلمات والجمل تلقائياً بعد قص فترات الصمت (`> 0.25s`)
   أو قص الإعادات الخاطئة، لضمان تزامن الكابشن والرسومات مع الصوت الجديد بنسبة 100%.
3. دالة `sync_live_scene_edits_to_words`: الجسر التفاعلي الذي يمنع عودة الكلمات القديمة (مثل "ينوضي") بعد تعديلها من واجهة الموقع (`app.py`)
   إلى ("يمونتي")، ويعيد بناء مصفوفة `words` و `word_strings` وتوزيع التوقيت الزمني وإعادة توجيه الرسمة البصرية بناءً على الكلمات المفتاحية الجديدة.
4. قاموس موسع للدارجة الجزائرية والعربية يشمل تصحيح أخطاء شائعة مثل (`تنوضي / ينوضي -> يمونتي / تمنتج`، `لي فيديو -> الفيديوهات`).
"""

import sys
import os
import gc
import ctypes
import subprocess

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

import re
import json
import math
import base64
import difflib
import logging
from typing import List, Dict, Any, Optional, Tuple

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _force_free_ram():
    try:
        gc.collect()
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


try:
    from smart_analyzer import query_hybrid_llm
except ImportError:
    def query_hybrid_llm(*args, **kwargs):
        return None


# ==============================================================================
# 1. إعدادات وموجهات الدارجة الجزائرية ومصطلحات المونتاج والتقنية والتجارة
# ==============================================================================
ALGERIAN_DARIJA_INITIAL_PROMPT = (
    "تسجيل بالدارجة الجزائرية والعربية: واش راكم، كاين بزاف ناس، درك، دوكا، علاش، كيفاش، بزاف، ماكانش، "
    "يمونتي، تمنتج، مونتاج، ريلز، شورتس، فيديوهات، ذكاء اصطناعي، منصة، سيبور، تشارجي، اكموندي، "
    "حاجة شابة، مليح، خاوتي، صحيتو، نقدروا نديرو، معنتها، باسكو، ديجا، نورمالمون، قاع، والو، مرحبا بكم."
)

ALGERIAN_DARIJA_LEXICON_FIXES = {
    # تصحيحات خاصة بمصطلحات المونتاج وصناعة المحتوى بالدارجة الجزائرية
    "تنوضي": "يمونتي",
    "ايديتين": "إيديتينغ",
    "ايديتينغ": "إيديتينغ",
    "إيديتين": "إيديتينغ",
    "وبالاي": "وبالـ AI",
    "بالاي": "بالـ AI",
    "ينوضي": "يمونتي",
    "نوضي": "يمونتي",
    "يمونطي": "يمونتي",
    "تمونطي": "تمونتي",
    "تمنطي": "تمونتي",
    "يمنطي": "يمونتي",
    "نمونطي": "نمنتج",
    "مونطي": "مونتاج",
    "مونتاجي": "مونتاج",
    "أصبر": "اصبر",
    "أصبر،": "اصبر،",
    "استكش": "ما حبستكش",
    "ماحبستكش": "ما حبستكش",
    "محبستكش": "ما حبستكش",
    "حبستكش": "ما حبستكش",
    "علاجال": "على جال",
    "علاجلك": "على جال",
    "تيبسي": "تيب سي",
    "تايبسي": "تيب سي",
    "سيرفر": "سيبور",
    "سيبورت": "سيبور",
    "سبور": "سيبور",
    "تشارجي": "تشارجي",
    "تشرجي": "تشارجي",
    "شارجي": "تشارجي",
    "يتشارجا": "يتشارجا",
    "تلقاوش": "يلقاوش",
    "فاستا": "فاست",
    "معناتها": "معنتها",
    "معنتها": "معنتها",
    "ومتخافش": "وما تخافش",
    "ماتخافش": "ما تخافش",
    "متخافش": "ما تخافش",
    "كاع": "قاع",
    "قاع": "قاع",
    "المتوفرس": "متوفر",
    "متوفرس": "متوفر",
    "أكموان": "اكموندي",
    "اكموان": "اكموندي",
    "أكموندي": "اكموندي",
    "كوموندي": "اكموندي",
    "كموندي": "اكموندي",
    "لنلو": "أهلاً",
    "لنلو،": "أهلاً،",
    "اهلا": "أهلاً",
    "سنه": "سنة",
    "منصه": "منصة",
    "المنصه": "المنصة",
    "استناعي": "اصطناعي",
    "إستناعي": "اصطناعي",
    "بذكاء": "بالذكاء",
    "اوتوماتيكي": "أوتوماتيكي",
    "أغالب": "أغلب",
    "اغالب": "أغلب",
    "اغلب": "أغلب",
    "لان": "لأن",
    "هنده": "عندها",
    "عنده": "عنده",
    "ريز": "ريلز",
    "ريز،": "ريلز،",
    "الريز": "الريلز",
    "للرز": "للريلز",
    "للريز": "للريلز",
    "لريز": "للريلز",
    "لريلز": "للريلز",
    "الرز": "الريلز",
    "وشراكم": "واش راكم",
    "واشراكم": "واش راكم",
    "علاه": "علاش",
    "كفاش": "كيفاش",
    "بالزاف": "بزاف",
    "ما كاش": "ماكانش",
    "مكانش": "ماكانش",
    "دركا": "درك",
    "دوكة": "دوكا",
    "عفسه": "عفسة",
    "خوتي": "خاوتي",
    "صحيتوا": "صحيتو",
    "نديروا": "نديرو",
    "نقدرو": "نقدروا",
    "بارسكو": "باسكو",
    "ديجة": "ديجا",
    "نورمالمو": "نورمالمون",
    "نتاع": "تاع",
    "هاذي": "هاذ",
    "كلشي": "كلش",
    "ليفريزو": "ليفريزون",
    "الخاصيه": "الخاصية",
    "للخاصيه": "للخاصية",
    "الاولى": "الأولى",
    "الثانيه": "الثانية",
    "الثالثه": "الثالثة",
    "الرابعه": "الرابعة",
    "الخامسه": "الخامسة",
    "الانتاجيه": "الإنتاجية",
    "المسؤوله": "المسؤولة",
    "دقيقه": "دقيقة",
    "ساعه": "ساعة",
    "جوده": "جودة",
    "صوره": "صورة",
    "مباشره": "مباشرة",
    "واحده": "واحدة",
    "فكره": "فكرة",
    "مشكله": "مشكلة",
    "طريقه": "طريقة",
    "نتيجه": "نتيجة",
    "خطوه": "خطوة",
    "اللي": "اللي",
    "اسفل": "أسفل",
    "والاقوى": "والأقوى",
    "الاقوى": "الأقوى",
    "والخاصيه": "والخاصية",
    "بالنسبه": "بالنسبة",
    "تليفون": "تيليفون",
    "تليفونك": "تيليفونك",
    "افضل": "أفضل",
    "اقل": "أقل",
    "اكثر": "أكثر",
    "انه": "أنه",
    "اما": "أما",
    "اي": "أي",
}

PHRASE_LEVEL_FIXES = [
    (r"وبالـ\s*AI\s+أي\b", "وبالـ AI"),
    (r"وبالاي\s+أي\b", "وبالـ AI"),
    (r"وبالاي\s+اي\b", "وبالـ AI"),
    (r"فيديو\s+ايديتين\b", "فيديو إيديتينغ"),
    (r"باش\s+تنوضي\s+لي\s+فيديو\s+واش\s+ترفعهم", "باش تمونتي الفيديوهات وترفعهم"),
    (r"باش\s+يمونتي\s+فيديو\s+الحساب\s+تاعك", "باش تمونتي الفيديوهات وترفعهم في حسابك"),
    (r"من\s+مشكل\s+وما\s+عندكش\s+الوقت", "من مشكل الوقت وما عندكش الوقت"),
    (r"عموما\s+يموتوا\s+وانت\s+ما\s+على(?!\s+بالكش)", "عموماً يموتوا وأنت ما على بالكش"),
    (r"منصة\s+مع\s+فيديو\s+تقدر\s+تمنطي", "منصة فيديو إيديتينغ تقدر تمونتي"),
    (r"منصة\s+مع\s+فيديو\s+تقدر\s+تمونتي", "منصة فيديو إيديتينغ تقدر تمونتي"),
    (r"المونتاج\s+العادي\s+قص\s+تع\b", "والمونتاج العادي وقص وتعديل"),
    (r"قص\s+تع\b", "وقص وتعديل"),
    (r"الصمت\s+من\s+وهذا\b", "ينحي الصمت من الفيديو مجاناً بالذكاء الاصطناعي"),
    (r"بشكل\s+مج\s+التسجيل", "بشكل مجاني ورابط التسجيل"),
    (r"بشكل\s+مج\b", "بشكل مجاني"),
    (r"باش\s+تنوضي\s+لي\s+فيديو", "باش تمونتي الفيديوهات"),
    (r"باش\s+ينوضي\s+لي\s+فيديو", "باش يمونتي الفيديوهات"),
    (r"تنوضي\s+لي\s+فيديو", "يمونتي الفيديوهات"),
    (r"ينوضي\s+لي\s+فيديو", "يمونتي الفيديوهات"),
    (r"سيرفر\s+تيليفون", "سيبور تيليفون"),
    (r"قطع[،,]?\s+يتقطع", "قاع يتقطع"),
    (r"المتوفرس\s+على", "راه متوفر"),
    (r"أكموان\s+من", "اكموندي من"),
    (r"حتى\s+تديهم\s+بالبري\s+مهب", "تديهم باطل"),
    (r"تديهم\s+بالبري\s+مهب", "تديهم باطل"),
    (r"بالبري\s+مهب", "باطل"),
    (r"تتفرج\s+وتم\s+والخاصي", "تتفرج والخاصي"),
    (r"والاقوى\s+ما\s+انت\s+اي", "والأقوى من هذا أي"),
    (r"والأقوى\s+ما\s+أنت\s+أي", "والأقوى من هذا أي"),
    (r"والاقوى\s+ما\s+انت", "والأقوى من هذا"),
    (r"والأقوى\s+ما\s+أنت", "والأقوى من هذا"),
    (r"بالسوبر\s+فاستا", "بالسوبر فاست"),
    (r"سوبر\s+فاستا", "سوبر فاست"),
    (r"ترفع\s+الإنتاجية\s+التواصل\s+الاجتماعي", "ترفع الإنتاجية في التواصل الاجتماعي"),
    (r"ترفع\s+الانتاجية\s+التواصل\s+الاجتماعي", "ترفع الإنتاجية في التواصل الاجتماعي"),
    (r"منصة\s+فيديو\s+المسؤولة", "منصة فيديوهات المسؤولة"),
    (r"منصة\s+اسمها\s+فيديو\s+تاع", "منصة اسمها فيديوهات"),
    (r"فيديو\s+تاع\s+المسؤولة", "فيديوهات المسؤولة"),
    (r"ترفع\s+ان\s+ترفع", "ترفع"),
    (r"ترفع\s+أن\s+ترفع", "ترفع"),
    (r"لاحظت\s+ان\s+في", "لاحظت أن في"),
    (r"عندها\s+مش\s+في", "عندها مشكل في"),
    (r"عنده\s+مش\s+في", "عنده مشكل في"),
    (r"ما\s+عندها\s+مش\s+في", "ما عندها مشكل في"),
    (r"في\s+المونتاج\s+للرز", "في المونتاج للريلز"),
    (r"في\s+المونتاج\s+للريز", "في المونتاج للريلز"),
    (r"تصور\s+لي\s+الفيديوهات", "تصور الفيديوهات"),
]

CONTEXTUAL_BROKEN_WORD_REPAIRS = [
    (r"(?<!\w)في\s+المونت(?!\w)", "في المونتاج"),
    (r"(?<!\w)المونت\s+الان(?!\w)", "المونتاج لأن"),
    (r"(?<!\w)المونت(?!\w)", "المونتاج"),
    (r"(?<!\w)الان\s+أغلب\s+الناس(?!\w)", "لأن أغلب الناس"),
    (r"(?<!\w)الان\s+اغلب\s+الناس(?!\w)", "لأن أغلب الناس"),
    (r"(?<!\w)تصور\s+للفيديوهات(?!\w)", "تصور الفيديوهات"),
    (r"(?<!\w)تصور\s+لي\s+الفيديوهات(?!\w)", "تصور الفيديوهات"),
    (r"(?<!\w)عندها\s+مش\s+في(?!\w)", "عندها مشكل في"),
    (r"(?<!\w)مش\s+في\s+المونتاج(?!\w)", "مشكل في المونتاج"),
    (r"(?<!\w)للرز(?!\w)", "للريلز"),
    (r"(?<!\w)للريز(?!\w)", "للريلز"),
    (r"(?<!\w)التواصل\s+الاج(?!\w)", "التواصل الاجتماعي"),
    (r"(?<!\w)مواقع\s+التواصل\s+الاج(?!\w)", "مواقع التواصل الاجتماعي"),
    (r"(?<!\w)الاج(?!\w)", "الاجتماعي"),
    (r"(?<!\w)المسؤوله\s+على\s+اللي(?!\w)", "المسؤولة على المونتاج"),
    (r"(?<!\w)صورته\s+ذكاء\s+الاصطناعي(?!\w)", "صوت وصورة بالذكاء الاصطناعي"),
    (r"(?<!\w)منت\s+الفيديو(?!\w)", "تمنتج الفيديو"),
    (r"(?<!\w)ومونتاج\s+احت\s+ولا(?!\w)", "ومونتاج احترافي"),
    (r"(?<!\w)ومونتاج\s+احت(?!\w)", "ومونتاج احترافي"),
    (r"(?<!\w)مونتاج\s+احت(?!\w)", "مونتاج احترافي"),
    (r"(?<!أقل\s)(?<!اقل\s)(?<!\w)من\s+دقيقه(?!\w)", "أقل من دقيقة"),
    (r"(?<!\w)قص\s+تعديل\s+الفيديو(?!\w)", "قص وتعديل الفيديو"),
]

SINGLE_TRUNCATED_TOKEN_MAP = {
    "تنوضي": "يمونتي",
    "ينوضي": "يمونتي",
    "نوضي": "يمونتي",
    "المونت": "المونتاج",
    "الاج": "الاجتماعي",
    "منت": "تمنتج",
    "احت": "احترافي",
    "الانتاجيه": "الإنتاجية",
    "المسؤوله": "المسؤولة",
    "دقيقه": "دقيقة",
    "للفيديوهات": "الفيديوهات",
    "الخاصيه": "الخاصية",
    "للخاصيه": "للخاصية",
    "الاولى": "الأولى",
    "الثانيه": "الثانية",
    "الثالثه": "الثالثة",
    "فاستا": "فاست",
    "اقل": "أقل",
    "افضل": "أفضل",
    "اسفل": "أسفل",
    "والاقوى": "والأقوى",
    "الاقوى": "الأقوى",
    "والخاصيه": "والخاصية",
    "بالنسبه": "بالنسبة",
    "تليفون": "تيليفون",
    "تليفونك": "تيليفونك",
}


def _orthographic_skeleton(word: str) -> str:
    w = re.sub(r"[،,.!؟?:؛\-]", "", str(word)).strip().lower()
    for ch in "أإآ":
        w = w.replace(ch, "ا")
    w = w.replace("ة", "ه").replace("ى", "ي")
    return w


def repair_truncated_words_and_sentences(words_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    محرك عام لإصلاح الكلمات المبتورة، توحيد الإملاء العربي، إزالة الحشو الناتج عن أخطاء التعرف الصوتي،
    ومنع تكرار الكلمات المتجاورة أو العبارات المكسورة.
    """
    if not words_list:
        return []
    repaired = [dict(w) for w in words_list]
    n = len(repaired)
    for i, w_obj in enumerate(repaired):
        raw_w = str(w_obj.get("word", "")).strip()
        clean_w = raw_w.strip("،,.!؟?")
        if clean_w in {"للرز", "للريز", "لريز"}:
            repaired[i]["word"] = "للريلز"
            clean_w = "للريلز"
        if clean_w in {"تنوضي", "ينوضي", "نوضي"}:
            repaired[i]["word"] = "يمونتي"
            clean_w = "يمونتي"
        if clean_w == "مش" and i + 1 < n:
            nxt_w_check = str(repaired[i + 1].get("word", "")).strip("،,.!؟?")
            prev_w_check = str(repaired[i - 1].get("word", "")).strip("،,.!؟?") if i > 0 else ""
            if nxt_w_check == "في" or prev_w_check in {"عندها", "عنده"}:
                repaired[i]["word"] = "مشكل"
                clean_w = "مشكل"
        if clean_w == "لي" and i > 0 and i + 1 < n:
            prev_w_check = str(repaired[i - 1].get("word", "")).strip("،,.!؟?")
            nxt_w_check = str(repaired[i + 1].get("word", "")).strip("،,.!؟?")
            if prev_w_check in {"تصور", "يصور", "يمونتي", "تمنتج", "تنوضي", "ينوضي"} and "فيديو" in nxt_w_check:
                repaired[i]["word"] = ""
                clean_w = ""
        if clean_w in SINGLE_TRUNCATED_TOKEN_MAP:
            repaired[i]["word"] = SINGLE_TRUNCATED_TOKEN_MAP[clean_w]
            clean_w = repaired[i]["word"]

        if clean_w in {"الان", "الآن"} and i + 1 < n:
            nxt_w = str(repaired[i + 1].get("word", "")).strip("،,.!؟?")
            if nxt_w in {"أغلب", "اغلب", "كثير", "بزاف", "الناس"}:
                repaired[i]["word"] = "لأن"
        if clean_w in {"صورته", "صورتك"} and i + 1 < n:
            nxt_w = str(repaired[i + 1].get("word", "")).strip("،,.!؟?")
            if "ذكاء" in nxt_w or "اصطناعي" in nxt_w:
                repaired[i]["word"] = "صوت وصورة"
        if clean_w == "ولا" and i > 0:
            prev_w = str(repaired[i - 1].get("word", "")).strip("،,.!؟?")
            if prev_w == "احترافي":
                repaired[i]["word"] = ""
        if clean_w == "وتم" and i + 1 < n:
            nxt_w = _orthographic_skeleton(repaired[i + 1].get("word", ""))
            if "خاصي" in nxt_w or "ثاني" in nxt_w or "ثالث" in nxt_w:
                repaired[i]["word"] = ""
        if clean_w in {"ان", "أن"} and 0 < i < n - 1:
            prev_s = _orthographic_skeleton(repaired[i - 1].get("word", ""))
            next_s = _orthographic_skeleton(repaired[i + 1].get("word", ""))
            if prev_s == next_s and prev_s:
                repaired[i]["word"] = ""
                repaired[i + 1]["word"] = ""
        if clean_w in {"ما"} and i > 0 and i + 1 < n:
            prev_s = _orthographic_skeleton(repaired[i - 1].get("word", ""))
            next_s = _orthographic_skeleton(repaired[i + 1].get("word", ""))
            if "اقوي" in prev_s and next_s in {"انت", "انك"}:
                repaired[i]["word"] = "من"
                repaired[i + 1]["word"] = "هذا"
        if clean_w == "بالبري" and i + 1 < n:
            next_s = _orthographic_skeleton(repaired[i + 1].get("word", ""))
            if next_s in {"مهب", "باطل"}:
                repaired[i]["word"] = "باطل"
                repaired[i + 1]["word"] = ""
                if i >= 2 and _orthographic_skeleton(repaired[i - 2].get("word", "")) == "حتي":
                    repaired[i - 2]["word"] = ""
        if _orthographic_skeleton(clean_w) in {"الانتاجيه", "انتاجيه"} and i + 1 < n:
            next_s = _orthographic_skeleton(repaired[i + 1].get("word", ""))
            if next_s == "التواصل":
                repaired[i]["word"] = "الإنتاجية في"

    non_empty = [w for w in repaired if str(w.get("word", "")).strip()]
    deduped = []
    for w in non_empty:
        w_skel = _orthographic_skeleton(w["word"])
        if deduped:
            prev_skel = _orthographic_skeleton(deduped[-1]["word"])
            if w_skel and w_skel == prev_skel and w_skel not in {"اصبر", "شوف", "لا", "نعم", "صح"}:
                if any(ch in w["word"] for ch in "أإآة") and not any(ch in deduped[-1]["word"] for ch in "أإآة"):
                    deduped[-1]["word"] = w["word"]
                deduped[-1]["end"] = max(float(deduped[-1]["end"]), float(w["end"]))
                continue
        deduped.append(w)

    return deduped


# ==============================================================================
# 1.8 كشف وإزالة أخطاء وإعادات التعليق الصوتي + إعادة حساب التوقيت بعد القص
# ==============================================================================
_LAST_DETECTED_RETAKE_CUTS: List[Dict[str, Any]] = []


def get_last_detected_retake_cuts() -> List[Dict[str, Any]]:
    return [dict(c) for c in _LAST_DETECTED_RETAKE_CUTS]


def _stem_skeleton(word: str) -> str:
    s = _orthographic_skeleton(word)
    for pref in ("وال", "بال", "فل", "كال", "لل", "ال", "و", "ب", "ف", "ل"):
        if s.startswith(pref) and len(s) - len(pref) >= 3:
            s = s[len(pref):]
            break
    return s


def _words_are_equivalent(w1: str, w2: str) -> bool:
    s1, s2 = _orthographic_skeleton(w1), _orthographic_skeleton(w2)
    if not s1 or not s2:
        return False
    if s1 == s2:
        return True
    st1, st2 = _stem_skeleton(w1), _stem_skeleton(w2)
    if st1 == st2 and len(st1) >= 2:
        return True
    if min(len(st1), len(st2)) >= 4:
        ratio = difflib.SequenceMatcher(None, st1, st2).ratio()
        if ratio >= 0.78:
            return True
    return False


def _phrase_similarity(seq1: List[str], seq2: List[str]) -> float:
    if not seq1 or not seq2:
        return 0.0
    m = min(len(seq1), len(seq2))
    matches = sum(1 for a, b in zip(seq1[:m], seq2[:m]) if _words_are_equivalent(a, b))
    return matches / float(max(len(seq1), len(seq2)))


def detect_and_remove_voiceover_retakes(
    words_list: List[Dict[str, Any]],
    remap_timestamps: bool = False
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    global _LAST_DETECTED_RETAKE_CUTS
    _LAST_DETECTED_RETAKE_CUTS = []

    if not words_list or len(words_list) < 2:
        return list(words_list), []

    items = [dict(w) for w in words_list if str(w.get("word", "")).strip()]
    n = len(items)
    keep_mask = [True] * n
    detected_cuts: List[Dict[str, Any]] = []

    i = 0
    while i < n - 1:
        if not keep_mask[i]:
            i += 1
            continue

        cut_made = False
        for j in range(i + 1, min(n, i + 10)):
            if not keep_mask[j]:
                continue
            span_len = j - i
            time_span = float(items[j]["start"]) - float(items[i]["start"])
            if time_span > 7.5:
                break

            check_len = min(span_len, n - j)
            if check_len >= 2 and _words_are_equivalent(items[i]["word"], items[j]["word"]):
                seq_a = [items[k]["word"] for k in range(i, i + check_len)]
                seq_b = [items[k]["word"] for k in range(j, j + check_len)]
                sim = _phrase_similarity(seq_a, seq_b)
                if sim >= 0.80 and span_len <= check_len + 2:
                    cut_s = float(items[i]["start"])
                    cut_e = float(items[j]["start"])
                    removed_str = " ".join(items[k]["word"] for k in range(i, j))
                    for k in range(i, j):
                        keep_mask[k] = False
                    detected_cuts.append({
                        "start": round(cut_s, 3),
                        "end": round(max(cut_s + 0.08, cut_e), 3),
                        "removed_text": removed_str,
                        "reason": "phrase_retake"
                    })
                    i = j
                    cut_made = True
                    break

            _common_particles = {"تاعك", "تاعي", "قاع", "كاع", "ولا", "باش", "وباش", "في", "من", "على", "مع", "لي", "اللي", "هذا", "هاذ", "ما", "بلي", "وراك", "راك"}
            if 3 <= span_len <= 6 and (j + 3) <= n:
                w_i0 = items[i]["word"].strip("،,.!؟?")
                w_i1 = items[i + 1]["word"].strip("،,.!؟?")
                w_i2 = items[i + 2]["word"].strip("،,.!؟?")
                prefix_match_3 = (
                    w_i0 not in _common_particles
                    and w_i1 not in _common_particles
                    and _words_are_equivalent(w_i0, items[j]["word"])
                    and _words_are_equivalent(w_i1, items[j + 1]["word"])
                    and _words_are_equivalent(w_i2, items[j + 2]["word"])
                )
                if prefix_match_3:
                    cut_idx_start = i
                    cut_s = float(items[cut_idx_start]["start"])
                    cut_e = float(items[j]["start"])
                    removed_str = " ".join(items[k]["word"] for k in range(cut_idx_start, j))
                    for k in range(cut_idx_start, j):
                        keep_mask[k] = False
                    detected_cuts.append({
                        "start": round(cut_s, 3),
                        "end": round(max(cut_s + 0.08, cut_e), 3),
                        "removed_text": removed_str,
                        "reason": "false_start_sentence_retake"
                    })
                    i = j
                    cut_made = True
                    break

        if cut_made:
            continue

        nxt_i = i + 1
        while nxt_i < n and not keep_mask[nxt_i]:
            nxt_i += 1
        if nxt_i < n:
            w_curr = items[i]["word"]
            w_next = items[nxt_i]["word"]
            skel_curr = _orthographic_skeleton(w_curr)
            if _words_are_equivalent(w_curr, w_next) and skel_curr not in {"اصبر", "شوف", "لا", "نعم", "صح", "خطوه"}:
                cut_s = float(items[i]["start"])
                cut_e = float(items[nxt_i]["start"])
                keep_mask[i] = False
                detected_cuts.append({
                    "start": round(cut_s, 3),
                    "end": round(max(cut_s + 0.06, cut_e), 3),
                    "removed_text": w_curr,
                    "reason": "word_stutter"
                })
                i = nxt_i
                continue

        i += 1

    cleaned_words = [w for idx_w, w in enumerate(items) if keep_mask[idx_w]]
    _LAST_DETECTED_RETAKE_CUTS = detected_cuts

    if remap_timestamps and detected_cuts:
        cleaned_words = remap_words_after_retake_cuts(cleaned_words, detected_cuts)

    if detected_cuts:
        logger.info(f"Voiceover Retake Detector removed {len(detected_cuts)} mistake/retake segment(s): {detected_cuts}")

    return cleaned_words, detected_cuts


def recalculate_word_timestamps_after_cuts(
    words_list: List[Dict[str, Any]],
    kept_speech_intervals: Optional[List[Tuple[float, float]]] = None,
    removed_silence_or_retake_cuts: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    إعادة حساب كافة الـ Timestamps للكلمات (`start`, `end`) بدقة الملي ثانية بعد عملية قص الصمت (`> 0.25s`)
    أو قص الإعادات الخاطئة، بحيث تبقى الكلمات والرسومات متزامنة 100% مع الصوت الجديد المقصوص.
    - إذا تم تمرير `kept_speech_intervals` (فترات الكلام المحتفظ بها بعد قص الصمت > 0.25s)، يتم إسقاط كل كلمة
      من الزمن الأصلي إلى الزمن الجديد المتراكم.
    - إذا تم تمرير `removed_silence_or_retake_cuts` (الفترات المحذوفة)، يتم طرح مدة كل فترة محذوفة سابقة.
    """
    if not words_list:
        return []

    out_words = [dict(w) for w in words_list]

    # 1. الإسقاط عبر فترات الكلام المحتفظ بها (Jump-Cut Interval Remapping)
    if kept_speech_intervals:
        valid_intervals = [(float(s), float(e)) for s, e in kept_speech_intervals if float(e) > float(s)]
        if valid_intervals:
            cum_starts: List[float] = []
            acc = 0.0
            for s, e in valid_intervals:
                cum_starts.append(acc)
                acc += (e - s)

            def _map_orig_to_cut_time(t_orig: float) -> float:
                for idx_iv, (iv_s, iv_e) in enumerate(valid_intervals):
                    if t_orig < iv_s:
                        return cum_starts[idx_iv]
                    if iv_s <= t_orig <= iv_e:
                        return cum_starts[idx_iv] + (t_orig - iv_s)
                return acc

            for w in out_words:
                orig_s = float(w.get("start", 0.0))
                orig_e = float(w.get("end", orig_s + 0.22))
                orig_dur = max(0.08, orig_e - orig_s)
                new_s = _map_orig_to_cut_time(orig_s)
                new_e = _map_orig_to_cut_time(orig_e)
                if new_e <= new_s + 0.06:
                    new_e = new_s + min(0.28, orig_dur)
                w["start"] = round(max(0.0, new_s), 3)
                w["end"] = round(max(w["start"] + 0.08, new_e), 3)

    # 2. طرح أي فترات محذوفة إضافية (Retake / Silence Cuts Subtraction)
    if removed_silence_or_retake_cuts:
        cuts = sorted(
            [
                (float(c["start"]), float(c["end"]))
                for c in removed_silence_or_retake_cuts
                if float(c.get("end", 0.0)) > float(c.get("start", 0.0))
            ],
            key=lambda x: x[0]
        )
        for w in out_words:
            ws = float(w.get("start", 0.0))
            we = float(w.get("end", ws + 0.22))
            shift = 0.0
            for cs, ce in cuts:
                if ce <= ws + 0.02:
                    shift += (ce - cs)
                elif cs < ws < ce:
                    shift += (ws - cs)
            new_s = max(0.0, round(ws - shift, 3))
            new_e = max(new_s + 0.08, round(we - shift, 3))
            w["start"] = new_s
            w["end"] = new_e

    return ensure_word_timestamp_continuity(out_words)


def remap_words_after_retake_cuts(
    words_list: List[Dict[str, Any]],
    retake_cuts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    return recalculate_word_timestamps_after_cuts(
        words_list=words_list,
        removed_silence_or_retake_cuts=retake_cuts
    )


_TRANSCRIPTION_CACHE: Dict[str, Dict[str, Any]] = {}
_WHISPER_MODEL_CACHE: Dict[str, Any] = {}

_CUSTOM_CAPTION_OVERRIDE: Dict[str, Any] = {
    "enabled": False,
    "words": [],
    "sentences": []
}
_LAST_EXTRACTED_TRANSCRIPT: Dict[str, List[Dict[str, Any]]] = {
    "words": [],
    "sentences": []
}


# ==============================================================================
# 2. تقسيم الكلمات إلى مشاهد دلالية سياقية سريعة (Alex Hormozi Fast-Paced Scenes)
# ==============================================================================
def ensure_word_timestamp_continuity(
    words_list: List[Dict[str, Any]],
    total_duration: Optional[float] = None
) -> List[Dict[str, Any]]:
    """ضمان اتصال التوقيت الزمني بين الكلمات بدقة الملي ثانية لمنع اختفاء الكابشن أو القفز الخاطئ."""
    if not words_list:
        return []

    smoothed: List[Dict[str, Any]] = [dict(w) for w in words_list]
    for i in range(len(smoothed)):
        w_s = float(smoothed[i].get("start", 0.0))
        w_e = float(smoothed[i].get("end", w_s + 0.24))
        if w_e <= w_s + 0.07:
            w_e = w_s + 0.20

        if i + 1 < len(smoothed):
            next_s = float(smoothed[i + 1].get("start", w_e))
            gap = next_s - w_e
            if 0.0 <= gap <= 0.35:
                w_e = next_s
            elif gap < 0.0:
                w_e = max(w_s + 0.07, next_s)
        elif total_duration is not None:
            if 0.0 < total_duration - w_e <= 0.40:
                w_e = total_duration

        smoothed[i]["start"] = round(w_s, 3)
        smoothed[i]["end"] = round(w_e, 3)

    return smoothed


def distribute_text_into_word_timestamps(
    text: str,
    start_sec: float,
    end_sec: float,
    existing_words: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    تحويل أي جملة نصية معدلة يدوياً (مثل تحويل "ينوضي" إلى "يمونتي") إلى قائمة كلمات `words`
    تحتوي على `word`, `start`, `end`, `probability` موزعة بدقة داخل `[start_sec, end_sec]`.
    """
    tokens = [t.strip() for t in str(text or "").split() if t.strip()]
    s_t = round(float(start_sec), 3)
    e_t = round(max(s_t + 0.25, float(end_sec)), 3)
    if not tokens:
        return []

    if existing_words and len(existing_words) == len(tokens):
        out = []
        for tok, old_w in zip(tokens, existing_words):
            ws = round(float(old_w.get("start", s_t)), 3)
            we = round(max(ws + 0.08, float(old_w.get("end", e_t))), 3)
            out.append({"word": tok, "start": ws, "end": we, "probability": 1.0})
        return ensure_word_timestamp_continuity(out, total_duration=e_t)

    weights = [max(2.0, float(len(tok)) ** 0.85) for tok in tokens]
    total_w = sum(weights)
    dur = max(0.20, e_t - s_t)
    cursor = s_t
    out = []
    for idx, (tok, w_val) in enumerate(zip(tokens, weights)):
        w_dur = dur * (w_val / total_w)
        w_end = e_t if idx == len(tokens) - 1 else round(cursor + w_dur, 3)
        out.append({
            "word": tok,
            "start": round(cursor, 3),
            "end": max(round(cursor + 0.07, 3), w_end),
            "probability": 1.0
        })
        cursor = w_end
    return ensure_word_timestamp_continuity(out, total_duration=e_t)


def sync_live_scene_edits_to_words(
    planned_scenes: List[Dict[str, Any]],
    base_words: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    الجسر التفاعلي ثنائي الاتجاه (Two-Way Live Scene & Caption Override Bus):
    عندما يعدل المستخدم في أسفل الموقع (`app.py`):
    1. عنوان المشهد `concept_title` أو النص المنطوق `text` (مثلاً تعديل "ينوضي" إلى "يمونتي"):
       - يتم تحديث نص المشهد ومصفوفة الكلمات `sc["words"]` و `sc["word_strings"]` فوراً بتوقيت دقيق.
    2. الكلمات المفتاحية `kpi_value` (مثلاً كتابة "يمنتج مونتاج") أو العناصر الفرعية `sub_items` (مثلاً "ما عنده وقت | عشان يمنتج"):
       - يعيد المحرك مطابقة الرسمة التعبيرية (`match_speech_to_visual_archetype`) بناءً على الكلمات المفتاحية الجديدة
         والعناصر الفرعية الجديدة حتى تتغير الرسمة فعلياً لتطابق ما كتبه المستخدم!
    3. يحفظ الكلمات المحدثة في `_CUSTOM_CAPTION_OVERRIDE` و `_LAST_EXTRACTED_TRANSCRIPT` لمنع عودة الكلمات القديمة أبداً.
    """
    if not planned_scenes:
        return [], []

    try:
        from style_evolution_brain import match_speech_to_visual_archetype, ALL_DYNAMIC_VISUAL_ARCHETYPES
    except Exception:
        match_speech_to_visual_archetype = None
        ALL_DYNAMIC_VISUAL_ARCHETYPES = []

    synced_scenes: List[Dict[str, Any]] = []
    all_synced_words: List[Dict[str, Any]] = []
    used_archs: List[str] = []
    total_sc = len(planned_scenes)

    for idx, sc in enumerate(planned_scenes):
        sc_copy = dict(sc)
        s_start = float(sc_copy.get("start", idx * 2.5))
        s_end = float(sc_copy.get("end", s_start + 2.5))

        orig_text = str(sc_copy.get("text", "")).strip()
        edited_title = str(sc_copy.get("concept_title") or sc_copy.get("short_title") or "").strip()
        edited_kpi = str(sc_copy.get("kpi_value", "")).strip()
        edited_badge = str(sc_copy.get("badge_label", "")).strip()
        sub_items = [str(x).strip() for x in (sc_copy.get("sub_items") or []) if str(x).strip()]

        # إذا عدل المستخدم الكلمة الخاطئة في العنوان البارز أو في النص (مثلاً غير "تنوضي/ينوضي" إلى "يمونتي")
        # نقوم بتطبيق التعديل على النص المنطوق والكلمات أيضاً!
        effective_speech_text = orig_text
        if edited_title and orig_text:
            orig_tokens = orig_text.split()
            title_tokens = edited_title.split()
            # إذا كان العنوان المعدل يغطي معظم جملة المشهد أو صحح كلمة فيها (مثل باش تنوضي لي فيديو -> باش يمونتي لي فيديو)
            if len(title_tokens) >= max(2, len(orig_tokens) - 2):
                if len(orig_tokens) > len(title_tokens):
                    # نحتفظ ببقية كلمات الجملة الأصلية التي لم تكن ضمن العنوان المختصر مع استبدال الجزء المعدل
                    tail_tokens = orig_tokens[len(title_tokens):]
                    effective_speech_text = " ".join(title_tokens + tail_tokens)
                else:
                    effective_speech_text = edited_title
            else:
                # استبدال ذكي لأي كلمة متشابهة إملائياً (مثل تنوضي/ينوضي -> يمونتي)
                updated_orig = list(orig_tokens)
                for t_tok in title_tokens:
                    for oi, o_tok in enumerate(updated_orig):
                        sim = difflib.SequenceMatcher(None, _orthographic_skeleton(t_tok), _orthographic_skeleton(o_tok)).ratio()
                        if 0.45 <= sim < 1.0 or (o_tok in {"تنوضي", "ينوضي", "نوضي"} and t_tok in {"يمونتي", "تمنتج", "يمونطي"}):
                            updated_orig[oi] = t_tok
                effective_speech_text = " ".join(updated_orig)
        elif edited_title and not orig_text:
            effective_speech_text = edited_title

        sc_copy["text"] = effective_speech_text
        if edited_title:
            sc_copy["concept_title"] = edited_title
            sc_copy["short_title"] = edited_title

        # إعادة بناء مصفوفة الكلمات والتوقيت الزمني للمشهد بحيث تظهر الكلمات المعدلة في الكابشن والموشن جرافيك
        rebuilt_words = distribute_text_into_word_timestamps(
            text=effective_speech_text,
            start_sec=s_start,
            end_sec=s_end,
            existing_words=sc_copy.get("words") if isinstance(sc_copy.get("words"), list) else None
        )
        sc_copy["words"] = rebuilt_words
        sc_copy["word_strings"] = [w["word"] for w in rebuilt_words]
        all_synced_words.extend(rebuilt_words)

        # إذا أدخل المستخدم كلمات مفتاحية جديدة في `kpi_value` (مثل "يمنتج مونتاج") أو عدل `sub_items` ("ما عنده وقت | عشان يمنتج")
        # ندمج هذه الكلمات المفتاحية في استعلام مطابقة الرسمة البصرية حتى تتغير الرسمة لتوافق تعديله 100%!
        combined_semantic_signal = " ".join(
            part for part in [
                edited_kpi,
                " ".join(sub_items),
                edited_title,
                effective_speech_text,
                edited_badge
            ] if part
        ).strip()
        sc_copy["search_keywords_override"] = combined_semantic_signal

        if callable(match_speech_to_visual_archetype) and combined_semantic_signal:
            # إذا كتب المستخدم كلمات مفتاحية صريحة (مثل "يمنتج مونتاج" أو "ما عنده وقت | عشان يمنتج")،
            # نتحقق مما إذا كانت الكلمات الجديدة تستدعي رسمة أدق من الرسمة القديمة المعلقة
            matched_arch, matched_subj = match_speech_to_visual_archetype(
                scene_text=combined_semantic_signal,
                scene_index=idx,
                total_scenes=total_sc,
                used_archetypes=used_archs,
                variation_seed=idx * 19
            )
            cur_arch = str(sc_copy.get("user_override_archetype") or sc_copy.get("archetype") or "")
            # إذا كان المستخدم قد كتب كلمات مفتاحية جديدة في kpi_value أو sub_items ولم يغير القائمة المنسدلة يدوياً عن قيمتها القديمة
            if edited_kpi or sub_items:
                if not sc_copy.get("_manual_arch_locked", False):
                    # إذا كانت الكلمات المفتاحية تشير بوضوح إلى مونتاج/قص/وقت/ذكاء، نعتمد الرسمة المطابقة للكلمات المفتاحية الجديدة
                    kw_low = f"{edited_kpi} {' '.join(sub_items)} {edited_title}".lower()
                    if any(k in kw_low for k in ["يمنتج", "مونتاج", "يمونتي", "قص", "تقطيع"]):
                        matched_arch = "hero_waveform_scissors" if "وقت" not in kw_low else "hero_chrono_speedometer"
                    elif any(k in kw_low for k in ["وقت", "ساعات", "دقيقة", "سريع"]):
                        matched_arch = "hero_chrono_speedometer"
                    sc_copy["archetype"] = matched_arch
                    sc_copy["user_override_archetype"] = matched_arch
                    sc_copy["visual_subject"] = matched_subj
                    if isinstance(sc_copy.get("scene_style_spec"), dict):
                        sc_copy["scene_style_spec"]["visual_archetype"] = matched_arch

        final_arch = str(sc_copy.get("archetype") or "web_dynamic_scene")
        used_archs.append(final_arch)
        synced_scenes.append(sc_copy)

    all_synced_words = ensure_word_timestamp_continuity(all_synced_words)
    _CUSTOM_CAPTION_OVERRIDE["enabled"] = True
    _CUSTOM_CAPTION_OVERRIDE["words"] = all_synced_words
    _CUSTOM_CAPTION_OVERRIDE["sentences"] = [
        {
            "text": s["text"],
            "start": s["start"],
            "end": s["end"],
            "words": s["words"]
        }
        for s in synced_scenes
    ]
    _LAST_EXTRACTED_TRANSCRIPT["words"] = all_synced_words
    _LAST_EXTRACTED_TRANSCRIPT["sentences"] = _CUSTOM_CAPTION_OVERRIDE["sentences"]

    return synced_scenes, all_synced_words


# ==============================================================================
# قواعد الحدود النحوية والدلالية الصارمة للدارجة الجزائرية والعربية (Semantic Clause Boundaries)
# تمنع قطع المشاهد بعد أي حرف جر أو أداة ربط أو مضاف أو إشارة أو نفي منعاً باتاً
# ==============================================================================
FORBIDDEN_SCENE_END_WORDS = {
    # حروف الجر والظروف المكانية/الزمانية المضافة
    "من", "في", "على", "إلى", "الى", "عن", "مع", "بين", "تحت", "فوق", "أمام", "امام",
    "وراء", "خلف", "حول", "دون", "بدون", "بلا", "عند", "لدى", "منذ", "مذ", "خلال", "عبر",
    "ضد", "نحو", "قرب", "وسط", "داخل", "خارج", "قبل", "بعد", "أسفل", "اسفل", "أعلى", "اعلى",
    # حروف الجر والربط المفردة
    "ب", "ك", "ل", "و", "ف", "بـ", "كـ", "لـ", "وـ", "فـ",
    # أدوات الإضافة والملكية بالدارجة والفصحى
    "تاع", "نتاع", "متاع", "ديال", "شغل", "جال", "سبيل",
    # أدوات الربط والتعليل والشرط والاستثناء
    "بلي", "باش", "باه", "كي", "كيما", "لأن", "لان", "لأنه", "لانه", "لأنها", "لانها",
    "أنه", "انه", "أنها", "انها", "أن", "ان", "إن", "إذ", "اذ", "إذا", "اذا", "لو", "لولا",
    "كون", "حتى", "حتي", "أو", "او", "أم", "ام", "ولا", "بل", "لكن", "لاكن", "بصح", "غير",
    "سوى", "عدا", "حاشا", "خاطر", "علاش", "كيفاش", "واش", "وش", "وين", "وقتاش", "شحال", "قداش",
    # أدوات النفي والنهي والتحقيق والاستقبال
    "ما", "وما", "لا", "لم", "لن", "ليس", "ليست", "ماشي", "مش", "موش", "قد", "سوف", "راح", "غادي",
    # أسماء الإشارة والأسماء الموصولة والضمائر المنفصلة
    "هذا", "هذه", "هاد", "هاذ", "هادي", "هاذي", "هذوك", "هادوك", "هذاك", "هداك", "ذلك", "تلك",
    "وهذا", "وهاد", "وهاذ", "وهذه",
    "الذي", "التي", "الذين", "اللي", "الي", "لي",
    "أنا", "انا", "أنت", "انت", "انتي", "وانت", "وأنت", "وإنت", "أنتما", "أنتم", "انتم", "هم", "هما", "هن", "نحن", "احنا", "هو", "هي",
    # مضافات شائعة وكلمات ناقصة دلالياً بدون ما بعدها
    "كل", "أي", "اي", "بعض", "نفس", "مثل", "شبه", "أغلب", "اغلب", "معظم", "كامل", "قاع", "كاع",
    "بزاف", "شوية", "شويا", "أكثر", "اكثر", "أقل", "اقل", "أحسن", "احسن", "أفضل", "افضل", "أول", "اول", "آخر", "اخر",
    "بشكل", "بطريقة", "بأسلوب", "فيها", "فيه", "عندي", "عندك", "عنده", "عندها", "عندنا", "عندكم", "عندهم",
    "راني", "راك", "راكي", "راه", "راهو", "راهي", "رانا", "راكم", "راهم", "كان", "كانت", "يكون", "تكون",
    "كاين", "كاينه", "ماكانش", "مكاينش",
    "اسم", "واسم", "اسمها", "اسمه", "اسمو", "منصة", "المنصة", "بالذكاء", "بذكاء", "وبالذكاء",
    "وبالاي", "بالاي", "رابط", "الرابط", "مشكل", "مشكلة", "حل", "الحل", "حساب", "الحساب", "الكونت", "كونت",
    # أفعال ناقصة أو متعدية شائعة لا يكتمل معناها بدون مفعولها المباشر
    "تقدر", "نقدر", "يقدر", "تقدرو", "نقدرو", "يقدرو", "تحب", "نحب", "يحب", "لازم", "خصك", "خصني",
    "أحاول", "احاول", "أبني", "ابني", "تعمل", "تخدم", "يمونتي", "تمونتي", "تمونطي", "يمونطي", "تمنتج", "يمنتج",
    "تنحي", "ينحي", "تنقي", "ينقي", "تبدل", "ترفع", "تطلع", "وتطلع", "وتنقي", "وتنحي", "وتمونتي", "وتمونطي",
    "ومخلي", "مخلي", "وخلا", "قاعد", "وقاعد", "عمري", "تعاني", "يعاني", "نعاني", "تعانيو", "يعانيو",
}

FORBIDDEN_SCENE_START_WORDS = {
    "بالي", "بالك", "بالكش", "لك", "لي", "لهم", "لها", "له", "لنا", "لكم", "بيك", "بيه", "بيها", "بيهم",
    "تاع", "نتاع", "متاع", "ديال", "تاعي", "تاعك", "تاعو", "تاعها", "تاعهم", "تاعنا", "تاعكم",
    "من", "في", "على", "إلى", "الى", "عن", "مع", "بلي", "باش", "باه",
    "الاصطناعي", "الإصطناعي", "ميديا", "إيديتينغ", "ايديتينغ", "جرافيك", "غرافيك", "برك", "فقط",
    "العادي", "مجاني", "مجاناً", "مجانا", "عموماً", "عموما", "الفيديو", "فيديو", "الصوت", "الصمت", "الوقت",
    "أي", "اي", "أسفل", "اسفل", "عليكم",
}

INSEPARABLE_ARABIC_BIGRAMS = {
    ("السلام", "عليكم"), ("وعليكم", "السلام"),
    ("على", "بالي"), ("على", "بالك"), ("على", "بالكش"),
    ("ما", "على"), ("وما", "على"), ("وأنت", "ما"), ("وانت", "ما"),
    ("بلي", "راك"), ("راك", "تعاني"), ("تعاني", "من"),
    ("من", "مشكل"), ("مشكل", "تاع"), ("مشكل", "الوقت"), ("تاع", "الوقت"),
    ("وما", "عندكش"), ("ما", "عندكش"), ("عندكش", "الوقت"),
    ("باش", "تمونتي"), ("باش", "تمونطي"),
    ("تمونتي", "لي"), ("تمونطي", "لي"), ("تمونتي", "لك"), ("تمونطي", "لك"),
    ("تقدر", "تمونتي"), ("تقدر", "تمونطي"),
    ("لي", "فيديو"), ("فيديو", "تاعك"),
    ("وتطلعهم", "في"), ("ترفعهم", "في"), ("في", "السوشيال"), ("السوشيال", "ميديا"), ("والسوشيال", "ميديا"),
    ("ومخلي", "الحساب"), ("ومخلي", "الكونت"), ("الحساب", "تاعك"), ("الكونت", "تاعك"),
    ("تاعك", "في"), ("في", "انستغرام"), ("في", "إنستغرام"),
    ("بلي", "كاين"), ("كاين", "منصة"), ("منصة", "اسمها"), ("اسمها", "فيديو"),
    ("فيديو", "ايديتينغ"), ("فيديو", "إيديتينغ"),
    ("بالموشن", "جرافيك"), ("وبالمونتاج", "العادي"), ("بالمونتاج", "العادي"),
    ("وتنقي", "الصوت"), ("وتنحي", "الصمت"), ("وتمونتي", "الصمت"), ("الصمت", "من"), ("من", "الفيديو"),
    ("وهذا", "بشكل"), ("بشكل", "مجاني"),
    ("وبالذكاء", "الاصطناعي"), ("بالذكاء", "الاصطناعي"), ("الاصطناعي", "برك"),
    ("وبالاي", "أي"), ("وبالاي", "اي"), ("بالاي", "أي"), ("بالاي", "اي"),
    ("رابط", "التسجيل"), ("التسجيل", "في"), ("في", "أسفل"), ("في", "اسفل"), ("أسفل", "الفيديو"), ("اسفل", "الفيديو"),
}


def _clean_arabic_token_for_boundary(w: str) -> str:
    return re.sub(r"[^\w\u0600-\u06FF]", "", str(w or "")).strip()


def can_split_between_arabic_words(prev_word_txt: str, next_word_txt: str, prev_prev_word_txt: str = "") -> bool:
    """
    تتحقق مما إذا كان الفصل بين كلمتين متتاليتين سليماً نحوياً ودلالياً،
    وتمنع الفصل بعد أي حرف جر أو أداة ربط أو مضاف أو اسم إشارة أو أداة نفي.
    """
    p_clean = _clean_arabic_token_for_boundary(prev_word_txt)
    n_clean = _clean_arabic_token_for_boundary(next_word_txt)
    pp_clean = _clean_arabic_token_for_boundary(prev_prev_word_txt)
    if not p_clean or not n_clean:
        return True
    if (p_clean, n_clean) in INSEPARABLE_ARABIC_BIGRAMS:
        return False
    # حالة نطق "وبالاي أي" (وبالـ AI) حيث "أي" هي الحرف الثاني من AI وليست أداة إضافة عربية
    if p_clean in {"أي", "اي"} and pp_clean in {"وبالاي", "بالاي"}:
        return n_clean not in FORBIDDEN_SCENE_START_WORDS
    if p_clean in FORBIDDEN_SCENE_END_WORDS:
        return False
    if len(p_clean) <= 2 and p_clean not in {"برك", "صح", "تم", "يد", "دم"}:
        return False
    if n_clean in FORBIDDEN_SCENE_START_WORDS:
        return False
    return True


def is_semantic_clause_starter(word_txt: str, prev_word_txt: str = "", prev_prev_word_txt: str = "") -> bool:
    """تحدد ما إذا كانت الكلمة تمثل بداية جملة دلالية جديدة (Semantic Clause Starter)."""
    w_clean = _clean_arabic_token_for_boundary(word_txt)
    p_clean = _clean_arabic_token_for_boundary(prev_word_txt)
    if not w_clean:
        return False
    if not can_split_between_arabic_words(prev_word_txt, word_txt, prev_prev_word_txt):
        return False
    if w_clean in {"رابط", "الرابط", "التسجيل"} and p_clean not in {"رابط", "الرابط", "من", "في", "على", "مع"}:
        return True
    if w_clean in {
        "وما", "ولكن", "لكن", "بصح", "باش", "لأن", "لان", "خاطر", "علاش", "كيفاش",
        "ومخلي", "وخلا", "وأنت", "وانت", "وإنت", "تقدر", "نقدر", "يقدر",
        "وبالمونتاج", "وتنحي", "وتمونتي", "وتمونطي", "وبالذكاء", "وبالاي",
        "سجل", "ادخل", "اطلب", "اكموندي"
    }:
        return True
    return False


def split_words_into_micro_scenes(
    words_list: List[Dict[str, Any]],
    max_words_per_scene: int = 10,
    max_duration_per_scene: float = 4.5,
    min_words_per_scene: int = 3
) -> List[Dict[str, Any]]:
    """
    تقسيم الكلمات إلى مشاهد على حدود الجمل الدلالية المكتملة (Semantic Clauses) وعند الوقفات الصوتية الطبيعية فقط،
    مع منع القطع منعاً باتاً بعد أي حرف جر أو أداة ربط أو مضاف أو اسم إشارة أو نفي.
    """
    if not words_list:
        return []

    eff_max_words = max(8, min(14, int(max_words_per_scene) if int(max_words_per_scene) >= 8 else 10))
    eff_max_dur = max(3.6, min(6.0, float(max_duration_per_scene) if float(max_duration_per_scene) >= 3.5 else 4.5))
    eff_min_words = max(2, min(5, int(min_words_per_scene)))

    # حفظ الفجوات الصوتية الأصلية قبل تنعيم التوقيت لاستخدامها في كشف الوقفات الصوتية الحقيقية
    orig_gaps: List[float] = [0.0] * len(words_list)
    for i in range(1, len(words_list)):
        g = float(words_list[i].get("start", 0.0)) - float(words_list[i - 1].get("end", 0.0))
        orig_gaps[i] = max(0.0, g)

    words_list = ensure_word_timestamp_continuity(words_list)
    raw_scenes: List[Dict[str, Any]] = []
    current_group: List[Dict[str, Any]] = []

    for idx, w in enumerate(words_list):
        w_txt = str(w.get("word", "")).strip()
        if not w_txt:
            continue
        w_clean = _clean_arabic_token_for_boundary(w_txt)

        if current_group:
            grp_start = float(current_group[0]["start"])
            prev_end = float(current_group[-1]["end"])
            grp_dur = prev_end - grp_start
            prev_word_txt = str(current_group[-1]["word"]).strip()
            pp_word_txt = str(current_group[-2]["word"]).strip() if len(current_group) >= 2 else ""
            natural_gap = orig_gaps[idx] if idx < len(orig_gaps) else max(0.0, float(w["start"]) - prev_end)

            syntactically_safe = can_split_between_arabic_words(prev_word_txt, w_txt, pp_word_txt)
            ends_with_strong_punct = any(prev_word_txt.endswith(p) for p in [".", "!", "؟", "?"])
            ends_with_comma = any(prev_word_txt.endswith(p) for p in ["،", ",", ";", "؛"])
            clause_starter = is_semantic_clause_starter(w_txt, prev_word_txt, pp_word_txt)
            is_cta_start = (
                w_clean in {"رابط", "الرابط", "التسجيل"}
                and _clean_arabic_token_for_boundary(prev_word_txt) not in {"رابط", "الرابط", "من", "في", "على", "مع"}
            )

            should_split = False
            if syntactically_safe:
                if natural_gap >= 0.30 and len(current_group) >= 2:
                    should_split = True
                elif ends_with_strong_punct and len(current_group) >= 2:
                    should_split = True
                elif ends_with_comma and len(current_group) >= eff_min_words and grp_dur >= 1.4:
                    should_split = True
                elif is_cta_start and len(current_group) >= 2:
                    should_split = True
                elif clause_starter and (len(current_group) >= eff_min_words or grp_dur >= 1.5):
                    should_split = True
                elif (len(current_group) >= eff_max_words or grp_dur >= eff_max_dur):
                    should_split = True
            elif len(current_group) >= 15 or grp_dur >= 6.5:
                should_split = True

            if should_split:
                raw_scenes.append({
                    "text": " ".join(x["word"] for x in current_group),
                    "start": round(float(current_group[0]["start"]), 3),
                    "end": round(float(current_group[-1]["end"]), 3),
                    "words": list(current_group)
                })
                current_group = []

        current_group.append(dict(w))

    if current_group:
        raw_scenes.append({
            "text": " ".join(x["word"] for x in current_group),
            "start": round(float(current_group[0]["start"]), 3),
            "end": round(float(current_group[-1]["end"]), 3),
            "words": list(current_group)
        })

    # دمج أي مشهد قصير جداً أو مبتور نحوياً مع المشهد المجاور لضمان اكتمال الجملة الدلالية
    merged_scenes: List[Dict[str, Any]] = []
    for sc in raw_scenes:
        sc_words = sc.get("words", [])
        sc_dur = float(sc["end"]) - float(sc["start"])
        if merged_scenes:
            prev_sc = merged_scenes[-1]
            prev_words = prev_sc.get("words", [])
            prev_last_w = str(prev_words[-1]["word"]) if prev_words else ""
            prev_pp_w = str(prev_words[-2]["word"]) if len(prev_words) >= 2 else ""
            curr_first_w = str(sc_words[0]["word"]) if sc_words else ""
            if not can_split_between_arabic_words(prev_last_w, curr_first_w, prev_pp_w):
                prev_sc["words"].extend(sc_words)
                prev_sc["end"] = sc["end"]
                prev_sc["text"] = " ".join(x["word"] for x in prev_sc["words"])
                continue
            if (len(sc_words) < 2 or sc_dur < 0.9) and len(prev_sc["words"]) + len(sc_words) <= 13:
                prev_sc["words"].extend(sc_words)
                prev_sc["end"] = sc["end"]
                prev_sc["text"] = " ".join(x["word"] for x in prev_sc["words"])
                continue
        merged_scenes.append(sc)

    for idx in range(len(merged_scenes) - 1):
        gap = merged_scenes[idx + 1]["start"] - merged_scenes[idx]["end"]
        if 0.0 < gap <= 1.0:
            merged_scenes[idx]["end"] = merged_scenes[idx + 1]["start"]
            if merged_scenes[idx]["words"]:
                merged_scenes[idx]["words"][-1]["end"] = merged_scenes[idx + 1]["start"]
        elif gap > 1.0:
            merged_scenes[idx]["end"] = round(merged_scenes[idx]["end"] + min(0.6, gap * 0.4), 3)

    return merged_scenes


# ==============================================================================
# 3. دوال إدارة وتعديل الكابشن التفاعلي لجميع الأنماط
# ==============================================================================
def get_last_extracted_transcript() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if _CUSTOM_CAPTION_OVERRIDE["enabled"] and _CUSTOM_CAPTION_OVERRIDE["words"]:
        return (
            [dict(w) for w in _CUSTOM_CAPTION_OVERRIDE["words"]],
            [dict(s) for s in _CUSTOM_CAPTION_OVERRIDE["sentences"]]
        )
    return (
        [dict(w) for w in _LAST_EXTRACTED_TRANSCRIPT["words"]],
        [dict(s) for s in _LAST_EXTRACTED_TRANSCRIPT["sentences"]]
    )


def clear_custom_caption_override():
    _CUSTOM_CAPTION_OVERRIDE["enabled"] = False
    _CUSTOM_CAPTION_OVERRIDE["words"] = []
    _CUSTOM_CAPTION_OVERRIDE["sentences"] = []


def set_custom_caption_override(
    custom_words: Optional[List[Dict[str, Any]]] = None,
    custom_sentences: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """حفظ تعديلات المستخدم على الكابشن ومزامنتها تلقائياً مع ملف الجلسة (`last_storyboard_session.json`)."""
    base_words, base_sentences = get_last_extracted_transcript()

    if custom_sentences is not None and custom_words is None:
        synced_words: List[Dict[str, Any]] = []
        for sent in custom_sentences:
            s_text = str(sent.get("text", "")).strip()
            s_start = round(float(sent.get("start", 0.0)), 3)
            s_end = round(float(sent.get("end", s_start + 1.0)), 3)
            if not s_text:
                continue

            rebuilt = distribute_text_into_word_timestamps(
                text=s_text,
                start_sec=s_start,
                end_sec=s_end,
                existing_words=sent.get("words") if isinstance(sent.get("words"), list) else None
            )
            synced_words.extend(rebuilt)

        synced_words = ensure_word_timestamp_continuity(synced_words)
        synced_sentences = split_words_into_micro_scenes(synced_words)

        _CUSTOM_CAPTION_OVERRIDE["enabled"] = True
        _CUSTOM_CAPTION_OVERRIDE["words"] = synced_words
        _CUSTOM_CAPTION_OVERRIDE["sentences"] = synced_sentences
        _LAST_EXTRACTED_TRANSCRIPT["words"] = synced_words
        _LAST_EXTRACTED_TRANSCRIPT["sentences"] = synced_sentences
        return synced_words, synced_sentences

    if custom_words is not None:
        cleaned_words = []
        for w in custom_words:
            w_txt = str(w.get("word", "")).strip()
            if not w_txt:
                continue
            w_s = round(float(w.get("start", 0.0)), 3)
            w_e = round(max(w_s + 0.08, float(w.get("end", w_s + 0.3))), 3)
            cleaned_words.append({
                "word": w_txt,
                "start": w_s,
                "end": w_e,
                "probability": 1.0
            })

        cleaned_words = ensure_word_timestamp_continuity(cleaned_words)
        updated_sentences = split_words_into_micro_scenes(cleaned_words)
        _CUSTOM_CAPTION_OVERRIDE["enabled"] = True
        _CUSTOM_CAPTION_OVERRIDE["words"] = cleaned_words
        _CUSTOM_CAPTION_OVERRIDE["sentences"] = updated_sentences
        _LAST_EXTRACTED_TRANSCRIPT["words"] = cleaned_words
        _LAST_EXTRACTED_TRANSCRIPT["sentences"] = updated_sentences
        return cleaned_words, updated_sentences

    return base_words, base_sentences


# ==============================================================================
# 4. تطبيع وتدقيق الدارجة الجزائرية والسياق الصوتي
# ==============================================================================
def normalize_algerian_word(word: str) -> str:
    if not word:
        return ""
    cleaned = word.strip()
    stripped_punct = cleaned.strip("،,.!؟?")
    if cleaned in ALGERIAN_DARIJA_LEXICON_FIXES:
        return ALGERIAN_DARIJA_LEXICON_FIXES[cleaned]
    if stripped_punct in ALGERIAN_DARIJA_LEXICON_FIXES:
        suffix = cleaned[len(stripped_punct):] if cleaned.startswith(stripped_punct) else ""
        return ALGERIAN_DARIJA_LEXICON_FIXES[stripped_punct] + suffix
    return cleaned


def normalize_algerian_sentence(text: str) -> str:
    if not text:
        return ""
    out = text.strip()
    for wrong, right in ALGERIAN_DARIJA_LEXICON_FIXES.items():
        out = re.sub(rf"(?<!\w){re.escape(wrong)}(?!\w)", right, out)
    for pattern, replacement in PHRASE_LEVEL_FIXES:
        out = re.sub(pattern, replacement, out)
    for pattern, replacement in CONTEXTUAL_BROKEN_WORD_REPAIRS:
        out = re.sub(pattern, replacement, out)
    return out


def apply_phrase_fixes_to_words(words_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """تطبيق التصحيحات المركبة والسياقية وفك الكلمات المدمجة مع الحفاظ على التوقيت."""
    if not words_list:
        return words_list

    expanded: List[Dict[str, Any]] = []
    for w in words_list:
        w_copy = dict(w)
        w_copy["word"] = normalize_algerian_word(w_copy["word"])
        parts = w_copy["word"].split()
        if len(parts) > 1:
            dur = max(0.12, float(w_copy["end"]) - float(w_copy["start"])) / len(parts)
            for idx, p in enumerate(parts):
                expanded.append({
                    "word": p,
                    "start": round(float(w_copy["start"]) + idx * dur, 3),
                    "end": round(float(w_copy["start"]) + (idx + 1) * dur, 3),
                    "probability": w_copy.get("probability", 0.95)
                })
        else:
            expanded.append(w_copy)

    for i in range(len(expanded)):
        w_curr = expanded[i]["word"].strip("،,.")
        if w_curr in {"لنلو"}:
            expanded[i]["word"] = "أهلاً"

    deduped = []
    for w in expanded:
        w_clean = w["word"].strip("،,.")
        if deduped and deduped[-1]["word"].strip("،,.") == w_clean and w_clean not in {"اصبر", "أصبر"}:
            deduped[-1]["end"] = w["end"]
            deduped[-1]["word"] = w["word"]
        else:
            deduped.append(w)

    repaired = repair_truncated_words_and_sentences(deduped)
    final_expanded = []
    for w in repaired:
        parts = str(w.get("word", "")).split()
        if len(parts) > 1:
            dur = max(0.12, float(w["end"]) - float(w["start"])) / len(parts)
            for idx, p in enumerate(parts):
                final_expanded.append({
                    "word": p,
                    "start": round(float(w["start"]) + idx * dur, 3),
                    "end": round(float(w["start"]) + (idx + 1) * dur, 3),
                    "probability": w.get("probability", 0.96)
                })
        else:
            final_expanded.append(w)

    cleaned_no_retakes, _ = detect_and_remove_voiceover_retakes(final_expanded, remap_timestamps=False)
    return ensure_word_timestamp_continuity(cleaned_no_retakes)


# ==============================================================================
# 5. المحرك الأول: Google Speech Recognition (ar-DZ الجزائر) مجاناً بدون مفتاح!
# ==============================================================================
def _transcribe_via_google_ar_dz_chunks(audio_path: str) -> Optional[List[Dict[str, Any]]]:
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
        from pydub.silence import detect_nonsilent
    except ImportError as e:
        logger.debug(f"مكتبة speech_recognition غير متوفرة ({e}).")
        return None

    temp_16k = audio_path + "_16k_mono.wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-threads", "1", "-i", audio_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-threads", "1", temp_16k],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60
        )
        if os.path.exists(temp_16k) and os.path.getsize(temp_16k) > 512:
            audio = AudioSegment.from_wav(temp_16k)
        else:
            audio = AudioSegment.from_file(audio_path).set_frame_rate(16000).set_channels(1).set_sample_width(2)
        total_ms = len(audio)
        if total_ms < 200:
            return None

        thresh = max(-50.0, min(-30.0, float(audio.dBFS) - 9.0)) if audio.dBFS != -float("inf") else -40.0
        # اكتشاف الكلام بدقة مع اعتبار أي صمت > 250ms حد فصل طبيعي
        raw_chunks = detect_nonsilent(audio, min_silence_len=250, silence_thresh=thresh, seek_step=10)
        if not raw_chunks:
            raw_chunks = [[0, total_ms]]

        merged_chunks: List[List[int]] = []
        for s_ms, e_ms in raw_chunks:
            s_pad = max(0, s_ms - 120)
            e_pad = min(total_ms, e_ms + 140)
            if not merged_chunks:
                merged_chunks.append([s_pad, e_pad])
            else:
                prev_s, prev_e = merged_chunks[-1]
                if (s_pad - prev_e < 260 and (e_pad - prev_s) < 8500) or (prev_e - prev_s < 1500 and (e_pad - prev_s) < 9000):
                    merged_chunks[-1][1] = e_pad
                else:
                    merged_chunks.append([s_pad, e_pad])

        final_chunks: List[Tuple[int, int]] = []
        # Fast network check so offline sandbox never hangs on Google API
        try:
            import socket
            socket.setdefaulttimeout(3.5)
            with socket.create_connection(("8.8.8.8", 53), timeout=1.5):
                pass
        except Exception:
            return None

        for s_ms, e_ms in merged_chunks:
            cur_s = s_ms
            while (e_ms - cur_s) > 9500:
                search_start = cur_s + 5500
                search_end = min(e_ms - 800, cur_s + 8800)
                best_split = cur_s + 7200
                min_rms = float("inf")
                for probe_ms in range(search_start, max(search_start + 25, search_end), 20):
                    win_slice = audio[probe_ms:probe_ms + 45]
                    if win_slice.rms < min_rms:
                        min_rms = win_slice.rms
                        best_split = probe_ms + 22
                final_chunks.append((cur_s, min(e_ms, best_split + 35)))
                cur_s = max(cur_s + 700, best_split - 35)
            if e_ms - cur_s >= 160:
                final_chunks.append((cur_s, e_ms))

        recognizer = sr.Recognizer()
        all_words: List[Dict[str, Any]] = []

        def _recognize_chunk_with_fallback(c_s: int, c_e: int) -> str:
            ch_aud = audio[c_s:c_e]
            ad = sr.AudioData(ch_aud.raw_data, 16000, 2)
            for lang_code in ("ar-DZ", "ar-SA", "ar"):
                try:
                    res_txt = recognizer.recognize_google(ad, language=lang_code)
                    if res_txt and res_txt.strip():
                        return res_txt.strip()
                except sr.UnknownValueError:
                    continue
                except Exception:
                    break
            if (c_e - c_s) > 2000:
                mid_s = c_s + int((c_e - c_s) * 0.35)
                mid_e = c_s + int((c_e - c_s) * 0.65)
                best_m = (c_s + c_e) // 2
                min_r = float("inf")
                for p_ms in range(mid_s, max(mid_s + 20, mid_e), 20):
                    w_sl = audio[p_ms:p_ms + 40]
                    if w_sl.rms < min_r:
                        min_r = w_sl.rms
                        best_m = p_ms + 20
                part1 = _recognize_chunk_with_fallback(c_s, best_m)
                part2 = _recognize_chunk_with_fallback(best_m, c_e)
                return f"{part1} {part2}".strip()
            return ""

        for c_start_ms, c_end_ms in final_chunks:
            chunk_audio = audio[c_start_ms:c_end_ms]
            try:
                text_dz = _recognize_chunk_with_fallback(c_start_ms, c_end_ms)
            except Exception as e:
                logger.warning(f"تعذر الاتصال بمحرك ar-DZ: {e}")
                return None
            if not text_dz or not text_dz.strip():
                continue

            cleaned_sentence = normalize_algerian_sentence(text_dz.strip())
            tokens = [normalize_algerian_word(t) for t in cleaned_sentence.split() if t.strip()]
            if not tokens:
                continue

            c_start_sec = c_start_ms / 1000.0
            c_end_sec = c_end_ms / 1000.0
            sub_nonsilent = detect_nonsilent(chunk_audio, min_silence_len=100, silence_thresh=thresh - 2.0, seek_step=10)
            if sub_nonsilent:
                speech_s_sec = c_start_sec + (sub_nonsilent[0][0] / 1000.0)
                speech_e_sec = c_start_sec + (sub_nonsilent[-1][1] / 1000.0)
            else:
                speech_s_sec, speech_e_sec = c_start_sec, c_end_sec

            speech_dur = max(0.18, speech_e_sec - speech_s_sec)
            weights = [max(2.0, float(len(tok)) ** 0.85) for tok in tokens]
            total_weight = sum(weights)

            cursor = speech_s_sec
            for idx, (tok, w_weight) in enumerate(zip(tokens, weights)):
                w_dur = speech_dur * (w_weight / total_weight)
                w_end = speech_e_sec if idx == len(tokens) - 1 else (cursor + w_dur)
                all_words.append({
                    "word": tok,
                    "start": round(cursor, 3),
                    "end": round(max(cursor + 0.08, w_end), 3),
                    "probability": 0.95
                })
                cursor = w_end

        if all_words:
            logger.info(f"نجح التعرف الصوتي باللهجة الجزائرية (ar-DZ): {len(all_words)} كلمة.")
            return ensure_word_timestamp_continuity(all_words)

    except Exception as e:
        logger.warning(f"ملاحظة في محرك ar-DZ: {e}")
    finally:
        if os.path.exists(temp_16k):
            try:
                os.remove(temp_16k)
            except Exception:
                pass
        _force_free_ram()

    return None


# ==============================================================================
# 6. المحرك الثاني: Gemini Multimodal Audio / Groq Whisper Large-v3
# ==============================================================================
def _transcribe_via_gemini_multimodal(
    audio_path: str,
    gemini_api_key: Optional[str] = None
) -> Optional[List[Dict[str, Any]]]:
    gem_key = (gemini_api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not gem_key:
        return None

    temp_mp3 = None
    try:
        from pydub import AudioSegment
        aud = AudioSegment.from_file(audio_path)
        total_dur = len(aud) / 1000.0
        temp_mp3 = audio_path + "_gem_temp.mp3"
        aud.set_frame_rate(16000).set_channels(1).export(temp_mp3, format="mp3", bitrate="64k")

        with open(temp_mp3, "rb") as f:
            b64_audio = base64.b64encode(f.read()).decode("utf-8")

        prompt = (
            f"هذا ملف صوتي مدته {total_dur:.2f} ثانية باللهجة الجزائرية الدارجة (Algerian Darija) أو العربية. "
            "فرّغ كل كلمة منطوقة بدقة تامة كما قيلت بالدارجة الجزائرية. "
            "أرجع JSON فقط عبارة عن قائمة قواميس لكل كلمة: "
            "[{\"word\": \"الكلمة\", \"start\": 0.0, \"end\": 0.4}, ...]"
        )

        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gem_key}"
            resp = requests.post(
                url,
                json={
                    "contents": [{
                        "parts": [
                            {"inlineData": {"mimeType": "audio/mp3", "data": b64_audio}},
                            {"text": prompt}
                        ]
                    }],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000}
                },
                timeout=30
            )
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    txt = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    match = re.search(r"\[.*\]", txt, re.DOTALL)
                    if match:
                        arr = json.loads(match.group(0))
                        words_out = []
                        for item in arr:
                            w_str = normalize_algerian_word(str(item.get("word", "")))
                            if w_str:
                                words_out.append({
                                    "word": w_str,
                                    "start": round(float(item.get("start", 0.0)), 3),
                                    "end": round(float(item.get("end", 0.3)), 3),
                                    "probability": 0.98
                                })
                        if words_out:
                            return ensure_word_timestamp_continuity(words_out, total_dur)
    except Exception as e:
        logger.warning(f"Gemini audio transcription fallback: {e}")
    finally:
        if temp_mp3 and os.path.exists(temp_mp3):
            try:
                os.remove(temp_mp3)
            except Exception:
                pass
    return None


def _transcribe_via_cloud_api(
    audio_path: str,
    groq_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    language: str = "ar"
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    gem_words = _transcribe_via_gemini_multimodal(audio_path, gemini_api_key=gemini_api_key)
    if gem_words:
        gem_words = apply_phrase_fixes_to_words(gem_words)
        return gem_words, split_words_into_micro_scenes(gem_words)

    groq_key = (groq_api_key or os.environ.get("GROQ_API_KEY", "")).strip()
    openai_key = (openai_api_key or os.environ.get("OPENAI_API_KEY", "")).strip()

    upload_path = audio_path
    temp_compressed = None
    try:
        if os.path.getsize(audio_path) > 22 * 1024 * 1024 or audio_path.lower().endswith((".mp4", ".mov", ".mkv", ".avi")):
            from pydub import AudioSegment
            temp_compressed = audio_path + "_cloud_temp.mp3"
            aud = AudioSegment.from_file(audio_path)
            aud = aud.set_frame_rate(16000).set_channels(1)
            aud.export(temp_compressed, format="mp3", bitrate="64k")
            upload_path = temp_compressed
    except Exception:
        upload_path = audio_path

    endpoints = []
    if groq_key:
        endpoints.append(("https://api.groq.com/openai/v1/audio/transcriptions", groq_key, "whisper-large-v3"))
    if openai_key:
        endpoints.append(("https://api.openai.com/v1/audio/transcriptions", openai_key, "whisper-1"))

    try:
        for url, api_key, model_name in endpoints:
            try:
                with open(upload_path, "rb") as f:
                    files = {"file": (os.path.basename(upload_path), f, "audio/mpeg")}
                    data = [
                        ("model", model_name),
                        ("response_format", "verbose_json"),
                        ("prompt", ALGERIAN_DARIJA_INITIAL_PROMPT),
                        ("timestamp_granularities[]", "word"),
                        ("timestamp_granularities[]", "segment")
                    ]
                    if language and language != "auto":
                        data.append(("language", language))

                    resp = requests.post(
                        url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        files=files,
                        data=data,
                        timeout=45
                    )

                if resp.status_code == 200:
                    payload = resp.json()
                    raw_words = payload.get("words", [])
                    words_list = []
                    for w in raw_words:
                        w_txt = normalize_algerian_word(w.get("word", ""))
                        if w_txt:
                            words_list.append({
                                "word": w_txt,
                                "start": round(float(w.get("start", 0.0)), 3),
                                "end": round(float(w.get("end", 0.0)), 3),
                                "probability": 0.96
                            })

                    if words_list:
                        words_list = apply_phrase_fixes_to_words(words_list)
                        micro_scenes = split_words_into_micro_scenes(words_list)
                        return words_list, micro_scenes
            except Exception as e:
                logger.warning(f"فشل التفريغ السحابي ({model_name}): {e}")
    finally:
        if temp_compressed and os.path.exists(temp_compressed):
            try:
                os.remove(temp_compressed)
            except Exception:
                pass

    return None


# ==============================================================================
# 7. الدمج الهجين بين محرك الجزائر (ar-DZ) وتوقيت faster-whisper
# ==============================================================================
def merge_ar_dz_with_whisper_timestamps(
    ar_dz_words: Optional[List[Dict[str, Any]]],
    whisper_words: List[Dict[str, Any]],
    groq_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    if ar_dz_words and len(ar_dz_words) >= max(3, int(len(whisper_words) * 0.75)):
        if whisper_words:
            dz_text = " ".join(w["word"] for w in ar_dz_words)
            wh_text = " ".join(w["word"] for w in whisper_words)
            prompt = (
                f"لدينا قراءتان لنفس التسجيل الصوتي بالدارجة الجزائرية:\n"
                f"القراءة الجزائرية (ar-DZ): \"{dz_text}\"\n"
                f"قراءة Whisper العام: \"{wh_text}\"\n"
                f"عدد كلمات القراءة الجزائرية هو {len(ar_dz_words)} كلمة.\n"
                "ادمج القراءتين لتصحيح أي كلمة غير مفهومة حسب سياق الفيديو العام، وأرجع النص الجزائري الصحيح فقط مفصولاً بمسافات."
            )
            merged_txt = query_hybrid_llm(
                prompt=prompt,
                system_prompt="أنت خبير في الدارجة الجزائرية وفهم سياق الكلام. أرجع النص المصحح فقط بدون أي شرح أو علامات تنصيص.",
                groq_api_key=groq_api_key,
                gemini_api_key=gemini_api_key,
                openai_api_key=openai_api_key,
                temperature=0.1,
                max_tokens=400
            )
            if merged_txt:
                clean_line = merged_txt.strip().strip("\"'")
                tokens = [normalize_algerian_word(t) for t in clean_line.split() if t.strip()]
                if len(tokens) == len(ar_dz_words):
                    for idx, tok in enumerate(tokens):
                        ar_dz_words[idx]["word"] = tok
        return apply_phrase_fixes_to_words(ar_dz_words)

    return apply_phrase_fixes_to_words(whisper_words)


def get_optimal_device_settings() -> Tuple[str, str]:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


def _get_or_load_whisper_model(model_size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    cache_key = f"{model_size}_{device}_{compute_type}"
    if cache_key not in _WHISPER_MODEL_CACHE:
        _WHISPER_MODEL_CACHE[cache_key] = WhisperModel(
            model_size_or_path=model_size,
            device=device,
            compute_type=compute_type
        )
    return _WHISPER_MODEL_CACHE[cache_key]


def _run_full_transcription(
    audio_path: str,
    model_size: str = "small",
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
    language: Optional[str] = "ar",
    vad_filter: bool = True,
    dialect_mode: str = "algerian_darija",
    groq_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if _CUSTOM_CAPTION_OVERRIDE["enabled"] and _CUSTOM_CAPTION_OVERRIDE["words"]:
        return (
            [dict(w) for w in _CUSTOM_CAPTION_OVERRIDE["words"]],
            [dict(s) for s in _CUSTOM_CAPTION_OVERRIDE["sentences"]]
        )

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"الملف المطلوب تفريغه غير موجود: {audio_path}")

    file_mtime = os.path.getmtime(audio_path)
    cache_key = f"{os.path.abspath(audio_path)}_{file_mtime}_{model_size}_{dialect_mode}"
    if cache_key in _TRANSCRIPTION_CACHE:
        cached = _TRANSCRIPTION_CACHE[cache_key]
        _LAST_EXTRACTED_TRANSCRIPT["words"] = cached["words"]
        _LAST_EXTRACTED_TRANSCRIPT["sentences"] = cached["sentences"]
        return cached["words"], cached["sentences"]

    cloud_res = _transcribe_via_cloud_api(
        audio_path=audio_path,
        groq_api_key=groq_api_key,
        openai_api_key=openai_api_key,
        gemini_api_key=gemini_api_key,
        language=language or "ar"
    )
    if cloud_res is not None:
        words_list, micro_scenes = cloud_res
        _TRANSCRIPTION_CACHE[cache_key] = {"words": words_list, "sentences": micro_scenes}
        _LAST_EXTRACTED_TRANSCRIPT["words"] = words_list
        _LAST_EXTRACTED_TRANSCRIPT["sentences"] = micro_scenes
        return words_list, micro_scenes

    ar_dz_words = None
    if dialect_mode == "algerian_darija":
        ar_dz_words = _transcribe_via_google_ar_dz_chunks(audio_path)

    detected_device, detected_compute = get_optimal_device_settings()
    final_device = device if device is not None else detected_device
    final_compute = compute_type if compute_type is not None else detected_compute

    _has_large_gap = False
    if ar_dz_words and len(ar_dz_words) >= 3:
        for _gi in range(len(ar_dz_words) - 1):
            if float(ar_dz_words[_gi + 1]["start"]) - float(ar_dz_words[_gi]["end"]) > 2.6:
                _has_large_gap = True
                break
    if ar_dz_words and len(ar_dz_words) >= 3 and final_device == "cpu" and not _has_large_gap:
        final_words = apply_phrase_fixes_to_words(ar_dz_words)
        micro_scenes = split_words_into_micro_scenes(final_words)
        if len(_TRANSCRIPTION_CACHE) > 2:
            _TRANSCRIPTION_CACHE.clear()
        _TRANSCRIPTION_CACHE[cache_key] = {"words": final_words, "sentences": micro_scenes}
        _LAST_EXTRACTED_TRANSCRIPT["words"] = final_words
        _LAST_EXTRACTED_TRANSCRIPT["sentences"] = micro_scenes
        _force_free_ram()
        return final_words, micro_scenes

    eff_model_size = "base" if (final_device == "cpu" and model_size in ("small", "medium", "large-v3", "auto")) else model_size

    whisper_words: List[Dict[str, Any]] = []
    try:
        model = _get_or_load_whisper_model(eff_model_size, final_device, final_compute)
        target_language = None if (language == "auto" or not language) else language

        segments, info = model.transcribe(
            audio_path,
            word_timestamps=True,
            language=target_language,
            initial_prompt=ALGERIAN_DARIJA_INITIAL_PROMPT,
            beam_size=2 if final_device == "cpu" else 5,
            best_of=2 if final_device == "cpu" else 5,
            condition_on_previous_text=False,
            compression_ratio_threshold=3.2,
            log_prob_threshold=-1.6,
            no_speech_threshold=0.85,
            vad_filter=vad_filter,
            vad_parameters=dict(threshold=0.25, min_speech_duration_ms=100, min_silence_duration_ms=250, speech_pad_ms=200)
        )

        for seg in segments:
            if seg.words:
                for word_obj in seg.words:
                    cleaned_word = normalize_algerian_word(word_obj.word)
                    if cleaned_word:
                        whisper_words.append({
                            "word": cleaned_word,
                            "start": round(word_obj.start, 3),
                            "end": round(word_obj.end, 3),
                            "probability": round(word_obj.probability, 3)
                        })

        del segments
        del model
        _WHISPER_MODEL_CACHE.clear()
        _force_free_ram()
    except Exception as wh_err:
        logger.warning(f"Whisper local fallback notice: {wh_err}")
        _WHISPER_MODEL_CACHE.clear()
        _force_free_ram()

    final_words = merge_ar_dz_with_whisper_timestamps(
        ar_dz_words=ar_dz_words,
        whisper_words=whisper_words,
        groq_api_key=groq_api_key,
        gemini_api_key=gemini_api_key,
        openai_api_key=openai_api_key
    )

    micro_scenes = split_words_into_micro_scenes(final_words)

    _TRANSCRIPTION_CACHE[cache_key] = {
        "words": final_words,
        "sentences": micro_scenes
    }
    _LAST_EXTRACTED_TRANSCRIPT["words"] = final_words
    _LAST_EXTRACTED_TRANSCRIPT["sentences"] = micro_scenes

    return final_words, micro_scenes


def transcribe_audio(
    audio_path: str,
    model_size: str = "small",
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
    language: Optional[str] = "ar",
    vad_filter: bool = True,
    dialect_mode: str = "algerian_darija",
    groq_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    words, _ = _run_full_transcription(
        audio_path=audio_path,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        language=language,
        vad_filter=vad_filter,
        dialect_mode=dialect_mode,
        groq_api_key=groq_api_key,
        gemini_api_key=gemini_api_key,
        openai_api_key=openai_api_key
    )
    return words


def transcribe_sentences(
    audio_path: str,
    model_size: str = "small",
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
    language: Optional[str] = "ar",
    dialect_mode: str = "algerian_darija",
    groq_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    _, sentences = _run_full_transcription(
        audio_path=audio_path,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        language=language,
        vad_filter=True,
        dialect_mode=dialect_mode,
        groq_api_key=groq_api_key,
        gemini_api_key=gemini_api_key,
        openai_api_key=openai_api_key
    )
    return sentences