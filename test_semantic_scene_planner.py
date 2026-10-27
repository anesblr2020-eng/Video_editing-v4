import unittest
from semantic_scene_planner import plan_scenes, scenes_to_json

class SemanticScenePlannerTests(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(plan_scenes("   "), [])

    def test_splits_and_classifies_distinct_topics(self):
        text = "بديت مشروعي من الصفر. بعد ذلك جهزت عطر وعبوة للبيع. وبعدها نشرت إعلان على إنستغرام."
        scenes = plan_scenes(text)
        self.assertGreaterEqual(len(scenes), 3)
        self.assertEqual(scenes[0]["intent"], "beginning")
        self.assertEqual(scenes[1]["intent"], "product")
        self.assertEqual(scenes[2]["intent"], "social")

    def test_schema_is_json_serializable(self):
        scenes = plan_scenes("قررت نبدأ مشروعي ونبيع منتج بسعر مناسب.")
        data = scenes_to_json(scenes)
        self.assertIn('"schema_version": "1.0"', data)
        self.assertIn('"visual_concept"', data)

    def test_word_timestamps_are_attached(self):
        words = [
            {"word": "بديت", "start": 0.2, "end": 0.5},
            {"word": "مشروعي", "start": 0.6, "end": 0.9},
            {"word": "من", "start": 1.0, "end": 1.1},
            {"word": "الصفر", "start": 1.2, "end": 1.6},
        ]
        scenes = plan_scenes("بديت مشروعي من الصفر.", words=words)
        self.assertIsNotNone(scenes[0]["start_time"])
        self.assertGreaterEqual(scenes[0]["end_time"], scenes[0]["start_time"])

if __name__ == "__main__":
    unittest.main()
