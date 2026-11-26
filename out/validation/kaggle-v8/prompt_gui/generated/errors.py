"""Application errors, one class per registered failure."""



from __future__ import annotations

class NegativeStockError(ValueError):
    """Raised when an attempt is made to set a wine's stock quantity to a negative value."""


class LocationOverCapacityException(ValueError):
    """Raised when adding a wine to a storage location would exceed that location's maximum bottle capacity."""


class InvalidPricingException(ValueError):
    """Raised when a wine's selling price is not strictly greater than its cost price."""


class DuplicateWineNameError(KeyError):
    """Raised when attempting to add a wine with a name that already exists in the system."""


class StorageLocationNotFoundError(LookupError):
    """Raised when a requested storage location is not found in the system."""


class WineNotFoundError(LookupError):
    """Raised when a requested wine is not found in the system."""
