import unittest
from auto_visual_assets import scene_prompt, _token

class AutoVisualAssetTests(unittest.TestCase):
    def test_prompt_includes_scene_text_and_style_constraints(self):
        prompt = scene_prompt({"spoken_text":"باش يمونتي فيديو", "intent":"editing", "visual_concept":"timeline"})
        self.assertIn("باش يمونتي فيديو", prompt)
        self.assertIn("No text", prompt)
        self.assertIn("timeline", prompt)
    def test_missing_token_fails_clearly(self):
        with self.assertRaisesRegex(RuntimeError, "REPLICATE_API_TOKEN"):
            _token("")
    def test_scene_specific_visual_direction(self):
        prompt = scene_prompt({"spoken_text":"وقت", "intent":"time"})
        self.assertIn("analog clock", prompt)
        self.assertIn("9:16", prompt)

if __name__ == '__main__': unittest.main()
