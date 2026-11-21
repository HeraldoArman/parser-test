import uuid
from pathlib import Path

from django.db import models


def upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"batches/{instance.batch_id}/{uuid.uuid4().hex}{suffix}"


class Batch(models.Model):
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Batch {self.pk} ({self.documents.count()} files)"


class Document(models.Model):
    STATUS_CHOICES = [
        ("ok", "OK"),
        ("bonus", "OK with bonus"),
        ("ambiguous", "Ambiguous"),
        ("needs_review", "Needs review"),
        ("not_found", "Assessment not found"),
        ("failed", "Failed"),
        ("approved", "Approved"),
    ]

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to=upload_path)
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    size = models.PositiveIntegerField(default=0)
    mime = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="needs_review")
    error = models.TextField(blank=True)
    fingerprint = models.CharField(max_length=40, blank=True, db_index=True)
    blocks = models.JSONField(default=list, blank=True)
    result = models.JSONField(default=dict, blank=True)
    extractor_version = models.CharField(max_length=20, blank=True)
    selected = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.original_name

    @property
    def source_text(self):
        parts = []
        for item in self.blocks or []:
            if item.get("type") == "table":
                parts.append("\n".join(" | ".join(str(cell) for cell in row)
                                       for row in item.get("rows", [])))
            else:
                parts.append(item.get("text", ""))
        return "\n".join(p for p in parts if p)

    @property
    def candidates(self):
        return (self.result or {}).get("candidates", [])

    @property
    def reasons(self):
        return (self.result or {}).get("reasons", [])

    @property
    def total_weight(self):
        return sum((c.weight or 0) for c in self.components.all())

    @property
    def component_count(self):
        return len(self.components.all())


class Component(models.Model):
    KIND_CHOICES = [
        ("quiz", "Quiz"),
        ("assignment", "Assignment"),
        ("midterm", "Midterm"),
        ("final", "Final"),
        ("participation", "Participation"),
        ("project", "Project"),
        ("lab", "Lab / practicum"),
        ("exam", "Exam"),
        ("other", "Other"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="components")
    order = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=300)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="other")
    weight = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    raw_weight = models.CharField(max_length=120, blank=True)
    formula = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)
    source_ref = models.CharField(max_length=120, blank=True)
    confidence = models.CharField(max_length=10, default="medium")
    bonus = models.BooleanField(default=False)
    is_range = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.name} ({self.weight}%)"


class AnchorEntry(models.Model):
    """Section headings confirmed by reviewers; the candidate ranker grows from these."""
    text = models.CharField(max_length=300, unique=True)
    fingerprint = models.CharField(max_length=40, blank=True)
    document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="anchors")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["text"]

    def __str__(self):
        return self.text
