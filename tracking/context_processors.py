from .version import VERSION


def app_version(request):
    """Exposes APP_VERSION to every template - see version.py for why."""
    return {"APP_VERSION": VERSION}
