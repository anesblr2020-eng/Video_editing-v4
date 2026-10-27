import unittest
from visual_scene_prototype import build_scene_html

class VisualScenePrototypeTests(unittest.TestCase):
    def test_time_scene_has_clock_and_person(self):
        html = build_scene_html({"intent":"time", "spoken_text":"الوقت ضيق", "intent_label":"وقت"})
        self.assertIn('id="clock"', html)
        self.assertIn('id="person"', html)
        self.assertIn('@keyframes tick', html)

    def test_social_scene_is_different(self):
        time_html = build_scene_html({"intent":"time", "spoken_text":"الوقت"})
        social_html = build_scene_html({"intent":"social", "spoken_text":"انشر المحتوى"})
        self.assertNotEqual(time_html, social_html)
        self.assertIn('id="phone"', social_html)

    def test_editing_scene_has_real_timeline_structure(self):
        html = build_scene_html({"intent":"editing", "spoken_text":"تعديل الفيديو وقص الصمت"})
        self.assertIn('id="timeline"', html)
        self.assertIn('class="playhead"', html)
        self.assertIn('@keyframes playhead', html)

    def test_reference_style_has_kinetic_headline_and_speech_caption(self):
        html = build_scene_html({"intent":"editing", "spoken_text":"مونتاج الفيديو", "intent_label":"مونتاج"})
        self.assertIn('class="headline"', html)
        self.assertIn('@keyframes headline-in', html)
        self.assertIn('من المقاطع إلى فيديو جاهز', html)
        self.assertIn('مونتاج الفيديو', html)

    def test_ai_scene_has_distinct_composition(self):
        html = build_scene_html({"intent":"ai", "spoken_text":"بالذكاء الاصطناعي"})
        self.assertIn('id="ai-editorial"', html)
        self.assertIn('class="ai-orbit"', html)

    def test_escapes_text_and_limits_duration(self):
        html = build_scene_html({"intent":"product", "spoken_text":"<script>alert(1)</script>"}, 99)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('animation:progress 20.0s', html)

if __name__ == '__main__':
    unittest.main()
