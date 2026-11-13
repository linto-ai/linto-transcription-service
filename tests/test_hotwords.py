import os
import sys

# Set PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import pytest

import transcriptionservice.transcription.transcription_task as tt
from transcriptionservice.transcription.configs.transcriptionconfig import (
    TranscriptionConfig,
)


def test_no_hotwords_by_default():
    config = TranscriptionConfig({"language": "fr"})
    assert config.hotwords is None
    assert config.toJson()["hotwords"] is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("LinTO, LINAGORA", "LinTO, LINAGORA"),
        ("  LinTO  ", "LinTO"),
        (["LinTO", " LINAGORA ", ""], "LinTO, LINAGORA"),
        ("", None),
        ([], None),
        (None, None),
    ],
)
def test_hotwords_normalized(value, expected):
    assert TranscriptionConfig({"hotwords": value}).hotwords == expected


@pytest.mark.parametrize("value", [42, {"term": "LinTO"}, ["LinTO", 3]])
def test_invalid_hotwords_rejected(value):
    with pytest.raises(ValueError):
        TranscriptionConfig({"hotwords": value})


def test_hotwords_survive_serialization():
    """The request config is serialized in the task info, then parsed again."""
    config = TranscriptionConfig({"language": "fr", "hotwords": ["LinTO", "LINAGORA"]})
    assert TranscriptionConfig(config.toJson()).hotwords == "LinTO, LINAGORA"
    assert TranscriptionConfig(str(config)).hotwords == "LinTO, LINAGORA"


def test_worker_args_without_hotwords():
    """Without hotwords the task keeps its 3 arguments (workers older than
    linto-stt 2.2.0 take no hotwords argument)."""
    config = TranscriptionConfig({"language": "fr"})
    assert tt.transcription_args("/opt/audio/a.wav", config) == ["/opt/audio/a.wav", True, "fr"]


def test_worker_args_with_hotwords():
    config = TranscriptionConfig({"language": "fr", "hotwords": "LinTO, LINAGORA"})
    assert tt.transcription_args("/opt/audio/a.wav", config) == [
        "/opt/audio/a.wav", True, "fr", "LinTO, LINAGORA"
    ]
