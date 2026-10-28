class TransientProviderError(Exception):
    """429 / 5xx style failure. Safe to retry."""


class PermanentProviderError(Exception):
    """Invalid recipient or rejected message. Do not retry."""
