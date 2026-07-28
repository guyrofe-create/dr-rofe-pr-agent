import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class AiSurfaceImportTests(unittest.TestCase):
    def test_imports_evidenced_gemini_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.json"
            output = Path(tmp) / "out.json"
            source.write_text(json.dumps([{
                "engine": "Google",
                "surface": "gemini",
                "interface": "consumer_ui",
                "collection_method": "authorized_browser_sample",
                "model": "Gemini",
                "country": "IL",
                "language": "he",
                "prompt": "מי הוא ד״ר גיא רופא?",
                "exact_answer": "תשובה שנשמרה במלואה",
                "observed_at": "2026-07-28T10:00:00Z",
                "screenshot_sha256": "a" * 64,
                "cited_sources": ["https://guyrofe.com/"],
            }]), encoding="utf-8")
            subprocess.run(
                [
                    "python3", "scripts/import_ai_surface_samples.py",
                    str(source), "--output", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["samples"][0]["engine"], "Google")
            self.assertTrue(payload["samples"][0]["evidence_preserved"])

    def test_rejects_browser_sample_without_screenshot_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.json"
            source.write_text(json.dumps([{
                "engine": "Google",
                "surface": "gemini",
                "interface": "consumer_ui",
                "collection_method": "authorized_browser_sample",
                "model": "Gemini",
                "country": "IL",
                "language": "he",
                "prompt": "prompt",
                "exact_answer": "answer",
                "observed_at": "2026-07-28T10:00:00Z",
            }]), encoding="utf-8")
            result = subprocess.run(
                ["python3", "scripts/import_ai_surface_samples.py", str(source)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("screenshot_sha256", result.stderr)


if __name__ == "__main__":
    unittest.main()
