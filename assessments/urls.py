from django.urls import path

from . import views

app_name = "assessments"

urlpatterns = [
    path("", views.upload, name="upload"),
    path("coverage/", views.coverage, name="coverage"),
    path("batches/<int:pk>/", views.batch_detail, name="batch"),
    path("batches/<int:pk>/export/<str:fmt>/", views.export_batch, name="export"),
    path("documents/<int:pk>/", views.review, name="review"),
    path("documents/<int:pk>/reparse/", views.reparse, name="reparse"),
]
