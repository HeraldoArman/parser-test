import csv
import json
from pathlib import Path

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ComponentFormSet
from .models import AnchorEntry, Batch, Document
from .services import parse_document, sync_components

ALLOWED = {".pdf", ".docx", ".xlsx"}
MAX_BYTES = 20 * 1024 * 1024


def upload(request):
    recent = Batch.objects.all()[:10]
    if request.method == "POST":
        files = request.FILES.getlist("files")
        if not files:
            messages.error(request, "No files received.")
            return redirect("assessments:upload")
        batch = Batch.objects.create(note=request.POST.get("note", "").strip())
        accepted = 0
        for uploaded in files:
            suffix = Path(uploaded.name).suffix.lower()
            if suffix not in ALLOWED:
                messages.error(request, f"{uploaded.name}: unsupported type {suffix or '?'}")
                continue
            if uploaded.size > MAX_BYTES:
                messages.error(request, f"{uploaded.name}: larger than 20 MB")
                continue
            document = Document.objects.create(
                batch=batch, file=uploaded, original_name=uploaded.name[:255],
                size=uploaded.size, mime=uploaded.content_type or "",
            )
            parse_document(document)
            accepted += 1
        if not accepted:
            batch.delete()
            return redirect("assessments:upload")
        messages.success(request, f"Parsed {accepted} file(s).")
        return redirect("assessments:batch", pk=batch.pk)
    return render(request, "assessments/upload.html", {"recent": recent})


def batch_detail(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    documents = batch.documents.prefetch_related("components")
    return render(request, "assessments/batch_detail.html",
                  {"batch": batch, "documents": documents})


def review(request, pk):
    document = get_object_or_404(Document, pk=pk)
    formset = ComponentFormSet(
        request.POST if request.method == "POST" else None,
        queryset=document.components.all(),
        prefix="components",
    )
    action = request.POST.get("action", "")

    if request.method == "POST" and action == "select":
        try:
            index = int(request.POST.get("candidate", ""))
        except ValueError:
            return HttpResponseBadRequest("invalid candidate")
        document.selected = index
        document.result["selected"] = index
        document.save(update_fields=["selected", "result"])
        sync_components(document, index)
        return redirect("assessments:review", pk=document.pk)

    if request.method == "POST" and action in {"save", "approve"}:
        if formset.is_valid():
            rows = formset.save(commit=False)
            for deleted in formset.deleted_objects:
                deleted.delete()
            for order, row in enumerate(rows):
                row.document = document
                row.order = order
                row.save()
            if action == "approve":
                document.status = "approved"
                document.approved_at = timezone.now()
                document.save(update_fields=["status", "approved_at"])
                heading = ""
                if document.candidates and document.selected is not None:
                    heading = document.candidates[document.selected].get("heading", "")
                if heading:
                    AnchorEntry.objects.get_or_create(
                        text=heading[:300],
                        defaults={"fingerprint": document.fingerprint, "document": document},
                    )
                messages.success(request, "Approved.")
            else:
                messages.success(request, "Saved.")
                if document.status == "approved":
                    document.status = "needs_review"
                    document.approved_at = None
                    document.save(update_fields=["status", "approved_at"])
            return redirect("assessments:review", pk=document.pk)
        messages.error(request, "Fix the highlighted rows.")

    if request.method == "POST" and action == "reject":
        document.status = "needs_review"
        document.approved_at = None
        document.save(update_fields=["status", "approved_at"])
        return redirect("assessments:review", pk=document.pk)

    selected = document.selected
    raw_section = ""
    if selected is not None and 0 <= selected < len(document.candidates):
        raw_section = document.candidates[selected].get("raw_section", "")
    return render(request, "assessments/review.html", {
        "document": document, "formset": formset,
        "candidates": document.candidates, "selected": selected,
        "raw_section": raw_section,
    })


def _document_payload(document: Document) -> dict:
    return {
        "id": document.pk,
        "file": document.original_name,
        "status": document.status,
        "fingerprint": document.fingerprint,
        "selected_candidate": document.selected,
        "total": float(sum((c.weight or 0) for c in document.components.all())),
        "reasons": document.reasons,
        "approved_at": document.approved_at.isoformat() if document.approved_at else None,
        "components": [
            {
                "name": c.name, "kind": c.kind,
                "weight": float(c.weight) if c.weight is not None else None,
                "raw_weight": c.raw_weight, "note": c.note,
                "source_ref": c.source_ref, "bonus": c.bonus,
            }
            for c in document.components.all()
        ],
    }


def export_batch(request, pk, fmt):
    batch = get_object_or_404(Batch, pk=pk)
    documents = batch.documents.prefetch_related("components")
    payload = [_document_payload(d) for d in documents]
    if fmt == "json":
        response = HttpResponse(
            json.dumps(payload, indent=2, ensure_ascii=False),
            content_type="application/json",
        )
        response["Content-Disposition"] = f'attachment; filename="batch-{batch.pk}.json"'
        return response
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="batch-{batch.pk}.csv"'
    writer = csv.writer(response)
    writer.writerow(["document_id", "file", "status", "fingerprint", "component_order",
                     "name", "kind", "weight", "bonus", "note", "source_ref", "approved_at"])
    for document in documents:
        base = [document.pk, document.original_name, document.status, document.fingerprint]
        approved = document.approved_at.isoformat() if document.approved_at else ""
        rows = list(document.components.all())
        if not rows:
            writer.writerow(base + ["", "", "", "", "", "", approved])
        for component in rows:
            writer.writerow(base + [
                component.order, component.name, component.kind,
                component.weight if component.weight is not None else "",
                "yes" if component.bonus else "", component.note,
                component.source_ref, approved,
            ])
    return response


def coverage(request):
    from .extraction import ranker
    statuses = list(Document.objects.values("status").annotate(count=Count("id")).order_by("-count"))
    families = list(
        Document.objects.exclude(fingerprint="")
        .values("fingerprint")
        .annotate(count=Count("id"), approved=Count("id", filter=Q(status="approved")))
        .order_by("-count")[:50]
    )
    total = Document.objects.count()
    return render(request, "assessments/coverage.html",
                  {"statuses": statuses, "families": families, "total": total,
                   "ranker": ranker.load()})


@require_POST
def reparse(request, pk):
    document = get_object_or_404(Document, pk=pk)
    document.result = {}
    document.blocks = []
    document.save(update_fields=["result", "blocks"])
    parse_document(document, force=True)
    return redirect("assessments:review", pk=document.pk)
