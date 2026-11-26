# Oracle findings

Total confirmed executions: **97**

- **passed**: 66
- **under_specified**: 24
- **coverage_gap: ambiguous action**: 6
- **coverage_gap: missing action**: 1

## coverage_gap: ambiguous action

- `prompt_04` / `complete_task`: no generated method matches 'complete_task'
- `prompt_13` / `report_low_stock`: no generated method matches 'report_low_stock'
- `prompt_26` / `close_loan`: no generated method matches 'close_loan'
- `prompt_29` / `get_orders_with_customer_name_repository_call`: ambiguous action binding: CustomerRepository.read_one, OrderRepository.read_one
- `prompt_46` / `track_clients`: no generated method matches 'track_clients'
- `prompt_46` / `know_outstanding_invoices`: no generated method matches 'check_outstanding_invoices'

## coverage_gap: missing action

- `prompt_18` / `export_contacts`: no generated method matches 'export_contacts' for export

## under_specified

- `prompt_02` / `division_by_zero_error`: cannot resolve given entity 'numbers'
- `prompt_04` / `add_task`: create case expects task.description = 'Write documentation' but supplies 'task description'
- `prompt_04` / `list_tasks`: task_1.description is 'value3', expected 'Write documentation'
- `prompt_08` / `filter_by_category`: no generated method matches 'filter_products'
- `prompt_08` / `display_low_quantity`: no generated method matches 'filter_products'
- `prompt_11` / `search_books`: no generated method matches 'search_books'
- `prompt_12` / `search_by_name`: no generated method matches 'search_by_name'
- `prompt_12` / `filter_by_email_domain`: no generated method matches 'filter_by_email_domain'
- `prompt_13` / `search_products`: no generated method matches 'search_products'
- `prompt_13` / `filter_by_category`: no generated method matches 'filter_by_category'
- `prompt_15` / `list_products_by_name_asc`: list case supplies a sort direction but no sort field; the directive does not determine which field to sort
- `prompt_15` / `list_products_by_price_desc`: list case supplies a sort direction but no sort field; the directive does not determine which field to sort
- `prompt_15` / `list_products_by_quantity_asc`: list case supplies a sort direction but no sort field; the directive does not determine which field to sort
- `prompt_17` / `search_by_name`: ambiguous action binding: ProductRepository.filter_by_category, ProductRepository.filter_by_max_price, ProductRepository.filter_by_min_quantity, ProductRepository.find_all_with_filters, ProductRepository.find_all_products_with_filters
- `prompt_17` / `combinable_filters`: ambiguous action binding: ProductRepository.filter_by_category, ProductRepository.filter_by_max_price, ProductRepository.filter_by_min_quantity
- `prompt_18` / `import_invalid_row_rejected`: expected invalid_row, no error was raised
- `prompt_21` / `list_orders_by_customer`: expected state field 'order.date' is not declared on Order
- `prompt_23` / `create_tag_association`: expected relation 'post.tags' is represented by join model PostTag
- `prompt_40` / `notify-on-confirm`: no generated method matches 'confirm_order'
- `prompt_44` / `know_stock_level`: no generated method matches 'know_stock_level'
- `prompt_52` / `book_not_available_while_borrowed`: no generated method matches 'check_availability'
- `prompt_53` / `place_order_with_sufficient_stock`: raised AttributeError: 'str' object has no attribute 'get'; expected None
- `prompt_58` / `manage_customers_and_retrieve_info`: no generated method matches 'manage_customers'
- `prompt_58` / `continue_operation_when_external_unavailable`: no generated method matches 'operate_application'

