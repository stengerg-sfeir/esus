"""Repositories over an in-memory Store, one class per persistence port.

CRUD, reads and filters run for real. Anything else raises
NotImplementedError with its work order — an aggregate or guard body
is specified by its pattern, not invented here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import datetime

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


def _model_list(records, model_cls):
    """Model objects from records, deduplicated by stable id."""
    out = []
    seen = set()
    if records is None:
        records = []
    elif isinstance(records, dict) or isinstance(records, (str, bytes)) \
            or not hasattr(records, '__iter__'):
        records = [records]
    for record in records:
        if isinstance(record, dict):
            key = record.get('id')
            item = model_cls(**record)
        else:
            key = getattr(record, 'id', None)
            item = record
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        out.append(item)
    return out



class WineRepository:
    ENTITY = "Wine"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_all(self, name: str = None, vintage_year: int = None, wine_type: str = None, country_of_origin: str = None, cost_price: int = None, selling_price: int = None, stock_quantity: int = None, storage_location_id: int = None) -> list[models.Wine]:
        """Lists every Wine; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if vintage_year is not None:
            criteria.append(('vintage_year', 'eq', vintage_year))
        if wine_type is not None:
            criteria.append(('wine_type', 'eq', wine_type))
        if country_of_origin is not None:
            criteria.append(('country_of_origin', 'eq', country_of_origin))
        if cost_price is not None:
            criteria.append(('cost_price', 'eq', cost_price))
        if selling_price is not None:
            criteria.append(('selling_price', 'eq', selling_price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        if storage_location_id is not None:
            criteria.append(('storage_location_id', 'eq', storage_location_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Wine(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Wine by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.WineNotFoundError)
        return models.Wine(**record)

    def create(self, name: str = None, vintage_year: int = None, wine_type: str = None, country_of_origin: str = None, cost_price: int = None, selling_price: int = None, stock_quantity: int = None, storage_location_id: int = None) -> Any:
        """Creates a new Wine. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
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
        if storage_location_id is not None:
            values['storage_location_id'] = storage_location_id
        unknown = [k for k in values if k not in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']]
        if unknown:
            raise ValueError(f"cannot create Wine from {unknown}")
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise errors.NegativeStockError(f"Wine.stock_quantity must be >= 0, got {value!r}")
        value = values.get('selling_price')
        other = values.get('cost_price')
        if value is not None and other is not None and not (value > other):
            raise errors.InvalidPricingException(f"Wine.selling_price must be > cost_price, got {value!r} vs {other!r}")
        location_id = values.get('storage_location_id')
        quantity = values.get('stock_quantity') or 0
        if location_id is not None:
            location = self._store.get('StorageLocation', 'id', location_id)
            used = sum(row.get('stock_quantity') or 0 for row in self._store.select(self.ENTITY, [('storage_location_id', 'eq', location_id)]))
            if used + quantity > location.get('maximum_capacity', 0):
                raise errors.LocationOverCapacityException(f"StorageLocation capacity exceeded for {location_id}")
        for unique_field in ['name']:
            value = values.get(unique_field)
            if value is not None and self._store.select(self.ENTITY, [(unique_field, 'eq', value)]):
                raise errors.DuplicateWineNameError(f"Wine with {unique_field}={value!r} already exists")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("storage_location_id", "StorageLocation", "id", errors.StorageLocationNotFoundError)])
        return models.Wine(**record)

    def update(self, id: int = None, name: str = None, vintage_year: int = None, wine_type: str = None, country_of_origin: str = None, cost_price: int = None, selling_price: int = None, stock_quantity: int = None, storage_location_id: int = None) -> Any:
        """Updates an existing Wine. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.WineNotFoundError(f"Wine update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['name'] = name
        if vintage_year is not None and 'vintage_year' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['vintage_year'] = vintage_year
        if wine_type is not None and 'wine_type' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['wine_type'] = wine_type
        if country_of_origin is not None and 'country_of_origin' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['country_of_origin'] = country_of_origin
        if cost_price is not None and 'cost_price' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['cost_price'] = cost_price
        if selling_price is not None and 'selling_price' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['selling_price'] = selling_price
        if stock_quantity is not None and 'stock_quantity' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['stock_quantity'] = stock_quantity
        if storage_location_id is not None and 'storage_location_id' in ['id', 'name', 'vintage_year', 'wine_type', 'country_of_origin', 'cost_price', 'selling_price', 'stock_quantity', 'storage_location_id']:
            patch['storage_location_id'] = storage_location_id
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise errors.NegativeStockError(f"Wine.stock_quantity must be >= 0, got {value!r}")
        value = patch.get('selling_price', found[0].get('selling_price'))
        other = patch.get('cost_price', found[0].get('cost_price'))
        if value is not None and other is not None and not (value > other):
            raise errors.InvalidPricingException(f"Wine.selling_price must be > cost_price, got {value!r} vs {other!r}")
        location_id = patch.get('storage_location_id', found[0].get('storage_location_id'))
        quantity = patch.get('stock_quantity', found[0].get('stock_quantity')) or 0
        if location_id is not None:
            location = self._store.get('StorageLocation', 'id', location_id)
            used = sum(row.get('stock_quantity') or 0 for row in self._store.select(self.ENTITY, [('storage_location_id', 'eq', location_id)]) if row.get(self.PK) != found[0][self.PK])
            if used + quantity > location.get('maximum_capacity', 0):
                raise errors.LocationOverCapacityException(f"StorageLocation capacity exceeded for {location_id}")
        for unique_field in ['name']:
            value = patch.get(unique_field)
            if value is not None and any(row.get(self.PK) != found[0][self.PK] for row in self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):
                raise errors.DuplicateWineNameError(f"Wine with {unique_field}={value!r} already exists")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.WineNotFoundError)
        return models.Wine(**record)

    def delete(self, id: int = None, name: str = None, vintage_year: int = None, wine_type: str = None, country_of_origin: str = None, cost_price: int = None, selling_price: int = None, stock_quantity: int = None, storage_location_id: int = None) -> None:
        """Deletes an existing Wine. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if vintage_year is not None:
            criteria.append(('vintage_year', 'eq', vintage_year))
        if wine_type is not None:
            criteria.append(('wine_type', 'eq', wine_type))
        if country_of_origin is not None:
            criteria.append(('country_of_origin', 'eq', country_of_origin))
        if cost_price is not None:
            criteria.append(('cost_price', 'eq', cost_price))
        if selling_price is not None:
            criteria.append(('selling_price', 'eq', selling_price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        if storage_location_id is not None:
            criteria.append(('storage_location_id', 'eq', storage_location_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.WineNotFoundError(f"Wine delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_wine_by_name(self, name: str = None) -> models.Wine | None:
        """Retrieves a wine record by its unique name, ensuring name uniqueness in the system. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.WineNotFoundError(f"Wine lookup matched {len(found)} records")
        record = found[0]
        return models.Wine(**record)

    def get_wine_count_by_type(self, id: int = None) -> dict[str, int]:
        """Returns the total number of wines categorized by wine type (e.g., red, white, rosé, sparkling). [mechanical count by field]"""
        counts = {}
        for row in self._store.select(self.ENTITY, []):
            key = row.get('wine_type')
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
        return counts


class StorageLocationRepository:
    ENTITY = "StorageLocation"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_all(self, zone_name: str = None, row_number: int = None, shelf_number: int = None, maximum_capacity: int = None) -> list[models.StorageLocation]:
        """Lists every StorageLocation; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if zone_name is not None:
            criteria.append(('zone_name', 'eq', zone_name))
        if row_number is not None:
            criteria.append(('row_number', 'eq', row_number))
        if shelf_number is not None:
            criteria.append(('shelf_number', 'eq', shelf_number))
        if maximum_capacity is not None:
            criteria.append(('maximum_capacity', 'eq', maximum_capacity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.StorageLocation(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one StorageLocation by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.StorageLocationNotFoundError)
        return models.StorageLocation(**record)

    def create(self, zone_name: str = None, row_number: int = None, shelf_number: int = None, maximum_capacity: int = None) -> Any:
        """Creates a new StorageLocation. [crud:create: STANDARD_CRUD]"""
        values = {}
        if zone_name is not None:
            values['zone_name'] = zone_name
        if row_number is not None:
            values['row_number'] = row_number
        if shelf_number is not None:
            values['shelf_number'] = shelf_number
        if maximum_capacity is not None:
            values['maximum_capacity'] = maximum_capacity
        unknown = [k for k in values if k not in ['id', 'zone_name', 'row_number', 'shelf_number', 'maximum_capacity']]
        if unknown:
            raise ValueError(f"cannot create StorageLocation from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.StorageLocation(**record)

    def update(self, id: int = None, zone_name: str = None, row_number: int = None, shelf_number: int = None, maximum_capacity: int = None) -> Any:
        """Updates an existing StorageLocation. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.StorageLocationNotFoundError(f"StorageLocation update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'zone_name', 'row_number', 'shelf_number', 'maximum_capacity']:
            patch['id'] = id
        if zone_name is not None and 'zone_name' in ['id', 'zone_name', 'row_number', 'shelf_number', 'maximum_capacity']:
            patch['zone_name'] = zone_name
        if row_number is not None and 'row_number' in ['id', 'zone_name', 'row_number', 'shelf_number', 'maximum_capacity']:
            patch['row_number'] = row_number
        if shelf_number is not None and 'shelf_number' in ['id', 'zone_name', 'row_number', 'shelf_number', 'maximum_capacity']:
            patch['shelf_number'] = shelf_number
        if maximum_capacity is not None and 'maximum_capacity' in ['id', 'zone_name', 'row_number', 'shelf_number', 'maximum_capacity']:
            patch['maximum_capacity'] = maximum_capacity
        new_capacity = patch.get('maximum_capacity')
        if new_capacity is not None:
            used = sum(row.get('stock_quantity') or 0 for row in self._store.select('Wine', [('storage_location_id', 'eq', found[0][self.PK])]))
            if used > new_capacity:
                raise errors.LocationOverCapacityException(f"StorageLocation.maximum_capacity capacity below assigned quantity")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.StorageLocationNotFoundError)
        return models.StorageLocation(**record)

    def delete(self, id: int = None, zone_name: str = None, row_number: int = None, shelf_number: int = None, maximum_capacity: int = None) -> None:
        """Deletes an existing StorageLocation. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if zone_name is not None:
            criteria.append(('zone_name', 'eq', zone_name))
        if row_number is not None:
            criteria.append(('row_number', 'eq', row_number))
        if shelf_number is not None:
            criteria.append(('shelf_number', 'eq', shelf_number))
        if maximum_capacity is not None:
            criteria.append(('maximum_capacity', 'eq', maximum_capacity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.StorageLocationNotFoundError(f"StorageLocation delete matched no records")
        for record in found:
            if self._store.select('Wine', [('storage_location_id', 'eq', record[self.PK])]):
                raise ValueError(f"StorageLocation is still assigned to Wine records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_location_by_zone_name(self, zone_name: str = None) -> models.StorageLocation | None:
        """Retrieves a storage location by its zone name (e.g., 'Main Cellar'), ensuring unique zone identification. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if zone_name is not None:
            criteria.append(('zone_name', 'eq', zone_name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.StorageLocationNotFoundError(f"StorageLocation lookup matched {len(found)} records")
        record = found[0]
        return models.StorageLocation(**record)

    def get_location_utilization_rate(self, location_id: int = None) -> float:
        """Calculates and returns the current utilization rate (as a percentage) of a storage location based on current bottle count and maximum capacity. [mechanical utilization]"""
        record = self._store.get(self.ENTITY, self.PK, location_id, error=errors.StorageLocationNotFoundError)
        used = sum(row.get('stock_quantity') or 0 for row in self._store.select('Wine', [('storage_location_id', 'eq', record['id'])]))
        capacity = record.get('maximum_capacity') or 0
        if not capacity:
            return 0.0
        return float(used) / capacity * 100.0

    def get_total_storage_capacity(self, id: int = None) -> int:
        """Returns the sum of maximum capacities across all storage locations in the system. [AGGREGATE_BY_FK via answered slots: target_field=maximum_capacity, aggregate_func=SUM]"""
        total = 0
        for record in self._store.select(self.ENTITY, []):
            total += record.get('maximum_capacity') or 0
        return total
