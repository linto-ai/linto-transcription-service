"""Diarization routing between a fast engine with a speaker ceiling (Nemotron, 8 speakers)
and a fallback engine without one (pyannote).

Enabled when DIARIZATION_FAST_SERVICE and DIARIZATION_FALLBACK_SERVICE are set. Requests
with serviceName null or "auto" are routed, explicit service names keep working as before.
"""
import logging
import os
from typing import Optional, Tuple

AUTO_SERVICE_NAME = "auto"
DEFAULT_FAST_MAX_SPEAKERS = 7


class DiarizationRouting:
    def __init__(self, services: dict, fast_name: str, fallback_name: str, fast_max_speakers: Optional[int] = None):
        """services: {service_name: Service} of type diarization, as listed by discovery"""
        self.services = services or {}
        self.fast_name = fast_name
        self.fallback_name = fallback_name
        self._fast_max_speakers = fast_max_speakers

    @classmethod
    def from_env(cls, services: dict) -> "DiarizationRouting":
        max_speakers = os.environ.get("DIARIZATION_FAST_MAX_SPEAKERS")
        return cls(
            services,
            os.environ.get("DIARIZATION_FAST_SERVICE"),
            os.environ.get("DIARIZATION_FALLBACK_SERVICE"),
            int(max_speakers) if max_speakers else None,
        )

    @property
    def configured(self) -> bool:
        return bool(self.fast_name and self.fallback_name)

    @property
    def fast(self):
        """The fast service, only if one of its instances answered discovery: its workers run
        the threads pool and answer even when busy, so silence means it is gone."""
        service = self.services.get(self.fast_name)
        if service is None:
            return None
        if any(instance.get("responding", True) for instance in service.instances):
            return service
        return None

    @property
    def fallback(self):
        return self.services.get(self.fallback_name)

    @property
    def fast_max_speakers(self) -> int:
        """Highest speaker count trusted from the fast engine: env override, else the
        ceiling the worker registered minus one (a result at the ceiling may be saturated)."""
        if self._fast_max_speakers is not None:
            return self._fast_max_speakers
        info = getattr(self.fast, "info", None)
        if isinstance(info, dict) and isinstance(info.get("max_speakers"), int):
            return info["max_speakers"] - 1
        return DEFAULT_FAST_MAX_SPEAKERS

    def applies(self, diarization_config) -> bool:
        return self.configured and diarization_config.serviceName in (None, AUTO_SERVICE_NAME)

    def plan(self, diarization_config) -> Tuple[object, Optional[object]]:
        """Return (service to run first, service to rerun on if the first one saturates)."""
        fast, fallback = self.fast, self.fallback
        if fast is None and fallback is None:
            raise RoutingError(f"No diarization service available ({self.fast_name}, {self.fallback_name})")
        if fast is None:
            logging.warning(f"Diarization routing: {self.fast_name} unavailable, using {self.fallback_name}")
            return fallback, None
        count = diarization_config.numberOfSpeaker
        if isinstance(count, int) and count > self.fast_max_speakers:
            if fallback is None:
                logging.warning(
                    f"Diarization routing: {count} speakers requested but {self.fallback_name} is unavailable, "
                    f"using {self.fast_name} (at most {self.fast_max_speakers + 1} speakers)"
                )
                return fast, None
            return fallback, None
        if fallback is None:
            logging.warning(f"Diarization routing: {self.fallback_name} unavailable, no fallback on saturation")
        return fast, fallback

    def should_fall_back(self, result) -> bool:
        """True when the fast engine used all its speaker slots: the audio may hold more speakers."""
        if not isinstance(result, dict):
            return False
        if result.get("saturated"):
            return True
        return len(result.get("speakers", [])) > self.fast_max_speakers

    def auto_entry(self) -> Optional[dict]:
        """Virtual "auto" diarization service for /list-services, or None when routing is off."""
        if not self.configured:
            return None
        available = [s for s in (self.fast, self.fallback) if s is not None]
        if not available:
            return None
        info = dict(available[0].info) if isinstance(available[0].info, dict) else {}
        infos = [s.info for s in available if isinstance(s.info, dict)]
        info["speaker_identification"] = any(i.get("speaker_identification") is True for i in infos)
        info["engine"] = AUTO_SERVICE_NAME
        info.pop("max_speakers", None)
        return {
            "service_name": AUTO_SERVICE_NAME,
            "service_type": "diarization",
            "service_language": "*",
            "queue_name": None,
            "info": info,
            "instances": [i for s in available for i in s.instances],
        }


class RoutingError(Exception):
    pass
