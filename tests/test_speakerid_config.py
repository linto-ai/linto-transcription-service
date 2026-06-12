import json

# Set PYTHONPATH
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import pytest

from transcriptionservice.transcription.configs.taskconfig import (
    DiarizationConfig,
    SpeakerIdentificationError,
    SpeakerIdentificationForbidden,
)
from transcriptionservice.transcription.configs.transcriptionconfig import (
    TranscriptionConfig,
)

ORG_ID = "64ff00112233445566778899"
OTHER_ORG_ID = "65ee00112233445566778899"
COLLECTION = f"spkid_{ORG_ID}_65aa00112233445566778899"


def make_config(**speaker_id_fields):
    config = {
        "enableDiarization": True,
        "speakerIdentificationConfig": {
            "organizationId": ORG_ID,
            "collections": [COLLECTION],
            **speaker_id_fields,
        },
    }
    return config


class TestSpeakerIdentificationConfigValidation:
    def test_valid_minimal(self):
        config = DiarizationConfig(make_config())
        assert config.enableDiarization is True
        assert config.speakerIdentificationConfig == {
            "organizationId": ORG_ID,
            "collections": [COLLECTION],
            "speakers": "*",
            "minSimilarity": None,
        }
        assert config.speakerIdentification is None

    def test_valid_full(self):
        config = DiarizationConfig(
            make_config(speakers=["label:65cc00112233445566778899"], minSimilarity=0.7)
        )
        assert config.speakerIdentificationConfig["speakers"] == [
            "label:65cc00112233445566778899"
        ]
        assert config.speakerIdentificationConfig["minSimilarity"] == 0.7

    def test_valid_from_json_string(self):
        config = DiarizationConfig(json.dumps(make_config()))
        assert config.speakerIdentificationConfig["collections"] == [COLLECTION]

    def test_valid_within_transcription_config(self):
        config = TranscriptionConfig(
            json.dumps({"diarizationConfig": make_config()})
        )
        assert (
            config.diarizationConfig.speakerIdentificationConfig["organizationId"]
            == ORG_ID
        )
        # toJson must serialize the normalized object
        assert (
            config.toJson()["diarizationConfig"]["speakerIdentificationConfig"][
                "speakers"
            ]
            == "*"
        )

    def test_requires_diarization(self):
        config = make_config()
        config["enableDiarization"] = False
        with pytest.raises(SpeakerIdentificationError) as error:
            DiarizationConfig(config)
        assert error.value.status_code == 400

    def test_number_of_speaker_one_disables_diarization(self):
        config = make_config()
        config["numberOfSpeaker"] = 1
        with pytest.raises(SpeakerIdentificationError) as error:
            DiarizationConfig(config)
        assert error.value.status_code == 400

    def test_not_an_object(self):
        with pytest.raises(SpeakerIdentificationError):
            DiarizationConfig(
                {"enableDiarization": True, "speakerIdentificationConfig": "*"}
            )

    def test_missing_organization_id(self):
        config = make_config()
        del config["speakerIdentificationConfig"]["organizationId"]
        with pytest.raises(SpeakerIdentificationError) as error:
            DiarizationConfig(config)
        assert error.value.status_code == 400

    @pytest.mark.parametrize(
        "organization_id", ["64ff", "64FF00112233445566778899", 1234, None, "g4ff00112233445566778899"]
    )
    def test_bad_organization_id(self, organization_id):
        with pytest.raises(SpeakerIdentificationError) as error:
            DiarizationConfig(make_config(organizationId=organization_id))
        assert error.value.status_code == 400

    @pytest.mark.parametrize("collections", [None, [], "not-a-list"])
    def test_bad_collections(self, collections):
        with pytest.raises(SpeakerIdentificationError) as error:
            DiarizationConfig(make_config(collections=collections))
        assert error.value.status_code == 400

    def test_too_many_collections(self):
        collections = [
            f"spkid_{ORG_ID}_{i:024x}" for i in range(17)
        ]
        with pytest.raises(SpeakerIdentificationError) as error:
            DiarizationConfig(make_config(collections=collections))
        assert error.value.status_code == 400

    def test_max_collections_accepted(self):
        collections = [
            f"spkid_{ORG_ID}_{i:024x}" for i in range(16)
        ]
        config = DiarizationConfig(make_config(collections=collections))
        assert len(config.speakerIdentificationConfig["collections"]) == 16

    @pytest.mark.parametrize(
        "collection",
        [
            f"spkid_{OTHER_ORG_ID}_65aa00112233445566778899",  # foreign organization
            f"spkid_{ORG_ID}_65aa",  # bad collection id
            f"spkid_{ORG_ID}_65AA00112233445566778899",  # uppercase
            "65aa00112233445566778899",  # missing prefix
            42,  # not a string
        ],
    )
    def test_foreign_collection_is_forbidden(self, collection):
        with pytest.raises(SpeakerIdentificationForbidden) as error:
            DiarizationConfig(make_config(collections=[COLLECTION, collection]))
        assert error.value.status_code == 403

    def test_object_takes_precedence_over_legacy(self):
        config = make_config()
        config["speakerIdentification"] = "*"
        diarization_config = DiarizationConfig(config)
        assert diarization_config.speakerIdentification is None
        assert diarization_config.speakerIdentificationConfig is not None

    def test_legacy_only_is_unchanged(self):
        diarization_config = DiarizationConfig(
            {"enableDiarization": True, "speakerIdentification": "*"}
        )
        assert diarization_config.speakerIdentification == "*"
        assert diarization_config.speakerIdentificationConfig is None

    @pytest.mark.parametrize("speakers", [42, "John", [42], {"a": 1}])
    def test_bad_speakers(self, speakers):
        with pytest.raises(SpeakerIdentificationError) as error:
            DiarizationConfig(make_config(speakers=speakers))
        assert error.value.status_code == 400

    @pytest.mark.parametrize("min_similarity", ["0.5", True, []])
    def test_bad_min_similarity(self, min_similarity):
        with pytest.raises(SpeakerIdentificationError) as error:
            DiarizationConfig(make_config(minSimilarity=min_similarity))
        assert error.value.status_code == 400
