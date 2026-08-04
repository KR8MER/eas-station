"""Regression tests: list views must not load audio blobs or geometry.

Several models carry multi-megabyte ``LargeBinary`` columns (EASMessage has
six, EASDecodedAudio seven, ManualEASActivation ten) and CAPAlert carries a
PostGIS geometry plus ``raw_json``. List views render none of that -- at
most they report whether a blob is populated -- but a plain ORM query loads
every column, so a single page moved gigabytes to compute a few booleans.
That is what turned the FCC reports page into a 502 gateway error, and the
same pattern was present in the other /logs tabs and the audio listings.

These tests pin the query shapes: the helpers on the models must select
blob-presence as a SQL NULL test rather than transferring the bytes, and
the deferring helper must cover every LargeBinary column on its model.
"""

from __future__ import annotations

from app_core.models import EASMessage, ManualEASActivation

# Column names that must never appear in a list view's SELECT list.
BLOB_COLUMNS = {
    "EASMessage": [
        "audio_data",
        "eom_audio_data",
        "same_audio_data",
        "attention_audio_data",
        "tts_audio_data",
        "buffer_audio_data",
    ],
}


def _select_list(query) -> str:
    """Return the query's SELECT list (everything before FROM), collapsed."""
    sql = " ".join(str(query).split())
    head = sql.split(" FROM ", 1)[0]
    return head.lower()


def test_eas_message_summary_query_selects_no_blobs(app):
    """EASMessage.summary_query() must not transfer any audio column."""
    with app.app_context():
        select_list = _select_list(EASMessage.summary_query())
        for column in BLOB_COLUMNS["EASMessage"]:
            # The column may appear inside an "IS NOT NULL" test, but must
            # never be selected as a value.
            assert f"eas_messages.{column} as" not in select_list, (
                f"summary_query() transfers {column}"
            )


def test_eas_message_summary_query_reports_blob_presence(app):
    """The has_* flags must be computed in SQL, one per audio column."""
    with app.app_context():
        select_list = _select_list(EASMessage.summary_query())
        assert select_list.count("is not null") == len(BLOB_COLUMNS["EASMessage"]), (
            "expected one SQL NULL test per audio column"
        )


def test_eas_message_summary_to_dict_matches_to_dict_keys(app):
    """summary_to_dict must be a drop-in for to_dict (same keys)."""
    with app.app_context():
        columns = {c["name"] for c in EASMessage.summary_query().column_descriptions
                   if isinstance(c, dict) and "name" in c}
        assert "has_audio_blob" in columns
        assert "has_buffer_audio" in columns

    # to_dict's key set, taken from an unsaved instance (no DB needed).
    expected = set(EASMessage().to_dict().keys())
    produced = set(
        EASMessage.summary_to_dict(
            _StubRow(
                id=1, cap_alert_id=None, alert_identifier=None, same_header="",
                audio_filename="", text_filename="", tts_warning=None,
                tts_provider=None, text_payload=None, metadata_payload=None,
                created_at=None, has_audio_blob=False, has_eom_blob=False,
                has_same_audio=False, has_attention_audio=False,
                has_tts_audio=False, has_buffer_audio=False,
            )
        ).keys()
    )
    assert produced == expected


def test_eas_message_without_audio_defers_every_blob(app):
    """without_audio() must cover all six LargeBinary columns."""
    with app.app_context():
        select_list = _select_list(EASMessage.without_audio())
        for column in EASMessage.AUDIO_BLOB_COLUMNS:
            assert f"eas_messages.{column}" not in select_list, (
                f"without_audio() still selects {column}"
            )


def test_eas_message_blob_column_list_is_complete():
    """AUDIO_BLOB_COLUMNS must list every LargeBinary column on EASMessage."""
    import sqlalchemy as sa

    actual = {
        column.name
        for column in EASMessage.__table__.columns
        if isinstance(column.type, sa.LargeBinary)
    }
    assert set(EASMessage.AUDIO_BLOB_COLUMNS) == actual


def test_manual_activation_without_audio_defers_every_blob(app):
    """without_audio() must cover all ten LargeBinary columns."""
    with app.app_context():
        select_list = _select_list(ManualEASActivation.without_audio())
        for column in ManualEASActivation.AUDIO_BLOB_COLUMNS:
            assert f"manual_eas_activations.{column}" not in select_list, (
                f"without_audio() still selects {column}"
            )


def test_manual_activation_blob_column_list_is_complete():
    """AUDIO_BLOB_COLUMNS must list every LargeBinary column on the model.

    A blob added to the model but omitted from this tuple would silently
    stop being deferred, reintroducing the bug.
    """
    import sqlalchemy as sa

    actual = {
        column.name
        for column in ManualEASActivation.__table__.columns
        if isinstance(column.type, sa.LargeBinary)
    }
    assert set(ManualEASActivation.AUDIO_BLOB_COLUMNS) == actual


class _StubRow:
    """Minimal stand-in for a SQLAlchemy Row with attribute access."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
