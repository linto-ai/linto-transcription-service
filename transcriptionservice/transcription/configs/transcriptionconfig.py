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
      "hotwords": string or list of strings (null),
      "diarizationConfig": object DiarizationConfig (null),
      "punctuationConfig": object PunctuationConfig (null),
      "enablePunctuation": boolean (false)
    }
    ```
    """

    _keys_default = {
        "vadConfig": VADConfig(),
        "language": None,
        "hotwords": None,
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

        self.hotwords = self._normalizeHotwords(self.hotwords)

        if self.enablePunctuation is not None:
            self.punctuationConfig.enablePunctuation = self.enablePunctuation

    @staticmethod
    def _normalizeHotwords(hotwords) -> Union[str, None]:
        """Hotwords are sent to the transcription worker as one free-text string
        (linto-stt `hotwords`). A list of terms is joined with ", "; an empty
        value means no hotwords."""
        if hotwords is None:
            return None
        if isinstance(hotwords, list):
            if not all(isinstance(term, str) for term in hotwords):
                raise ValueError("hotwords must be a string or a list of strings")
            hotwords = ", ".join(term.strip() for term in hotwords if term.strip())
        if not isinstance(hotwords, str):
            raise ValueError("hotwords must be a string or a list of strings")
        return hotwords.strip() or None

    def __eq__(self, other):
        if isinstance(other, TranscriptionConfig):
            for key in self._keys_default.keys():
                if self.__getattribute__(key) != other.__getattribute__(key):
                    return False
            return True
        return False

    def __str__(self) -> str:
        return json.dumps(self.toJson())

