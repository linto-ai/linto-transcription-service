import json
from typing import Union

from transcriptionservice.transcription.configs.sharedconfig import Config
from transcriptionservice.transcription.configs.taskconfig import (
    DiarizationConfig,
    PunctuationConfig,
    VADConfig,
)


class TranscriptionConfig(Config):
    """TranscriptionConfig parses and holds transcription request configuration.
    Expected configuration format is as follows:
    ```json
    {
      "vadConfig": obect VADConfig (WebRTC),
      "language": string (null),
      "diarizationConfig": object DiarizationConfig (null),
      "punctuationConfig": object PunctuationConfig (null),
      "enablePunctuation": boolean (false)
    }
    ```
    """

    _keys_default = {
        "vadConfig": VADConfig(),
        "language": None,
        "diarizationConfig": DiarizationConfig(),
        "punctuationConfig": PunctuationConfig(),
        "enablePunctuation": None,  # Kept for backward compatibility
        # "transcribePerChannel": False,
    }

    def __init__(self, config: Union[str, dict] = {}):
        super().__init__(config)
        self._checkConfig()

    @property
    def tasks(self) -> list:
        return [self.diarizationConfig, self.punctuationConfig]

    def _checkConfig(self):
        """Check and update field values"""
        if isinstance(self.diarizationConfig, dict):
            self.diarizationConfig = DiarizationConfig(self.diarizationConfig)
        if isinstance(self.punctuationConfig, dict):
            self.punctuationConfig = PunctuationConfig(self.punctuationConfig)
        if isinstance(self.vadConfig, dict):
            self.vadConfig = VADConfig(self.vadConfig)

        if self.language and "," in self.language:
            self.language = self.language.split(",")[0]

        if self.enablePunctuation is not None:
            self.punctuationConfig.enablePunctuation = self.enablePunctuation

    def __eq__(self, other):
        if isinstance(other, TranscriptionConfig):
            for key in self._keys_default.keys():
                if self.__getattribute__(key) != other.__getattribute__(key):
                    return False
            return True
        return False

    def __str__(self) -> str:
        return json.dumps(self.toJson())

