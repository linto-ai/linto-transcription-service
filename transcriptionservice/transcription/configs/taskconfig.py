""" This module contains the configuration classe for the transcription subtasks"""

import re
from faulthandler import is_enabled
from typing import Union

from transcriptionservice.transcription.configs.sharedconfig import Config
from transcriptionservice.transcription.utils.audio import validate_vad_method

HEX24_PATTERN = re.compile(r"^[0-9a-f]{24}$")
SPEAKER_ID_MAX_COLLECTIONS = 16


class SpeakerIdentificationError(Exception):
    """Exception raised when the speakerIdentificationConfig field is invalid."""

    status_code = 400


class SpeakerIdentificationForbidden(SpeakerIdentificationError):
    """Exception raised when referenced collections do not belong to the declared organization."""

    status_code = 403


class TaskConfig(Config):
    service_type = None
    task_name = None
    serviceName = None
    serviceQueue = None

    def __init__(self, config: Union[str, dict] = {}):
        super().__init__(config)
        self._checkConfig()
        self.isEnabled = False  # If the service is necessary for the request
        self.isAvailable = False  # If the service is resolvable (Available or interchangeable)
        self.serviceQueue = None

    def setService(self, serviceName: str, serviceQueue: str) -> None:
        self.isAvailable = True
        self.serviceName = serviceName
        self.serviceQueue = serviceQueue


class PunctuationConfig(TaskConfig):
    """PunctuationConfig parses and holds punctuation related configuration.
    Expected configuration format is as follows:
    ```json
    {
      "enableDiarization": boolean (false),
      "serviceName: str (None)
    }
    ```
    """

    service_type = "punctuation"
    task_name = "punctuation_task"

    _keys_default = {
        "enablePunctuation": False,
        "serviceName": None,
        "serviceQueue": None,
    }

    def __init__(self, config: Union[str, dict] = {}):
        super().__init__(config)
        self._checkConfig()
        self.isEnabled = self.enablePunctuation  # If the service is necessary for the request


class DiarizationConfig(TaskConfig):
    """DiarizationConfig parses and holds diarization related configuration.
    Expected configuration format is as follows:
    ```json
    {
      "enableDiarization": boolean (false),
      "numberOfSpeaker": integer (null),
      "maxNumberOfSpeaker": integer (null),
      "speakerIdentification": string (null),
      "speakerIdentificationConfig": object (null),
      "serviceName": string (null),
      "serviceQueue": string (null)
    }
    ```
    speakerIdentificationConfig format (replaces the legacy speakerIdentification field):
    ```json
    {
      "organizationId": "24 hexadecimal characters (required)",
      "collections": ["spkid_{organizationId}_{24 hexadecimal characters}", ...],
      "speakers": "*",
      "minSimilarity": null
    }
    ```
    """

    service_type = "diarization"
    task_name = "diarization_task"

    _keys_default = {
        "enableDiarization": False,
        "numberOfSpeaker": None,
        "maxNumberOfSpeaker": None,
        "speakerIdentification": None,
        "speakerIdentificationConfig": None,
        "serviceName": None,
        "serviceQueue": None,
    }

    def __init__(self, config: Union[str, dict] = {}):
        super().__init__(config)
        self._checkConfig()
        self.isEnabled = self.enableDiarization

    def _checkConfig(self):
        """Check diarization parameters."""
        if self.speakerIdentificationConfig is not None:
            self._checkSpeakerIdentificationConfig()
        if self.enableDiarization in ["true", 1, True]:
            self.enableDiarization = True
            if type(self.numberOfSpeaker) is int:
                if self.numberOfSpeaker <= 0:
                    self.numberOfSpeaker = None
                elif self.numberOfSpeaker == 1:
                    if self.speakerIdentificationConfig is not None:
                        raise SpeakerIdentificationError(
                            "speakerIdentificationConfig requires diarization (numberOfSpeaker=1 disables it)"
                        )
                    self.enableDiarization = False
                    return

            if type(self.maxNumberOfSpeaker) is int:
                if self.numberOfSpeaker is not None:
                    self.maxNumberOfSpeaker = self.numberOfSpeaker
                else:
                    if self.maxNumberOfSpeaker <= 0:
                        self.maxNumberOfSpeaker = None
        else:
            self.enableDiarization = False

    def _checkSpeakerIdentificationConfig(self):
        """Check and normalize the speakerIdentificationConfig field."""
        config = self.speakerIdentificationConfig
        if not isinstance(config, dict):
            raise SpeakerIdentificationError("speakerIdentificationConfig must be an object")

        if self.enableDiarization not in ["true", 1, True]:
            raise SpeakerIdentificationError(
                "speakerIdentificationConfig requires enableDiarization to be enabled"
            )

        # The new object field takes precedence: the legacy speakerIdentification field is ignored
        if self.speakerIdentification is not None:
            self.speakerIdentification = None

        organization_id = config.get("organizationId")
        if not isinstance(organization_id, str) or not HEX24_PATTERN.match(organization_id):
            raise SpeakerIdentificationError(
                "speakerIdentificationConfig.organizationId is required and must be a 24 character hexadecimal identifier"
            )

        collections = config.get("collections")
        if not isinstance(collections, list) or not len(collections):
            raise SpeakerIdentificationError(
                "speakerIdentificationConfig.collections is required and must be a non-empty list"
            )
        if len(collections) > SPEAKER_ID_MAX_COLLECTIONS:
            raise SpeakerIdentificationError(
                "speakerIdentificationConfig.collections is limited to {} collections".format(
                    SPEAKER_ID_MAX_COLLECTIONS
                )
            )
        collection_pattern = re.compile(
            r"^spkid_" + organization_id + r"_[0-9a-f]{24}$"
        )
        for collection in collections:
            if not isinstance(collection, str) or not collection_pattern.match(collection):
                raise SpeakerIdentificationForbidden(
                    "speaker identification collections do not belong to the declared organization"
                )

        speakers = config.get("speakers", "*")
        if speakers is None:
            speakers = "*"
        if speakers != "*" and not (
            isinstance(speakers, list) and all(isinstance(s, str) for s in speakers)
        ):
            raise SpeakerIdentificationError(
                'speakerIdentificationConfig.speakers must be "*" or a list of speaker identifiers'
            )

        min_similarity = config.get("minSimilarity")
        if min_similarity is not None and (
            isinstance(min_similarity, bool) or not isinstance(min_similarity, (int, float))
        ):
            raise SpeakerIdentificationError(
                "speakerIdentificationConfig.minSimilarity must be a number"
            )

        self.speakerIdentificationConfig = {
            "organizationId": organization_id,
            "collections": collections,
            "speakers": speakers,
            "minSimilarity": min_similarity,
        }

class VADConfig(Config):
    """VADConfig parses and holds VAD related configuration.
    Expected configuration format is as follows:
    ```json
    {
      "enableVAD": boolean (true),
      "methodName": string ("WebRTC"),
      "minDuration": float (0.0)
      "maxDuration": float (1200.0),
    }
    ```
    """

    _keys_default = {
        "enableVAD": True,
        "methodName": "WebRTC",
        "minDuration": 0.0,
        "maxDuration": 1200.0,
    }

    def __init__(self, config: Union[str, dict] = {}):
        super().__init__(config)
        self._checkConfig()
        self.isEnabled = self.enableVAD

    def _checkConfig(self):
        """Check VAD parameters."""

        if self.methodName is None and not self.enableVAD:
            pass
        else:
            self.methodName = validate_vad_method(self.methodName)
