"""Application errors, one class per registered failure."""



class FileNotFoundError(OSError):
    """Raised when the input file does not exist."""


class MalformedCSVError(ValueError):
    """Raised when the CSV file is malformed or has inconsistent row lengths."""
