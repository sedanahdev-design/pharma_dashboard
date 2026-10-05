from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import profile_for


@login_required
def home(request):
    """Send each account straight into whatever it actually has.

    A user with exactly one service never sees a chooser - landing on a
    menu with one button is just an extra click on every single visit.
    A user with both gets the chooser; a user with neither gets a page
    that says so plainly instead of an empty navigation bar."""
    profile = profile_for(request.user)
    can_tracking = bool(profile and profile.can_use_tracking)
    can_reconcile = bool(profile and profile.can_use_reconcile)

    if can_tracking and not can_reconcile:
        return redirect("tracking:upload_list")
    if can_reconcile and not can_tracking:
        return redirect("reconcile:batch_list")
    return render(
        request,
        "home.html",
        {"can_tracking": can_tracking, "can_reconcile": can_reconcile},
    )
