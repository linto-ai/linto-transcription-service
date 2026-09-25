import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import pytest

from transcriptionservice.transcription.configs.taskconfig import DiarizationConfig
from transcriptionservice.transcription.utils.diarizationrouting import (
    AUTO_SERVICE_NAME,
    DiarizationRouting,
    RoutingError,
)


class FakeService:
    def __init__(self, name, info):
        self.service_name = name
        self.queue_name = f"q-{name}"
        self.info = info
        self.instances = [{"host_name": f"host-{name}"}]


NEMOTRON = FakeService("stt-diarization-nemotron", {"engine": "nemotron", "max_speakers": 8, "speaker_identification": True, "fr": "Oui"})
PYANNOTE = FakeService("stt-diarization-pyannote", {"engine": "pyannote", "speaker_identification": True, "fr": "Oui"})


def routing(services=None, max_speakers=None):
    if services is None:
        services = {s.service_name: s for s in (NEMOTRON, PYANNOTE)}
    return DiarizationRouting(services, NEMOTRON.service_name, PYANNOTE.service_name, max_speakers)


def config(**fields):
    return DiarizationConfig({"enableDiarization": True, **fields})


class TestPlan:
    @pytest.mark.parametrize(
        "fields, primary, fallback",
        [
            ({}, NEMOTRON, PYANNOTE),  # auto
            ({"maxNumberOfSpeaker": 100}, NEMOTRON, PYANNOTE),  # what Studio sends
            ({"maxNumberOfSpeaker": 5}, NEMOTRON, PYANNOTE),
            ({"numberOfSpeaker": 7}, NEMOTRON, PYANNOTE),
            ({"numberOfSpeaker": 8}, PYANNOTE, None),
            ({"numberOfSpeaker": 12}, PYANNOTE, None),
        ],
    )
    def test_table(self, fields, primary, fallback):
        assert routing().plan(config(**fields)) == (primary, fallback)

    def test_fast_unavailable(self):
        assert routing({PYANNOTE.service_name: PYANNOTE}).plan(config()) == (PYANNOTE, None)

    def test_fallback_unavailable(self):
        r = routing({NEMOTRON.service_name: NEMOTRON})
        assert r.plan(config()) == (NEMOTRON, None)
        assert r.plan(config(numberOfSpeaker=12)) == (NEMOTRON, None)

    def test_fast_registered_but_silent(self):
        silent = FakeService(NEMOTRON.service_name, NEMOTRON.info)
        silent.instances = [{"host_name": "gone", "responding": False}]
        r = routing({silent.service_name: silent, PYANNOTE.service_name: PYANNOTE})
        assert r.plan(config()) == (PYANNOTE, None)

    def test_fast_one_instance_responding(self):
        svc = FakeService(NEMOTRON.service_name, NEMOTRON.info)
        svc.instances = [{"host_name": "a", "responding": False}, {"host_name": "b", "responding": True}]
        r = routing({svc.service_name: svc, PYANNOTE.service_name: PYANNOTE})
        assert r.plan(config()) == (svc, PYANNOTE)

    def test_nothing_available(self):
        with pytest.raises(RoutingError):
            routing({}).plan(config())


class TestApplies:
    def test_auto_and_unset(self):
        assert routing().applies(config())
        assert routing().applies(config(serviceName=AUTO_SERVICE_NAME))

    def test_explicit_service_keeps_legacy_resolution(self):
        assert not routing().applies(config(serviceName=PYANNOTE.service_name))

    def test_not_configured(self):
        r = DiarizationRouting({}, None, None)
        assert not r.configured
        assert not r.applies(config())


class TestSaturation:
    def test_ceiling_from_registration(self):
        assert routing().fast_max_speakers == 7

    def test_ceiling_env_override(self):
        assert routing(max_speakers=5).fast_max_speakers == 5

    def test_should_fall_back(self):
        r = routing()
        speakers = lambda n: [{"spk_id": f"spk{i}"} for i in range(n)]
        assert r.should_fall_back({"speakers": speakers(8), "saturated": True})
        assert r.should_fall_back({"speakers": speakers(8)})
        assert not r.should_fall_back({"speakers": speakers(7), "saturated": False})
        assert not r.should_fall_back("not a result")

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("DIARIZATION_FAST_SERVICE", NEMOTRON.service_name)
        monkeypatch.setenv("DIARIZATION_FALLBACK_SERVICE", PYANNOTE.service_name)
        monkeypatch.setenv("DIARIZATION_FAST_MAX_SPEAKERS", "6")
        r = DiarizationRouting.from_env({NEMOTRON.service_name: NEMOTRON})
        assert r.configured and r.fast is NEMOTRON and r.fallback is None
        assert r.fast_max_speakers == 6


class TestAutoEntry:
    def test_entry(self):
        entry = routing().auto_entry()
        assert entry["service_name"] == AUTO_SERVICE_NAME
        assert entry["service_type"] == "diarization"
        assert entry["info"]["speaker_identification"] is True
        assert entry["info"]["engine"] == AUTO_SERVICE_NAME
        assert entry["info"]["fr"] == "Oui"
        assert "max_speakers" not in entry["info"]
        assert len(entry["instances"]) == 2

    def test_no_entry_when_not_configured(self):
        assert DiarizationRouting({}, None, None).auto_entry() is None

    def test_no_entry_without_services(self):
        assert routing({}).auto_entry() is None
