# -*- coding: utf-8 -*-
"""Local editorial MP4 renderer. Uses source footage + locally rendered motion graphics; no image-generation API."""
from __future__ import annotations
import json, math, shutil, subprocess, tempfile
from pathlib import Path
from typing import Any
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 720, 1280, 30
LIME = (223, 255, 0)
INK = (15, 17, 17)
WHITE = (250, 250, 246)
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

def _font(size: int):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try: return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
            except Exception: pass
    return ImageFont.load_default()

def _short_title(text: str, max_words: int = 4) -> str:
    # Exact contiguous excerpt only; never invent wording.
    words = str(text).split()
    return " ".join(words[:max_words])

def _scene_ranges(scenes: list[dict[str, Any]], duration: float):
    valid = all(s.get("start_time") is not None and s.get("end_time") is not None for s in scenes)
    if valid:
        ranges=[]
        for i,s in enumerate(scenes):
            a=max(0.0,float(s["start_time"])); b=max(a+0.25,float(s["end_time"]))
            if i+1<len(scenes): b=min(b,float(scenes[i+1].get("start_time",b))) if float(scenes[i+1].get("start_time",b))>a else b
            ranges.append((a,min(duration,b)))
        if ranges and ranges[-1][1] < duration: ranges[-1]=(ranges[-1][0],duration)
        if ranges and ranges[0][0] > 0: ranges[0]=(0.0,ranges[0][1])
        if all(b>a for a,b in ranges): return ranges
    # Text-only plans: distribute beats evenly across the full source duration.
    n=max(1,len(scenes)); return [(duration*i/n,duration*(i+1)/n) for i in range(n)]

def _draw_overlay(frame_bgr: np.ndarray, scene: dict[str, Any], local_t: float, scene_dur: float, index: int, total: int) -> np.ndarray:
    base=Image.fromarray(cv2.cvtColor(frame_bgr,cv2.COLOR_BGR2RGB)).convert("RGBA")
    overlay=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(overlay)
    # Editorial label bar; no persistent caption over the entire footage.
    d.rounded_rectangle((34,42,230,88), radius=4, fill=(255,255,255,238))
    d.rectangle((34,42,43,88), fill=(*LIME,255))
    d.text((58,52),f"SCENE {index:02d} / {total:02d}",font=_font(20),fill=(*INK,255),direction="ltr")
    title=_short_title(scene.get("spoken_text", ""), 4)
    # The title is a literal excerpt and lives in a compact editorial card.
    if title:
        size=58 if len(title)<19 else (48 if len(title)<28 else 39)
        font=_font(size)
        max_width=int(W*.84)
        words=title.split(); lines=[]; current=""
        for word in words:
            test=(current+" "+word).strip()
            if d.textbbox((0,0),test,font=font,direction="rtl")[2] <= max_width or not current:
                current=test
            else: lines.append(current); current=word
        if current: lines.append(current)
        lines=lines[:2]
        line_h=size+9; box_h=42+line_h*len(lines)+24
        # Animated entrance; the highlight moves only during the opening beat.
        ease=min(1.0,max(0.0,local_t/.22)); ease=1-(1-ease)**3
        xshift=int((1-ease)*W*.28)
        y=H-int(H*.245)-box_h
        x0=38+xshift; x1=W-38+xshift
        d.polygon([(x0,y+8),(x1,y),(x1-16,y+box_h),(x0-10,y+box_h-5)],fill=(*WHITE,247))
        d.rectangle((x0,y+8,x0+14,y+box_h-5),fill=(*LIME,255))
        yy=y+25
        for line in lines:
            d.text((W-64+xshift,yy),line,font=font,fill=(*INK,255),anchor="ra",direction="rtl",stroke_width=0)
            yy+=line_h
    # Short timeline accent at bottom, resets at every visual beat.
    bar_x,bar_y,bar_w=40,H-34,W-80
    d.rounded_rectangle((bar_x,bar_y,bar_x+bar_w,bar_y+5),radius=2,fill=(255,255,255,150))
    progress=min(1.0,max(0.0,local_t/max(.1,scene_dur)))
    d.rounded_rectangle((bar_x,bar_y,bar_x+int(bar_w*progress),bar_y+5),radius=2,fill=(*LIME,255))
    out=Image.alpha_composite(base,overlay).convert("RGB")
    return cv2.cvtColor(np.asarray(out),cv2.COLOR_RGB2BGR)

