"""Application errors, one class per registered failure."""



class NegativeStockError(ValueError):
    """Raised when a wine's stock quantity is attempted to be set to or below zero."""


class InvalidPricingException(ValueError):
    """Raised when a wine's selling price is not strictly greater than its cost price."""


class DuplicateWineNameError(ValueError):
    """Raised when attempting to add a wine with a name that already exists in the system."""


class LocationOverCapacityException(RuntimeError):
    """Raised when attempting to assign a wine bottle to a storage location that is already at or exceeds its maximum bottle capacity."""


class WineNotFoundError(LookupError):
    """Raised when attempting to access a wine that does not exist in the system."""


class StorageLocationNotFoundError(LookupError):
    """Raised when attempting to access a storage location that does not exist in the system."""


class InvalidWineTypeError(ValueError):
    """Raised when an invalid wine type (not red, white, rosé, or sparkling) is provided."""


class NegativeCapacityError(ValueError):
    """Raised when a storage location's capacity is set to or below zero."""
