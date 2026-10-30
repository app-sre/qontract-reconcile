"""App-interface GraphQL path normalization."""


def normalize_app_interface_path(path: str) -> str:
    """Normalize an app-interface GraphQL path to its repository-root-relative path.

    GraphQL exposes app-interface file paths relative to the schema root (e.g.
    "/access/users/alice.yml"), but the underlying repository stores those files
    under a "data/" prefix (e.g. "data/access/users/alice.yml"). VCS reads and
    writes need the repository-root-relative form.
    """
    normalized = path.strip()
    if normalized == "data" or normalized.startswith("data/"):
        return normalized
    return f"data/{normalized.lstrip('/')}"
