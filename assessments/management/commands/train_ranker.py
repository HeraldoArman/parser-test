"""Fit the candidate ranker from approved review decisions."""
from django.core.management.base import BaseCommand

from assessments.extraction import ranker
from assessments.models import Document


class Command(BaseCommand):
    help = "Train the candidate ranker from approved documents (needs ~20 approvals)."

    def handle(self, *args, **options):
        documents = (
            Document.objects.filter(status="approved")
            .exclude(selected=None)
            .order_by("pk")
        )
        rows: list[list[float]] = []
        labels: list[int] = []
        per_document: list[tuple[list[list[float]], int]] = []
        for document in documents:
            candidates = document.candidates
            if len(candidates) < 2 or document.selected is None:
                continue
            vectors, chosen = [], document.selected
            for index, candidate in enumerate(candidates):
                signals = candidate.get("signals") or {}
                if not signals:
                    continue
                vectors.append([float(signals.get(name, 0.0)) for name in ranker.FEATURES])
                labels.append(1 if index == chosen else 0)
            if vectors:
                per_document.append((vectors, chosen))
                rows.extend(vectors)

        if len(rows) < ranker.MIN_SAMPLES or sum(labels) < ranker.MIN_POSITIVES:
            self.stderr.write(
                f"Not enough labels: {len(rows)} candidate rows, {sum(labels)} approvals "
                f"(need {ranker.MIN_SAMPLES} rows and {ranker.MIN_POSITIVES} positives). "
                "Approve more documents first."
            )
            return

        model = ranker.fit(rows, labels)
        top1 = 0
        for vectors, chosen in per_document:
            scores = [ranker.predict_vector(model, vector) for vector in vectors]
            if max(range(len(scores)), key=scores.__getitem__) == chosen:
                top1 += 1
        ranker.save(model)
        self.stdout.write(self.style.SUCCESS(
            f"Trained on {model['samples']} rows from {len(per_document)} documents "
            f"({model['positives']} approvals); picks the approved candidate for "
            f"{top1}/{len(per_document)} documents. Saved to {ranker.path()}."
        ))
