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


class TestNestedDiarizationSegments:
    def test_several_segments_inside_a_long_turn(self):
        # spk1 speaks from 0 to 120 s, spk2 says two short words during that turn, spk3 speaks after
        words = [{"word": f"w{t}", "start": float(t), "end": t + 0.5, "conf": 1.0} for t in range(0, 120, 5)]
        words.append({"word": "next", "start": 122.0, "end": 123.0, "conf": 1.0})
        result = TranscriptionResult([({"words": words, "confidence-score": 1.0}, 0.0)])
        result.setDiarizationResult({
            "segments": [
                {"seg_begin": 0.0, "seg_end": 120.0, "spk_id": "spk1", "seg_id": 0},
                {"seg_begin": 30.0, "seg_end": 31.0, "spk_id": "spk2", "seg_id": 1},
                {"seg_begin": 60.0, "seg_end": 61.0, "spk_id": "spk2", "seg_id": 2},
                {"seg_begin": 121.0, "seg_end": 130.0, "spk_id": "spk3", "seg_id": 3},
            ],
        })
        assert [s.spk_id for s in result.diarizationSegments] == ["spk1", "spk3"]
        assert [(s.speaker_id, len(s.words)) for s in result.segments] == [("spk1", 24), ("spk3", 1)]