def render_editorial_mp4(source: str|Path, scenes: list[dict[str,Any]], output: str|Path, progress_callback=None) -> Path:
    source=Path(source); output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    if not source.is_file() or source.stat().st_size==0: raise ValueError("ملف المصدر غير موجود أو فارغ.")
    if not scenes: raise ValueError("خطة المشاهد فارغة.")
    if not shutil.which("ffmpeg"): raise RuntimeError("FFmpeg غير مثبت على الخادم.")
    cap=cv2.VideoCapture(str(source))
    if not cap.isOpened(): raise RuntimeError("تعذر فتح الفيديو المصدر؛ يلزم ملف فيديو يحتوي على الصورة الأصلية.")
    fps=cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames<=0: cap.release(); raise RuntimeError("تعذر تحديد مدة الفيديو المصدر.")
    duration=total_frames/fps
    ranges=_scene_ranges(scenes,duration)
    with tempfile.TemporaryDirectory(prefix="editorial_render_") as td:
        silent=Path(td)/"visual.mp4"
        writer=cv2.VideoWriter(str(silent),cv2.VideoWriter_fourcc(*"mp4v"),FPS,(W,H))
        if not writer.isOpened(): cap.release(); raise RuntimeError("تعذر إنشاء مسار الفيديو المؤقت.")
        scene_idx=0
        for fi in range(total_frames):
            ok, frame=cap.read()
            if not ok: break
            t=fi/fps
            while scene_idx<len(ranges)-1 and t>=ranges[scene_idx][1]: scene_idx+=1
            a,b=ranges[scene_idx]; scene=scenes[scene_idx]
            # Fill 9:16 from the source using a center crop; never invent/generate imagery.
            fh,fw=frame.shape[:2]; target_ratio=W/H; ratio=fw/fh
            if ratio>target_ratio:
                nw=int(fh*target_ratio); x=max(0,(fw-nw)//2); frame=frame[:,x:x+nw]
            else:
                nh=int(fw/target_ratio); y=max(0,(fh-nh)//2); frame=frame[y:y+nh,:]
            frame=cv2.resize(frame,(W,H),interpolation=cv2.INTER_AREA if frame.shape[1]>W else cv2.INTER_CUBIC)
            # Gentle alternating push-in per beat, keeping the footage as the visual source.
            phase=max(0.0,min(1.0,(t-a)/max(.1,b-a)))
            scale=1.0+0.035*phase
            if scale>1:
                cw=int(W/scale); ch=int(H/scale); x=(W-cw)//2; y=(H-ch)//2
                frame=cv2.resize(frame[y:y+ch,x:x+cw],(W,H),interpolation=cv2.INTER_CUBIC)
            frame=_draw_overlay(frame,scene,t-a,max(.1,b-a),scene_idx+1,len(scenes))
            writer.write(frame)
            if progress_callback and fi%max(1,int(fps*2))==0: progress_callback(fi/max(1,total_frames),f"تركيب المشهد {scene_idx+1}/{len(scenes)} · {t:.1f}s")
        cap.release(); writer.release()
        if not silent.exists() or silent.stat().st_size<1024: raise RuntimeError("فشل إنشاء الصورة المتحركة.")
        cmd=["ffmpeg","-y","-i",str(silent),"-i",str(source),"-map","0:v:0","-map","1:a?","-c:v","libx264","-preset","veryfast","-crf","19","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",str(output)]
        proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=max(180,int(duration*8)))
        if proc.returncode!=0: raise RuntimeError("فشل دمج الصوت مع الفيديو: "+proc.stderr[-1200:])
    if not output.is_file() or output.stat().st_size<2048: raise RuntimeError("ملف MP4 الناتج غير صالح.")
    if progress_callback: progress_callback(1.0,"اكتمل تركيب MP4 والتحقق من الملف.")
    return output
