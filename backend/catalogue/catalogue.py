"""Public catalogue API — thin re-export shim over the split submodules.

`catalogue.py` used to hold every catalogue function in one 1300-line file.
It's now split by concern (db/users/kyds/nco_aliases/classifications/datasets/
query/dashboard), but every external caller still does
``from catalogue import catalogue as _cat`` and calls ``_cat.push_to_catalogue``
etc. — this module re-exports the same public names so none of those call
sites had to change.
"""
from catalogue.db import get_connection, init_schema
from catalogue.users import create_user, get_user_by_email
from catalogue.kyds import (
    save_kyds_entry,
    get_latest_kyds_responses,
    get_own_latest_kyds_entry,
)
from catalogue.nco_aliases import (
    NCO_2015_CSV_PATH,
    seed_nco_2015,
    lookup_nco_alias,
    upsert_nco_aliases,
)
from catalogue.classification_standards import (
    list_standards as list_classification_standards,
    create_standard as create_classification_standard,
    select_standard as select_classification_standard,
    delete_standard as delete_classification_standard,
    ensure_selected_loaded as ensure_classification_standard_loaded,
)
from catalogue.classifications import (
    get_metadata_group_classifications,
    get_definition_facts,
    get_recent_classification_columns,
    update_metadata_group_classification_column,
)
from catalogue.datasets import (
    STANDARD_CONCEPTS,
    push_to_catalogue,
)
from catalogue.query import (
    get_catalogue_dataset,
    list_catalogue_datasets,
    query_dataset_rows,
    search_catalogue_datasets,
)
from catalogue.dashboard import list_dashboard

__all__ = [
    "get_connection",
    "init_schema",
    "create_user",
    "get_user_by_email",
    "save_kyds_entry",
    "get_latest_kyds_responses",
    "get_own_latest_kyds_entry",
    "NCO_2015_CSV_PATH",
    "seed_nco_2015",
    "lookup_nco_alias",
    "upsert_nco_aliases",
    "list_classification_standards",
    "create_classification_standard",
    "select_classification_standard",
    "delete_classification_standard",
    "ensure_classification_standard_loaded",
    "get_metadata_group_classifications",
    "get_definition_facts",
    "get_recent_classification_columns",
    "update_metadata_group_classification_column",
    "STANDARD_CONCEPTS",
    "list_catalogue_datasets",
    "search_catalogue_datasets",
    "get_catalogue_dataset",
    "query_dataset_rows",
    "push_to_catalogue",
    "list_dashboard",
]
