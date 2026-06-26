import json

# Set PYTHONPATH
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import io

import pytest
from celery.exceptions import TimeoutError as CeleryTimeoutError
from flask import Flask

import transcriptionservice.server.speakerid as speakerid
from transcriptionservice.broker.discovery import Service
from transcriptionservice.server.speakerid import check_speaker_id_auth, speakerid_bp

ORG_ID = "64ff00112233445566778899"
OTHER_ORG_ID = "65ee00112233445566778899"
COLLECTION = f"spkid_{ORG_ID}_65aa00112233445566778899"
SPEAKER_ID = "label:65cc00112233445566778899"

SPEAKER_ID_INFO = {
    "speaker_identification": True,
    "model_id": "speechbrain/spkrec-ecapa-voxceleb",
    "dim": 192,
}

VOICEPRINT_RESULT = {
    "vector": [0.1, 0.2, 0.3],
    "model_id": "speechbrain/spkrec-ecapa-voxceleb",
    "dim": 192,
    "duration_used": 42.0,
    "files_used": 2,
}


def make_service(name="diarization-pyannote", info=SPEAKER_ID_INFO):
    return Service(name, "diarization", "*", f"{name}_queue", info)


class FakeAsyncResult:
    def __init__(self, result=None, exception=None):
        self.result = result
        self.exception = exception

    def get(self, timeout=None):
        self.timeout = timeout
        if self.exception is not None:
            raise self.exception
        return self.result


class FakeCelery:
    def __init__(self, result=None, exception=None):
        self.result = result
        self.exception = exception
        self.calls = []

    def send_task(self, name=None, queue=None, args=None):
        self.calls.append({"name": name, "queue": queue, "args": args})
        return FakeAsyncResult(self.result, self.exception)


