from django import forms

from .models import Category, MonthlyUpload, TargetItem


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    """A FileField that accepts one or more files selected together. The
    view figures out which uploaded file is which (sales vs. a price
    report) by sniffing its columns, so the person never has to label
    them - they just select everything for the month at once."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultiFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)) and data:
            return [single_file_clean(d, initial) for d in data]
        # No files selected (data is None, an empty list/tuple, or falsy) -
        # let FileField.clean raise its usual "required" error when needed.
        cleaned = single_file_clean(data or None, initial)
        return [cleaned] if cleaned else []


class MonthlyUploadForm(forms.ModelForm):
    sales_file = MultiFileField(
        label="ملف موسع الشهر (xlsx)",
        help_text=(
            "الملف الذي يحتوي على كل المبيعات مع عمود الشروحات 5. إن كان هذا الملف يتضمّن عموده "
            "الخاص \"السعر\"، يشتق التطبيق منه أسعار هذا الشهر تلقائياً - لا حاجة لرفع أي ملف أسعار "
            "آخر في هذه الحالة. (بإمكانك أيضاً اختيار هذا الملف مع تقرير أصناف الأورانج معاً هنا - "
            "Ctrl/Cmd أثناء الاختيار - بدل استخدام الحقل التالي، والتطبيق سيميّز بينهما تلقائياً.)"
        ),
    )
    price_file = forms.FileField(
        required=False,
        label="تقرير أصناف الأورانج لهذا الشهر (اختياري)",
        help_text=(
            "اختياري - فقط إن لم يكن ملف موسع أعلاه يحتوي عموده الخاص بالسعر. أي تقرير فيه عمودا "
            "الكمية والقيمة لكل صنف - يُشتق منه سعر الوحدة (القيمة ÷ الكمية) خاص بهذا الشهر بالضبط. "
            "إن تركته فارغاً ولم يكن لملف موسع عمود سعر خاص به، يُستخدم آخر سعر معروف من شهر سابق تلقائياً."
        ),
    )
    clone_from = forms.ModelChoiceField(
        queryset=MonthlyUpload.objects.none(),
        required=False,
        label="نسخ التصنيفات المستهدفة من شهر سابق (اختياري)",
    )
    clone_prices_too = forms.BooleanField(
        required=False,
        initial=True,
        label="نسخ الأسعار أيضاً من نفس الشهر المختار",
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

    def __init__(self, *args, owner=None, **kwargs):
        """The "clone from a previous month" list is built per user.

        It starts empty and is filled here rather than being declared as
        MonthlyUpload.objects.all(): a ModelChoiceField also *validates*
        against its queryset, so scoping it to the owner is what stops
        one account from cloning - and thereby reading - the other
        account's category names by posting someone else's upload id."""
        super().__init__(*args, **kwargs)
        self.owner = owner
        if owner is not None:
            self.fields["clone_from"].queryset = MonthlyUpload.objects.filter(owner=owner)


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
