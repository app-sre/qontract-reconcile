import time
from collections.abc import Iterable

from reconcile.utils.helpers import match_patterns


def record_timestamp(path: str) -> None:
    with open(path, "w", encoding="locale") as file_object:
        file_object.write(str(time.time()))


def sync_tag(
    tags: Iterable[str] | None,
    tags_exclude: Iterable[str] | None,
    candidate: str,
) -> bool:
    """
    Determine if the candidate tag should sync, tags_exclude check take precedence.
    :param tags: regex patterns to filter, match means to sync, None means no filter
    :param tags_exclude: regex patterns to filter, match means not to sync, None means no filter
    :param candidate: tag to check
    :return: bool, True means to sync, False means not to sync
    """
    if tags:
        if tags_exclude:
            # both tags and tags_exclude provided
            return not match_patterns(
                tags_exclude,
                candidate,
            ) and match_patterns(
                tags,
                candidate,
            )
        else:
            # only tags provided
            return match_patterns(tags, candidate)
    elif tags_exclude:
        # only tags_exclude provided
        return not match_patterns(tags_exclude, candidate)
    else:
        # neither tags nor tags_exclude provided
        return True
