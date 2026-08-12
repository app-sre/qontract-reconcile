"""Constants for qontract-api."""

# HTTP Headers
REQUEST_ID_HEADER = "X-Request-ID"

# Gzip request decompression limits (protect against decompression bombs)
MAX_GZIP_COMPRESSED_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_GZIP_DECOMPRESSED_SIZE = 100 * 1024 * 1024  # 100 MB
