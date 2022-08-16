def safe_resource_id(s: str) -> str:
    """Sanitize a string into a valid terraform resource id"""
    res = s.translate({ord(c): "_" for c in "."})
    res = res.replace("*", "_star")
    return res
