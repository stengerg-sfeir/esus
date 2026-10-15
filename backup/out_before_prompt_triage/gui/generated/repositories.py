"""Repositories over an in-memory Store, one class per persistence port.

CRUD, reads and filters run for real. Anything else raises
NotImplementedError with its work order — an aggregate or guard body
is specified by its pattern, not invented here.
"""

import models
import errors
from store import Store, match_criterion


def _record_values(data, field_names):
    """A dataclass or dict entity argument as a `{field: value}` dict."""
    if data is None:
        return {}
    if isinstance(data, dict):
        return {name: data.get(name) for name in field_names}
    return {name: getattr(data, name, None) for name in field_names}



class WineRepository:
    ENTITY = "Wine"
    PK = "wine_id"

    def __init__(self, store):
        self._store = store


    def create_wine(self, wine_name: Any = None, vintage_year: int = None, wine_type: Any = None, country_of_origin: Any = None, cost_price: float = None, selling_price: float = None, stock_quantity: int = None) -> models.Wine:
        """Creates a new wine entry with the provided details. [crud:create: STANDARD_CRUD]"""
        values = {}
        if wine_name is not None:
            values['wine_name'] = wine_name
        if vintage_year is not None:
            values['vintage_year'] = vintage_year
        if wine_type is not None:
            values['wine_type'] = wine_type
        if country_of_origin is not None:
            values['country_of_origin'] = country_of_origin
        if cost_price is not None:
            values['cost_price'] = cost_price
        if selling_price is not None:
            values['selling_price'] = selling_price
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        unknown = [k for k in values if k not in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']]
        if unknown:
            raise ValueError(f"cannot create Wine from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("primary_location_id", "StorageLocation", "location_id", errors.StorageLocationNotFoundError)])
        return models.Wine(**record)

    def read_all_wines(self) -> List[models.Wine]:
        """Reads all wines in the system. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Wine(**r) for r in found]

    def read_wine_by_id(self, wine_id: int = None) -> models.Wine:
        """Reads a specific wine by its unique identifier. [crud:read_one: STANDARD_CRUD]"""
        record = self._store.get(self.ENTITY, self.PK, wine_id, error=errors.WineNotFoundError)
        return models.Wine(**record)

    def update_wine(self, wine_id: int = None, wine_name: Any = None, vintage_year: int = None, wine_type: Any = None, country_of_origin: Any = None, cost_price: float = None, selling_price: float = None, stock_quantity: int = None) -> models.Wine:
        """Updates an existing wine's details. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if wine_id is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'wine_id')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'wine_id'")
            field, operator = matched
            criteria.append((field, operator, wine_id))
        if wine_name is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'wine_name')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'wine_name'")
            field, operator = matched
            criteria.append((field, operator, wine_name))
        if vintage_year is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'vintage_year')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'vintage_year'")
            field, operator = matched
            criteria.append((field, operator, vintage_year))
        if wine_type is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'wine_type')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'wine_type'")
            field, operator = matched
            criteria.append((field, operator, wine_type))
        if country_of_origin is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'country_of_origin')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'country_of_origin'")
            field, operator = matched
            criteria.append((field, operator, country_of_origin))
        if cost_price is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'cost_price')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'cost_price'")
            field, operator = matched
            criteria.append((field, operator, cost_price))
        if selling_price is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'selling_price')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'selling_price'")
            field, operator = matched
            criteria.append((field, operator, selling_price))
        if stock_quantity is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'stock_quantity')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'stock_quantity'")
            field, operator = matched
            criteria.append((field, operator, stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.WineNotFoundError(f"Wine update matched {len(found)} records")
        patch = {}
        if wine_id is not None and 'wine_id' in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']:
            patch['wine_id'] = wine_id
        if wine_name is not None and 'wine_name' in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']:
            patch['wine_name'] = wine_name
        if vintage_year is not None and 'vintage_year' in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']:
            patch['vintage_year'] = vintage_year
        if wine_type is not None and 'wine_type' in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']:
            patch['wine_type'] = wine_type
        if country_of_origin is not None and 'country_of_origin' in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']:
            patch['country_of_origin'] = country_of_origin
        if cost_price is not None and 'cost_price' in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']:
            patch['cost_price'] = cost_price
        if selling_price is not None and 'selling_price' in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']:
            patch['selling_price'] = selling_price
        if stock_quantity is not None and 'stock_quantity' in ['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id']:
            patch['stock_quantity'] = stock_quantity
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.WineNotFoundError)
        return models.Wine(**record)

    def delete_wine(self, wine_id: int = None) -> Any:
        """Deletes a wine from the system. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if wine_id is not None:
            matched = match_criterion(['wine_id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'primary_location_id'], 'wine_id')
            if matched is None:
                raise ValueError(f"cannot filter Wine by 'wine_id'")
            field, operator = matched
            criteria.append((field, operator, wine_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.WineNotFoundError(f"Wine delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class StorageLocationRepository:
    ENTITY = "StorageLocation"
    PK = "location_id"

    def __init__(self, store):
        self._store = store


    def create_location(self, zone_name: Any = None, row_number: int = None, shelf_number: int = None, max_bottle_capacity: int = None) -> models.StorageLocation:
        """Creates a new storage location. [crud:create: STANDARD_CRUD]"""
        values = {}
        if zone_name is not None:
            values['zone_name'] = zone_name
        if row_number is not None:
            values['row_number'] = row_number
        if shelf_number is not None:
            values['shelf_number'] = shelf_number
        if max_bottle_capacity is not None:
            values['max_bottle_capacity'] = max_bottle_capacity
        unknown = [k for k in values if k not in ['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity']]
        if unknown:
            raise ValueError(f"cannot create StorageLocation from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.StorageLocation(**record)

    def read_all_locations(self) -> List[models.StorageLocation]:
        """Reads all storage locations in the system. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.StorageLocation(**r) for r in found]

    def read_location_by_id(self, location_id: int = None) -> models.StorageLocation:
        """Reads a specific storage location by its unique identifier. [crud:read_one: STANDARD_CRUD]"""
        record = self._store.get(self.ENTITY, self.PK, location_id, error=errors.StorageLocationNotFoundError)
        return models.StorageLocation(**record)

    def update_location(self, location_id: int = None, zone_name: Any = None, row_number: int = None, shelf_number: int = None, max_bottle_capacity: int = None) -> models.StorageLocation:
        """Updates an existing storage location's details. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if location_id is not None:
            matched = match_criterion(['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity'], 'location_id')
            if matched is None:
                raise ValueError(f"cannot filter StorageLocation by 'location_id'")
            field, operator = matched
            criteria.append((field, operator, location_id))
        if zone_name is not None:
            matched = match_criterion(['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity'], 'zone_name')
            if matched is None:
                raise ValueError(f"cannot filter StorageLocation by 'zone_name'")
            field, operator = matched
            criteria.append((field, operator, zone_name))
        if row_number is not None:
            matched = match_criterion(['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity'], 'row_number')
            if matched is None:
                raise ValueError(f"cannot filter StorageLocation by 'row_number'")
            field, operator = matched
            criteria.append((field, operator, row_number))
        if shelf_number is not None:
            matched = match_criterion(['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity'], 'shelf_number')
            if matched is None:
                raise ValueError(f"cannot filter StorageLocation by 'shelf_number'")
            field, operator = matched
            criteria.append((field, operator, shelf_number))
        if max_bottle_capacity is not None:
            matched = match_criterion(['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity'], 'max_bottle_capacity')
            if matched is None:
                raise ValueError(f"cannot filter StorageLocation by 'max_bottle_capacity'")
            field, operator = matched
            criteria.append((field, operator, max_bottle_capacity))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.StorageLocationNotFoundError(f"StorageLocation update matched {len(found)} records")
        patch = {}
        if location_id is not None and 'location_id' in ['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity']:
            patch['location_id'] = location_id
        if zone_name is not None and 'zone_name' in ['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity']:
            patch['zone_name'] = zone_name
        if row_number is not None and 'row_number' in ['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity']:
            patch['row_number'] = row_number
        if shelf_number is not None and 'shelf_number' in ['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity']:
            patch['shelf_number'] = shelf_number
        if max_bottle_capacity is not None and 'max_bottle_capacity' in ['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity']:
            patch['max_bottle_capacity'] = max_bottle_capacity
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.StorageLocationNotFoundError)
        return models.StorageLocation(**record)

    def delete_location(self, location_id: int = None) -> Any:
        """Deletes a storage location from the system. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if location_id is not None:
            matched = match_criterion(['location_id', 'zone_name', 'row_number', 'shelf_number', 'max_bottle_capacity'], 'location_id')
            if matched is None:
                raise ValueError(f"cannot filter StorageLocation by 'location_id'")
            field, operator = matched
            criteria.append((field, operator, location_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.StorageLocationNotFoundError(f"StorageLocation delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None
