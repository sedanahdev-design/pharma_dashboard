from django import forms

from .models import Category, MonthlyUpload, TargetItem


class MonthlyUploadForm(forms.ModelForm):
    sales_file = forms.FileField(
        label="ملف موسع الشهر (xlsx)",
        help_text="الملف الذي يحتوي على كل المبيعات مع عمود الشروحات 5",
    )
    clone_from = forms.ModelChoiceField(
        queryset=MonthlyUpload.objects.all(),
        required=False,
        label="نسخ التصنيفات المستهدفة من شهر سابق (اختياري)",
    )
    targets_file = forms.FileField(
        required=False,
        label="ملف تارغيت + كاتيغوري (اختياري)",
        help_text="لاستيراد التصنيفات والأصناف المستهدفة مباشرة من ملف Excel",
    )

    class Meta:
        model = MonthlyUpload
        fields = ["name", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "مثال: شهر 8 - 2026"}),
            "notes": forms.Textarea(attrs={"rows": 2, "placeholder": "ملاحظات اختيارية"}),
        }
        labels = {"name": "اسم الشهر / الدفعة", "notes": "ملاحظات"}


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": "اسم التصنيف كما يظهر في عمود الشروحات 5", "autofocus": True}
            )
        }
        labels = {"name": ""}


class TargetItemForm(forms.ModelForm):
    class Meta:
        model = TargetItem
        fields = ["item_name"]
        widgets = {
            "item_name": forms.TextInput(attrs={"placeholder": "اسم الصنف المستهدف بالضبط كما في ملف موسع"})
        }
        labels = {"item_name": ""}


class ImportTargetsForm(forms.Form):
    targets_file = forms.FileField(label="ملف تارغيت + كاتيغوري (xlsx)")
