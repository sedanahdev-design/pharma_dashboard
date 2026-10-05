"""Which services the current user may see - needed by base.html on every
page so the top navigation never offers a link that would 403."""

from .models import profile_for


def services(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"CAN_TRACKING": False, "CAN_RECONCILE": False, "USER_LABEL": ""}
    profile = profile_for(user)
    return {
        "CAN_TRACKING": bool(profile and profile.can_use_tracking),
        "CAN_RECONCILE": bool(profile and profile.can_use_reconcile),
        "USER_LABEL": (profile.display_name if profile and profile.display_name else user.get_username()),
    }
