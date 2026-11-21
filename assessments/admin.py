from django.contrib import admin

from .models import AnchorEntry, Batch, Component, Document


class ComponentInline(admin.TabularInline):
    model = Component
    extra = 0
    fields = ("order", "name", "kind", "weight", "bonus", "note")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "batch", "status", "fingerprint", "extractor_version",
                    "approved_at")
    list_filter = ("status", "fingerprint")
    search_fields = ("original_name", "sha256")
    readonly_fields = ("result", "blocks")
    inlines = [ComponentInline]


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("pk", "note", "created_at")
    date_hierarchy = "created_at"


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ("name", "document", "kind", "weight", "bonus")
    list_filter = ("kind", "bonus")
    search_fields = ("name",)


@admin.register(AnchorEntry)
class AnchorEntryAdmin(admin.ModelAdmin):
    list_display = ("text", "fingerprint", "created_at")
    search_fields = ("text",)
