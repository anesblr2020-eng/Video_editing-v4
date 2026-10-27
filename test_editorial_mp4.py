import json, shutil, subprocess, tempfile, unittest
from pathlib import Path
from editorial_mp4 import _scene_ranges, _short_title, render_editorial_mp4

class EditorialMP4Tests(unittest.TestCase):
    def test_titles_are_literal_excerpts(self):
        self.assertEqual(_short_title('السلام عليكم على بالي راك تعاني'), 'السلام عليكم على بالي')
    def test_text_only_scenes_cover_full_duration(self):
        ranges=_scene_ranges([{'spoken_text':'a'},{'spoken_text':'b'},{'spoken_text':'c'}], 9.0)
        self.assertEqual(ranges[0][0],0.0); self.assertEqual(ranges[-1][1],9.0)
        self.assertEqual(len(ranges),3)
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe unavailable')
    def test_render_real_mp4_and_preserve_audio(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'src.mp4'; out=Path(td)/'out.mp4'
            cmd=['ffmpeg','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=12:duration=2','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(src)]
            subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=60)
            scenes=[{'scene_number':1,'spoken_text':'السلام عليكم على بالي راك تعاني','start_time':None,'end_time':None}, {'scene_number':2,'spoken_text':'مشكل تاع الوقت وما عندكش الوقت','start_time':None,'end_time':None}]
            render_editorial_mp4(src,scenes,out)
            self.assertGreater(out.stat().st_size,2048)
            probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type','-of','json',str(out)],capture_output=True,text=True,check=True)
            types={s['codec_type'] for s in json.loads(probe.stdout)['streams']}
            self.assertIn('video',types); self.assertIn('audio',types)

if __name__=='__main__': unittest.main()