@pytest.fixture
def app():
    app = Flask(__name__)
    app.register_blueprint(speakerid_bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEAKER_ID_API_TOKEN", raising=False)
    monkeypatch.delenv("RESOLVE_POLICY", raising=False)
    monkeypatch.setattr(speakerid, "AUDIO_FOLDER", str(tmp_path))
    monkeypatch.setattr(
        speakerid,
        "list_available_services",
        lambda ensure_alive=False: {"diarization": {"diarization-pyannote": make_service()}},
    )


@pytest.fixture
def fake_celery(monkeypatch):
    fake = FakeCelery()
    monkeypatch.setattr(speakerid, "celery", fake)
    return fake


HEADERS = {"X-Organization-Id": ORG_ID}


class TestVoiceprint:
    def voiceprint_files(self, n=2):
        return {
            "file": [
                (io.BytesIO(b"fake audio content"), f"sample_{i}.wav") for i in range(n)
            ]
        }

    def test_happy_path(self, client, fake_celery, tmp_path):
        fake_celery.result = VOICEPRINT_RESULT
        response = client.post(
            "/speaker-identification/voiceprint",
            headers=HEADERS,
            data=self.voiceprint_files(),
        )
        assert response.status_code == 200
        assert json.loads(response.data) == {
            "vector": [0.1, 0.2, 0.3],
            "modelId": "speechbrain/spkrec-ecapa-voxceleb",
            "dim": 192,
            "durationUsed": 42.0,
        }
        assert len(fake_celery.calls) == 1
        call = fake_celery.calls[0]
        assert call["name"] == "voiceprint_compute_task"
        assert call["queue"] == "diarization-pyannote_queue"
        assert len(call["args"][0]) == 2
        # Files must be cleaned up after the task
        assert list(tmp_path.iterdir()) == []

    def test_files_cleaned_up_on_failure(self, client, fake_celery, tmp_path):
        fake_celery.exception = Exception("no_valid_audio")
        response = client.post(
            "/speaker-identification/voiceprint",
            headers=HEADERS,
            data=self.voiceprint_files(),
        )
        assert response.status_code == 502
        assert json.loads(response.data) == {"error": "no_valid_audio"}
        assert list(tmp_path.iterdir()) == []

    def test_timeout(self, client, fake_celery, tmp_path):
        fake_celery.exception = CeleryTimeoutError("too long")
        response = client.post(
            "/speaker-identification/voiceprint",
            headers=HEADERS,
            data=self.voiceprint_files(),
        )
        assert response.status_code == 504
        assert list(tmp_path.iterdir()) == []

    def test_no_file(self, client, fake_celery):
        response = client.post(
            "/speaker-identification/voiceprint", headers=HEADERS, data={}
        )
        assert response.status_code == 400
        assert fake_celery.calls == []

    def test_missing_organization_header(self, client, fake_celery):
        response = client.post(
            "/speaker-identification/voiceprint", data=self.voiceprint_files()
        )
        assert response.status_code == 400
        assert fake_celery.calls == []

    def test_bad_organization_header(self, client, fake_celery):
        response = client.post(
            "/speaker-identification/voiceprint",
            headers={"X-Organization-Id": "not-hexadecimal"},
            data=self.voiceprint_files(),
        )
        assert response.status_code == 400

    def test_token_required(self, client, fake_celery, monkeypatch):
        monkeypatch.setenv("SPEAKER_ID_API_TOKEN", "secret")
        fake_celery.result = VOICEPRINT_RESULT
        # Missing token
        response = client.post(
            "/speaker-identification/voiceprint",
            headers=HEADERS,
            data=self.voiceprint_files(),
        )
        assert response.status_code == 401
        # Wrong token
        response = client.post(
            "/speaker-identification/voiceprint",
            headers={**HEADERS, "X-Speaker-Id-Token": "wrong"},
            data=self.voiceprint_files(),
        )
        assert response.status_code == 401
        # Valid token
        response = client.post(
            "/speaker-identification/voiceprint",
            headers={**HEADERS, "X-Speaker-Id-Token": "secret"},
            data=self.voiceprint_files(),
        )
        assert response.status_code == 200

    def test_no_capable_service(self, client, fake_celery, monkeypatch):
        monkeypatch.setattr(
            speakerid,
            "list_available_services",
            lambda ensure_alive=False: {
                "diarization": {"legacy-diarization": make_service("legacy-diarization", "unknown")}
            },
        )
        response = client.post(
            "/speaker-identification/voiceprint",
            headers=HEADERS,
            data=self.voiceprint_files(),
        )
        assert response.status_code == 404

    def test_unknown_service_name(self, client, fake_celery):
        response = client.post(
            "/speaker-identification/voiceprint?serviceName=does-not-exist",
            headers=HEADERS,
            data=self.voiceprint_files(),
        )
        assert response.status_code == 404


class TestUpsertSpeaker:
    URL = f"/speaker-identification/collections/{COLLECTION}/speakers/{SPEAKER_ID}"
    BODY = {
        "name": "Griogy",
        "vector": [0.1, 0.2, 0.3],
        "modelId": "speechbrain/spkrec-ecapa-voxceleb",
    }

    def test_happy_path(self, client, fake_celery):
        fake_celery.result = {"status": "ok", "point_id": "uuid", "created_collection": False}
        response = client.put(self.URL, headers=HEADERS, json=self.BODY)
        assert response.status_code == 200
        assert json.loads(response.data) == {"status": "ok"}
        call = fake_celery.calls[0]
        assert call["name"] == "speaker_upsert_task"
        assert call["queue"] == "diarization-pyannote_queue"
        assert call["args"] == [
            COLLECTION,
            SPEAKER_ID,
            "Griogy",
            [0.1, 0.2, 0.3],
            "speechbrain/spkrec-ecapa-voxceleb",
        ]

    def test_foreign_collection(self, client, fake_celery):
        url = f"/speaker-identification/collections/spkid_{OTHER_ORG_ID}_65aa00112233445566778899/speakers/{SPEAKER_ID}"
        response = client.put(url, headers=HEADERS, json=self.BODY)
        assert response.status_code == 403
        assert fake_celery.calls == []

    def test_bad_speaker_id(self, client, fake_celery):
        url = f"/speaker-identification/collections/{COLLECTION}/speakers/bogus:65cc00112233445566778899"
        response = client.put(url, headers=HEADERS, json=self.BODY)
        assert response.status_code == 400

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"vector": [0.1], "modelId": "m"},  # missing name
            {"name": "a", "modelId": "m"},  # missing vector
            {"name": "a", "vector": [0.1]},  # missing modelId
            {"name": "a", "vector": ["x"], "modelId": "m"},  # bad vector
            {"name": "", "vector": [0.1], "modelId": "m"},  # empty name
        ],
    )
    def test_bad_body(self, client, fake_celery, body):
        response = client.put(self.URL, headers=HEADERS, json=body)
        assert response.status_code == 400
        assert fake_celery.calls == []

    def test_worker_failure(self, client, fake_celery):
        fake_celery.exception = Exception("model_mismatch")
        response = client.put(self.URL, headers=HEADERS, json=self.BODY)
        assert response.status_code == 502
        assert json.loads(response.data) == {"error": "model_mismatch"}


