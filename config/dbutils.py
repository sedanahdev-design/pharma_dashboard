"""Database helpers shared by both services.

Kept at project level rather than inside either app because both the
monthly موسع import and the كشف حركات import hit the same wall: a single
upload can carry tens of thousands of rows, and the obvious way to write
them - build the list, hand it to bulk_create - holds every row twice
over in memory at once.
"""


def insert_in_chunks(model, objects, chunk=2000):
    """Write an iterable of unsaved model instances in fixed-size batches.

    bulk_create() calls list() on whatever it is given, so passing it a
    generator still materialises everything before the first INSERT. The
    only way to keep peak memory flat is to slice the stream ourselves
    and let each batch be garbage-collected once written.

    On a 512MB instance this is the difference between an import that
    completes and a worker killed mid-request - which reaches the browser
    as a bare HTTP 502 with nothing in it to explain what went wrong.

    Returns the number of rows written.
    """
    batch = []
    total = 0
    for obj in objects:
        batch.append(obj)
        if len(batch) >= chunk:
            model.objects.bulk_create(batch)
            total += len(batch)
            batch.clear()
    if batch:
        model.objects.bulk_create(batch)
        total += len(batch)
    return total
