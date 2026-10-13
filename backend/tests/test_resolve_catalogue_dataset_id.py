"""Published dataset_id resolution (PDF human ids vs Excel DDI ids)."""
from __future__ import annotations

from app.db.repositories.datasets import resolve_catalogue_dataset_id


def test_pdf_uuid_id_uses_human_table_id():
    tid = resolve_catalogue_dataset_id(
        {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "table_id": "DDI_DES_DEL_VS_1_P79",
        },
        0,
    )
    assert tid == "DDI_DES_DEL_VS_1_P79"


def test_excel_ddi_id_preferred_over_source_table_label():
    tid = resolve_catalogue_dataset_id(
        {
            "id": "DDI_DEL_DES_VS_B14_RURAL_2024_V1",
            "table_id": "Table : B-14",
        },
        0,
    )
    assert tid == "DDI_DEL_DES_VS_B14_RURAL_2024_V1"


def test_explicit_dataset_id_wins():
    tid = resolve_catalogue_dataset_id(
        {
            "dataset_id": "DDI_DES_DEL_VS_CUSTOM",
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "table_id": "DDI_DES_DEL_VS_1_P79",
        },
        0,
    )
    assert tid == "DDI_DES_DEL_VS_CUSTOM"
