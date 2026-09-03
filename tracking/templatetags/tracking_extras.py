from django import template

register = template.Library()


@register.filter
def pct_class(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "bad"
    if v >= 70:
        return "good"
    if v >= 40:
        return "warn"
    return "bad"


@register.filter
def qty(value):
    """Format a quantity: drop trailing .0, keep up to 2 decimals otherwise."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    if v == int(v):
        return f"{int(v):,}".replace(",", "،")
    return f"{v:,.2f}".replace(",", "،")


@register.filter
def pct(value):
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return value