class TestDeleteSpeaker:
    URL = f"/speaker-identification/collections/{COLLECTION}/speakers/{SPEAKER_ID}"

    def test_happy_path(self, client, fake_celery):
        fake_celery.result = {"status": "ok", "deleted": 1}
        response = client.delete(self.URL, headers=HEADERS)
        assert response.status_code == 200
        assert json.loads(response.data) == {"status": "ok"}
        call = fake_celery.calls[0]
        assert call["name"] == "speaker_delete_task"
        assert call["args"] == [COLLECTION, [SPEAKER_ID]]

    def test_bad_speaker_id(self, client, fake_celery):
        url = f"/speaker-identification/collections/{COLLECTION}/speakers/label:42"
        response = client.delete(url, headers=HEADERS)
        assert response.status_code == 400


class TestDropCollection:
    URL = f"/speaker-identification/collections/{COLLECTION}"

    def test_happy_path(self, client, fake_celery):
        fake_celery.result = {"status": "ok", "existed": True}
        response = client.delete(self.URL, headers=HEADERS)
        assert response.status_code == 200
        assert json.loads(response.data) == {"status": "ok"}
        call = fake_celery.calls[0]
        assert call["name"] == "collection_drop_task"
        assert call["args"] == [COLLECTION]

    def test_foreign_collection(self, client, fake_celery):
        url = f"/speaker-identification/collections/spkid_{OTHER_ORG_ID}_65aa00112233445566778899"
        response = client.delete(url, headers=HEADERS)
        assert response.status_code == 403
        assert fake_celery.calls == []


class TestInfo:
    URL = "/speaker-identification/info"

    def test_happy_path(self, client, fake_celery):
        response = client.get(self.URL, headers=HEADERS)
        assert response.status_code == 200
        assert json.loads(response.data) == {
            "enabled": True,
            "modelId": "speechbrain/spkrec-ecapa-voxceleb",
            "dim": 192,
            "serviceName": "diarization-pyannote",
        }
        # No Celery task involved
        assert fake_celery.calls == []

    def test_no_capable_service(self, client, monkeypatch):
        monkeypatch.setattr(
            speakerid,
            "list_available_services",
            lambda ensure_alive=False: {"diarization": {}},
        )
        response = client.get(self.URL, headers=HEADERS)
        assert response.status_code == 404
        assert json.loads(response.data) == {"enabled": False}

    def test_missing_organization_header(self, client):
        response = client.get(self.URL)
        assert response.status_code == 400

    def test_service_name_param(self, client):
        response = client.get(f"{self.URL}?serviceName=diarization-pyannote", headers=HEADERS)
        assert response.status_code == 200
        response = client.get(f"{self.URL}?serviceName=unknown-service", headers=HEADERS)
        assert response.status_code == 404


class TestTranscribeAuthHelper:
    """check_speaker_id_auth is the helper used by /transcribe when a
    speakerIdentificationConfig is present."""

    def test_matching_header(self):
        assert check_speaker_id_auth({"X-Organization-Id": ORG_ID}, ORG_ID) is None

    def test_missing_header(self):
        error = check_speaker_id_auth({}, ORG_ID)
        assert error is not None and error[1] == 403

    def test_mismatching_header(self):
        error = check_speaker_id_auth({"X-Organization-Id": OTHER_ORG_ID}, ORG_ID)
        assert error is not None and error[1] == 403

    def test_token(self, monkeypatch):
        monkeypatch.setenv("SPEAKER_ID_API_TOKEN", "secret")
        error = check_speaker_id_auth({"X-Organization-Id": ORG_ID}, ORG_ID)
        assert error is not None and error[1] == 401
        assert (
            check_speaker_id_auth(
                {"X-Organization-Id": ORG_ID, "X-Speaker-Id-Token": "secret"}, ORG_ID
            )
            is None
        )
