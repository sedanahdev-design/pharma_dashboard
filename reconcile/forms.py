from django import forms

from .models import Memo, MovementBatch, Pharmacy


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    """Accepts one or more workbooks selected together."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultiFileInput(attrs={"accept": ".xlsx,.xlsm", "multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)) and data:
            return [single(d, initial) for d in data]
        cleaned = single(data or None, initial)
        return [cleaned] if cleaned else []


class MovementBatchForm(forms.ModelForm):
    movements_file = MultiFileField(
        label="ملفات الحركة (xlsx) - يمكن اختيار أكثر من ملف معاً",
        help_text=(
            "ملف الموسع (المبيعات والمردودات) وملف المناقلات إن وُجد. اخترهما معاً "
            "(Ctrl/Cmd أثناء الاختيار) ويميّز التطبيق بينهما تلقائياً من أعمدة كل ملف. "
            "المناقلات لا تظهر في ملف الموسع، فبدون ملف مناقلات يبقى عمود «المتناقل» صفراً."
        ),
    )

    class Meta:
        model = MovementBatch
        fields = ["name", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "مثال: كشف حركات 9-2026"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class PharmacyForm(forms.ModelForm):
    class Meta:
        model = Pharmacy
        fields = ["cost_center", "short_name"]
        widgets = {
            "cost_center": forms.TextInput(
                attrs={"placeholder": "انسخ الاسم حرفياً من عمود مركز الكلفة"}
            ),
            "short_name": forms.TextInput(attrs={"placeholder": "مثال: ليليان فارس"}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    def clean_cost_center(self):
        value = (self.cleaned_data["cost_center"] or "").strip()
        qs = Pharmacy.objects.filter(owner=self.owner, cost_center=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("هذا المركز معرَّف مسبقاً عندك.")
        return value


class MemoUploadForm(forms.ModelForm):
    memo_file = forms.FileField(
        label="ملف المذكرة (xlsx)",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.xlsm"}),
    )

    class Meta:
        model = Memo
        fields = ["note"]
        widgets = {"note": forms.TextInput(attrs={"placeholder": "ملاحظة اختيارية"})}


class ImportPharmaciesForm(forms.Form):
    """One-click creation of the pharmacies found inside an uploaded كشف.

    Typing ten Arabic branch names by hand is both tedious and the single
    likeliest way to break the whole comparison - one wrong character and
    a branch silently matches nothing - so the names are offered exactly
    as the file spells them."""

    centers = forms.MultipleChoiceField(
        label="مراكز الكلفة الموجودة في الكشف", widget=forms.CheckboxSelectMultiple, required=True
    )

    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["centers"].choices = [(c, c) for c in choices]
