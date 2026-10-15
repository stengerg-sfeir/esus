"""Services. A method with the same name as a repository method delegates
to it; anything else raises NotImplementedError with its work order.
"""

import models
import errors



class WineLocationService:

    def __init__(self, repos):
        self._repos = repos


    def assign_wine_to_location(self, wine_id: int = None, location_id: int = None) -> models.Wine:
        """Assigns a wine to a storage location, ensuring the location's capacity is not exceeded. [gap NO_PATTERN_IN_DOMAIN: QUOTA_CAPACITY_GUARD refused (QUOTA_CAPACITY_GUARD returns boolean/none, but this method returns entity (Wine))]"""
        raise NotImplementedError(
            "WineLocationService.assign_wine_to_location: gap NO_PATTERN_IN_DOMAIN: QUOTA_CAPACITY_GUARD refused (QUOTA_CAPACITY_GUARD returns boolean/none, but this method returns entity (Wine))")

    def remove_wine_from_location(self, wine_id: int = None) -> models.Wine:
        """Removes a wine from its assigned storage location. [no same-name repository method to delegate to]"""
        raise NotImplementedError(
            "WineLocationService.remove_wine_from_location: STANDARD_CRUD")

    def get_wine_by_location(self, location_id: int = None) -> List[models.Wine]:
        """Retrieves all wines assigned to a specific storage location. [pattern FILTER_BY_FIELD: no mechanical reading]"""
        raise NotImplementedError(
            "WineLocationService.get_wine_by_location: pattern FILTER_BY_FIELD: no mechanical reading")
