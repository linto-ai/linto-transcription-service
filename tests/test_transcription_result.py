# Set PYTHONPATH
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from transcriptionservice.transcription.transcription_result import (
    DiarizationSegment,
    TranscriptionResult,
)

DIARIZATION_RESULT = {
    "speakers": [
        {"spk_id": "Griogy", "duration": 10.0, "nbr_seg": 1, "spk_id_score": 0.83},
    ],
    "segments": [
        {"seg_begin": 0.0, "seg_end": 10.0, "spk_id": "Griogy", "seg_id": 0},
    ],
}


def make_result():
    transcription = {
        "words": [
            {"word": "hello", "start": 0.0, "end": 1.0, "conf": 1.0},
            {"word": "world", "start": 1.0, "end": 2.0, "conf": 1.0},
        ],
        "confidence-score": 1.0,
    }
    return TranscriptionResult([(transcription, 0.0)])


class TestDiarizationSpeakers:
    def test_set_diarization_result_keeps_speakers(self):
        result = make_result()
        result.setDiarizationResult(DIARIZATION_RESULT)
        assert result.diarizationSpeakers == DIARIZATION_RESULT["speakers"]

    def test_final_result_contains_speakers(self):
        result = make_result()
        result.setDiarizationResult(DIARIZATION_RESULT)
        final = result.final_result()
        assert final["diarization_speakers"] == DIARIZATION_RESULT["speakers"]

    def test_no_speakers_field(self):
        result = make_result()
        result.setDiarizationResult({"segments": DIARIZATION_RESULT["segments"]})
        assert result.diarizationSpeakers == []
        assert result.final_result()["diarization_speakers"] == []

    def test_from_dict_tolerates_absence(self):
        result = make_result()
        result.setDiarizationResult(DIARIZATION_RESULT)
        final = result.final_result()
        del final["diarization_speakers"]
        restored = TranscriptionResult.fromDict(final)
        assert restored.diarizationSpeakers == []

    def test_from_dict_restores_speakers(self):
        result = make_result()
        result.setDiarizationResult(DIARIZATION_RESULT)
        restored = TranscriptionResult.fromDict(result.final_result())
        assert restored.diarizationSpeakers == DIARIZATION_RESULT["speakers"]


class TestDiarizationSegmentFromDict:
    def test_ignores_unknown_keys(self):
        segment = DiarizationSegment.fromDict(
            {
                "seg_begin": 0.0,
                "seg_end": 1.0,
                "spk_id": "spk1",
                "seg_id": 0,
                "spk_id_score": 0.9,
            }
        )
        assert segment.spk_id == "spk1"
        assert segment.json == {
            "seg_begin": 0.0,
            "seg_end": 1.0,
            "spk_id": "spk1",
            "seg_id": 0,
        }

    def test_segments_with_extra_keys(self):
        result = make_result()
        diarization = {
            "speakers": [],
            "segments": [
                {
                    "seg_begin": 0.0,
                    "seg_end": 10.0,
                    "spk_id": "spk1",
                    "seg_id": 0,
                    "extra_key": "ignored",
                }
            ],
        }
        result.setDiarizationResult(diarization)
        assert len(result.diarizationSegments) == 1
