from collections.abc import Generator, Iterable
from itertools import islice
from typing import Any


def batched(iterable: Iterable[Any], size: int) -> Generator:
    if size < 1:
        raise ValueError("n must be at least one")
    it = iter(iterable)
    while batch := tuple(islice(it, size)):
        yield batch
