import json
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import pytest

import transcriptionservice.broker.discovery as discovery


class FakeDoc:
    def __init__(self, doc_id, info):
        self.id = doc_id
        self.json = json.dumps(info)


class FakeSearch:
    def __init__(self, registry):
        self.registry = registry
        self.deleted = []

    def search(self, query):
        docs = [FakeDoc(k, v) for k, v in self.registry.items()]
        return type("Result", (), {"docs": docs})

    def delete_document(self, doc_id):
        self.deleted.append(doc_id)
        self.registry.pop(doc_id, None)


class FakeRedis:
    def __init__(self, registry):
        self._ft = FakeSearch(registry)

    def ft(self):
        return self._ft


def entry(host, name="stt-diarization-pyannote", age=0):
    return (
        f"service:{host}",
        {
            "service_name": name,
            "service_type": "diarization",
            "service_language": "*",
            "queue_name": name,
            "version": "1.0.0",
            "info": "{}",
            "last_alive": int(time.time() - age),
            "concurrency": 1,
        },
    )


@pytest.fixture
def listing(monkeypatch):
    """list_available_services on a fake registry; responding_hosts answer inspect."""

    def run(entries, responding_hosts, ensure_alive=True):
        registry = dict(entries)
        client = FakeRedis(registry)
        monkeypatch.setenv("SERVICES_BROKER", "redis://localhost:6379")
        monkeypatch.setattr(discovery, "LANGUAGE", "fr-FR")
        monkeypatch.setattr(discovery.redis, "Redis", lambda **kwargs: client)
        queues = (
            None
            if responding_hosts is None
            else {f"w@{h}": [] for h in responding_hosts}
        )
        inspect = type("Inspect", (), {"active_queues": lambda self: queues})
        monkeypatch.setattr(discovery.celery.control, "inspect", lambda: inspect())
        services = discovery.list_available_services(ensure_alive=ensure_alive)
        return services["diarization"], client._ft.deleted

    return run


def test_responding_worker_listed(listing):
    services, deleted = listing([entry("a")], ["a"])
    assert services["stt-diarization-pyannote"].instances[0]["responding"] is True
    assert deleted == []


def test_busy_worker_with_fresh_heartbeat_kept(listing):
    services, deleted = listing([entry("a", age=60)], [])
    assert services["stt-diarization-pyannote"].instances[0]["responding"] is False
    assert deleted == []


def test_silent_worker_with_stale_heartbeat_removed(listing):
    services, deleted = listing(
        [entry("a", age=discovery.STALE_SERVICE_SECONDS + 1)], []
    )
    assert services == {}
    assert deleted == ["service:a"]


def test_no_inspect_reply(listing):
    services, deleted = listing([entry("a", age=60)], None)
    assert services["stt-diarization-pyannote"].instances[0]["responding"] is False
    assert deleted == []


def test_instances_of_one_service_merged(listing):
    services, _ = listing(
        [entry("a"), entry("b"), entry("c", name="stt-diarization-nemotron")],
        ["a", "b", "c"],
    )
    assert sorted(
        i["host_name"] for i in services["stt-diarization-pyannote"].instances
    ) == ["a", "b"]
    assert len(services["stt-diarization-nemotron"].instances) == 1


def test_without_ensure_alive(listing):
    services, deleted = listing(
        [entry("a", age=10 * discovery.STALE_SERVICE_SECONDS)], [], ensure_alive=False
    )
    assert "responding" not in services["stt-diarization-pyannote"].instances[0]
    assert deleted == []


def test_responding_worker_with_stale_heartbeat_kept(listing):
    services, deleted = listing(
        [entry("a", age=10 * discovery.STALE_SERVICE_SECONDS)], ["a"]
    )
    assert services["stt-diarization-pyannote"].instances[0]["responding"] is True
    assert deleted == []


def test_entry_without_heartbeat_removed_when_silent(listing):
    host, info = entry("a")
    del info["last_alive"]
    services, deleted = listing([(host, info)], [])
    assert services == {} and deleted == ["service:a"]


def test_other_language_ignored(listing):
    host, info = entry("a")
    info["service_language"] = "en-US"
    services, deleted = listing([(host, info)], [])
    assert services == {} and deleted == []
