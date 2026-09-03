from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("", views.upload_list, name="upload_list"),
    path("uploads/new/", views.upload_create, name="upload_create"),
    path("uploads/<int:pk>/", views.upload_detail, name="upload_detail"),
    path("uploads/<int:pk>/delete/", views.upload_delete, name="upload_delete"),
    path("uploads/<int:pk>/export/", views.export_excel, name="export_excel"),
    path("uploads/<int:pk>/categories/add/", views.category_add, name="category_add"),
    path("uploads/<int:pk>/categories/<int:cat_id>/rename/", views.category_rename, name="category_rename"),
    path("uploads/<int:pk>/categories/<int:cat_id>/delete/", views.category_delete, name="category_delete"),
    path("uploads/<int:pk>/categories/<int:cat_id>/items/add/", views.item_add, name="item_add"),
    path("uploads/<int:pk>/items/<int:item_id>/delete/", views.item_delete, name="item_delete"),
    path("uploads/<int:pk>/import-targets/", views.import_targets, name="import_targets"),
]
