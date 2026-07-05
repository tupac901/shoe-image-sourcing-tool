"""Register optional image decoders used by Pillow."""

try:
    import pillow_avif  # noqa: F401
except Exception:
    pass
