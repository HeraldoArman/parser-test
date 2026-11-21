import json
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .extraction import ranker
from .extraction.pipeline import analyze
from .models import Batch, Document

DOCS = Path(__file__).resolve().parent.parent / "docs-example"

GOLDEN = {
    "BRP Anum Gasal_2026_2027 up 31082026.pdf": ("ok", 4),
    "BRP MPPI 2026 Ganjil.pdf": ("ok", 7),
    "Silabus POK 2025-Gnp-Mhs.v3.pdf": ("bonus", 6),
    "Silabus Jarkom x Jarkomdat Ganjil 2026_2027.docx": ("ambiguous", 7),
    "DAA Weekly Plan.xlsx": ("not_found", 0),
}


class GoldenCorpusTests(TestCase):
    """The acceptance table for every format in docs-example."""

    def test_docs_example_statuses(self):
        missing = [name for name in GOLDEN if not (DOCS / name).exists()]
        if missing:
            self.skipTest(f"missing fixtures: {missing}")
        for name, (status, count) in GOLDEN.items():
            with self.subTest(name=name):
                result = analyze(str(DOCS / name))
                self.assertEqual(result["status"], status, result.get("reasons"))
                self.assertEqual(len(result["components"]), count)
                if result["components"]:
                    self.assertEqual(len(result["candidates"]), len(
                        {tuple(c["signature"]) for c in result["candidates"]}))


class UploadFlowTests(TestCase):
    def test_upload_review_select_approve_export(self):
        source = DOCS / "BRP Anum Gasal_2026_2027 up 31082026.pdf"
        if not source.exists():
            self.skipTest("fixture missing")
        upload = SimpleUploadedFile(
            source.name, source.read_bytes(), content_type="application/pdf")

        response = self.client.post(reverse("assessments:upload"), {"files": [upload]})
        self.assertEqual(response.status_code, 302)
        batch_url = response["Location"]
        self.assertEqual(self.client.get(batch_url).status_code, 200)

        from .models import Batch, Document
        batch = Batch.objects.get()
        document = Document.objects.get(batch=batch)
        self.assertEqual(document.status, "ok")
        self.assertEqual(document.components.count(), 4)
        self.assertEqual(len(document.sha256), 64)

        review_url = reverse("assessments:review", args=[document.pk])
        self.assertEqual(self.client.get(review_url).status_code, 200)

        # approve the prefilled rows as they stand
        rows = list(document.components.all())
        data = {
            "action": "approve",
            "components-TOTAL_FORMS": str(len(rows)),
            "components-INITIAL_FORMS": str(len(rows)),
            "components-MIN_NUM_FORMS": "0",
            "components-MAX_NUM_FORMS": "1000",
        }
        for index, component in enumerate(rows):
            data[f"components-{index}-id"] = component.pk
            data[f"components-{index}-name"] = component.name
            data[f"components-{index}-kind"] = component.kind
            data[f"components-{index}-weight"] = str(component.weight)
            data[f"components-{index}-note"] = component.note
        self.assertEqual(self.client.post(review_url, data).status_code, 302)
        document.refresh_from_db()
        self.assertEqual(document.status, "approved")

        csv_response = self.client.get(reverse("assessments:export", args=[batch.pk, "csv"]))
        self.assertIn("Kuis", csv_response.content.decode())
        json_response = self.client.get(reverse("assessments:export", args=[batch.pk, "json"]))
        self.assertEqual(json_response.status_code, 200)


class RankerTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "ranker.json"

    def test_fit_separates_separable_rows(self):
        rows, labels = [], []
        for index in range(30):
            positive = index % 2 == 0
            rows.append([1.0 if positive else 0.0] + [0.0] * (len(ranker.FEATURES) - 1))
            labels.append(1 if positive else 0)
        model = ranker.fit(rows, labels)
        self.assertGreater(ranker.predict_vector(model, rows[0]), ranker.predict_vector(model, rows[1]))
        self.assertGreater(ranker.predict_vector(model, rows[0]), 0.5)

    @override_settings()
    def test_load_ignores_undertrained_model(self):
        from django.conf import settings
        settings.RANKER_PATH = self.path
        self.path.write_text(json.dumps({"features": list(ranker.FEATURES), "weights": [0] * 11,
                                         "bias": 0.0, "samples": 3, "positives": 1}))
        self.assertIsNone(ranker.load())

    @override_settings()
    def test_training_command_writes_model_from_approvals(self):
        from django.conf import settings
        settings.RANKER_PATH = self.path
        batch = Batch.objects.create(note="train")
        for number in range(10):
            candidate = {"signals": {name: 0.0 for name in ranker.FEATURES}}
            other = {"signals": {name: 0.0 for name in ranker.FEATURES}}
            candidate["signals"]["sum_exact"] = 1.0
            Document.objects.create(
                batch=batch, file="train.pdf", original_name=f"t{number}.pdf",
                status="approved", selected=0,
                result={"candidates": [candidate, other]},
            )
        from io import StringIO
        call_command("train_ranker", stdout=StringIO())
        model = json.loads(self.path.read_text())
        self.assertEqual(model["samples"], 20)
        self.assertEqual(model["positives"], 10)
        self.assertIsNotNone(ranker.load())


class OcrTests(TestCase):
    def test_scanned_page_is_read_by_ocr(self):
        from .extraction.readers import ocr
        if not ocr.available():
            self.skipTest("rapidocr not installed")
        import pdfplumber
        source = DOCS / "BRP Anum Gasal_2026_2027 up 31082026.pdf"
        if not source.exists():
            self.skipTest("fixture missing")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "scanned.pdf"
            with pdfplumber.open(source) as pdf:
                image = pdf.pages[4].to_image(resolution=200).original.convert("RGB")
            image.save(target, resolution=200)
            result = analyze(str(target))
        self.assertEqual(result["ocr_pages"], 1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([c["weight"] for c in result["components"]], [25.0, 15.0, 30.0, 30.0])
