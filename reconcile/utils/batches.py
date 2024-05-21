from itertools import islice


def batched(iterable, size):
    if size < 1:
        raise ValueError("n must be at least one")
    it = iter(iterable)
    while batch := tuple(islice(it, size)):
        yield batch
