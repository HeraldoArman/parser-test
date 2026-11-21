from django.forms import modelformset_factory

from .models import Component

ComponentFormSet = modelformset_factory(
    Component,
    fields=["name", "kind", "weight", "note"],
    extra=1,
    can_delete=True,
)
