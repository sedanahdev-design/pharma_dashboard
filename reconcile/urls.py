from django.urls import path

from . import views

app_name = "reconcile"

urlpatterns = [
    path("", views.batch_list, name="batch_list"),
    path("new/", views.batch_create, name="batch_create"),
    path("<int:pk>/", views.batch_detail, name="batch_detail"),
    path("<int:pk>/delete/", views.batch_delete, name="batch_delete"),
    path("<int:pk>/export/", views.batch_export, name="batch_export"),
    path("pharmacies/", views.pharmacy_list, name="pharmacy_list"),
    path("pharmacies/add/", views.pharmacy_create, name="pharmacy_create"),
    path("pharmacies/import/", views.pharmacy_import, name="pharmacy_import"),
    path("pharmacies/<int:pk>/delete/", views.pharmacy_delete, name="pharmacy_delete"),
    path("pharmacies/<int:pk>/memo/", views.memo_upload, name="memo_upload"),
    path("memos/<int:pk>/delete/", views.memo_delete, name="memo_delete"),
]
