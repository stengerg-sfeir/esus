"""Application errors, one class per registered failure."""



from __future__ import annotations

class NegativeStockError(ValueError):
    """Raised when an attempt is made to set a wine's stock quantity to a negative value."""


class InvalidPricingException(ValueError):
    """Raised when a wine's selling price is not strictly greater than its cost price."""


class LocationOverCapacityException(ValueError):
    """Raised when attempting to assign a wine bottle to a storage location that would exceed its defined maximum bottle capacity."""


class DuplicateWineNameError(LookupError):
    """Raised when trying to add a wine with a name that already exists in the system."""


class StorageLocationNotFoundError(KeyError):
    """Raised when a requested storage location is not found in the system during lookup or assignment."""


class WineNotFoundError(KeyError):
    """Raised when a requested wine by ID is not found in the system during lookup or retrieval."""
