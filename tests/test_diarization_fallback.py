import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

os.environ.setdefault("MONGO_HOST", "localhost")
os.environ.setdefault("MONGO_PORT", "27017")
os.environ.setdefault("SERVICE_NAME", "stt")

import pytest

import transcriptionservice.transcription.transcription_task as tt
from transcriptionservice.transcription.configs.taskconfig import DiarizationConfig
from transcriptionservice.transcription.utils.diarizationrouting import (
    DiarizationRouting,
)
from transcriptionservice.transcription.utils.taskprogression import TaskProgression


class FakeJob:
    def __init__(self, result, status="SUCCESS", state="SUCCESS", info=None, polls=0):
        self.result = result
        self.status = status
        self.state = state
        self.info = info
        self.polls = polls

    def ready(self):
        self.polls -= 1
        return self.polls < 0

    def get(self, disable_sync_subtasks=True, propagate=True):
        return self.result


class FakeTask:
    def __init__(self):
        self.states = []

    def update_state(self, state, meta):
        self.states.append(meta["steps"]["diarization"]["progress"])


class FakeService:
    def __init__(self, name, info=None):
        self.service_name = name
        self.queue_name = f"q-{name}"
        self.info = info or {}
        self.instances = [{"host_name": name}]


NEMOTRON = FakeService("nemotron", {"max_speakers": 8})
PYANNOTE = FakeService("pyannote")
ARGS = ["file.wav", None, None]


def speakers(n, saturated=False):
    return {"speakers": [{"spk_id": f"spk{i}"} for i in range(n)], "saturated": saturated}


@pytest.fixture
def run(monkeypatch):
    """_collect_diarization with a first job, and the job the fallback would send."""
    monkeypatch.setattr(tt, "POLL_INTERVAL", 0)
    monkeypatch.setattr(tt.time, "sleep", lambda s: None)

    def call(first, second=None, fallback=PYANNOTE):
        sent = []

        def send_task(name, queue, args):
            sent.append((name, queue, args))
            return second

        monkeypatch.setattr(tt.celery, "send_task", send_task)
        routing = DiarizationRouting(
            {s.service_name: s for s in (NEMOTRON, PYANNOTE)}, "nemotron", "pyannote"
        )
        task = FakeTask()
        progress = TaskProgression([("diarization", True)])
        config = DiarizationConfig({"enableDiarization": True})
        config.setService("nemotron", "q-nemotron")
        job, result = tt._collect_diarization(
            task, progress, first, fallback, routing, config, ARGS
        )
        return job, result, sent, task

    return call


class TestCollectDiarization:
    def test_below_ceiling_keeps_fast_result(self, run):
        first = FakeJob(speakers(4))
        job, result, sent, _ = run(first)
        assert job is first and result == speakers(4) and sent == []

    def test_saturated_reruns_on_fallback(self, run):
        second = FakeJob(speakers(12))
        job, result, sent, task = run(FakeJob(speakers(8, saturated=True)), second)
        assert job is second and result == speakers(12)
        assert sent == [(DiarizationConfig.task_name, "q-pyannote", ARGS)]
        assert task.states[-1] == 0.0

    def test_ceiling_reached_without_flag_reruns(self, run):
        _, _, sent, _ = run(FakeJob(speakers(8)), FakeJob(speakers(9)))
        assert len(sent) == 1

    def test_failure_reruns_on_fallback(self, run):
        second = FakeJob(speakers(3))
        job, result, sent, _ = run(FakeJob(RuntimeError("OOM"), status="FAILURE"), second)
        assert job is second and result == speakers(3) and len(sent) == 1

    def test_fallback_failure_is_returned(self, run):
        second = FakeJob(RuntimeError("down"), status="FAILURE")
        job, _, _, _ = run(FakeJob(RuntimeError("OOM"), status="FAILURE"), second)
        assert job.status == "FAILURE"

    def test_no_fallback_returns_failure_untouched(self, run):
        first = FakeJob(RuntimeError("OOM"), status="FAILURE")
        job, result, sent, _ = run(first, fallback=None)
        assert job is first and isinstance(result, RuntimeError) and sent == []

    def test_no_fallback_keeps_saturated_result(self, run):
        _, result, sent, _ = run(FakeJob(speakers(8, saturated=True)), fallback=None)
        assert result["saturated"] and sent == []


class TestReportDiarization:
    def report(self, job):
        task = FakeTask()
        progress = TaskProgression([("diarization", True)])
        tt._report_diarization(task, progress, job)
        return task.states

    def test_progress_copied(self):
        assert self.report(FakeJob(None, state="PROGRESS", info={"progress": 0.4})) == [0.4]

    @pytest.mark.parametrize(
        "state, info",
        [
            ("STARTED", {"progress": 0.4}),
            ("PROGRESS", None),
            ("PROGRESS", {}),
            ("PROGRESS", {"progress": "n/a"}),
            ("PROGRESS", {"progress": None}),
        ],
    )
    def test_ignored(self, state, info):
        assert self.report(FakeJob(None, state=state, info=info)) == []

    def test_no_job(self):
        assert self.report(None) == []

    def test_backend_error_ignored(self):
        class Broken:
            @property
            def state(self):
                raise ConnectionError("redis down")

        assert self.report(Broken()) == []

    def test_polls_until_ready(self, monkeypatch):
        monkeypatch.setattr(tt.time, "sleep", lambda s: None)
        ticks = []
        tt._wait(FakeJob(None, polls=3), lambda: ticks.append(1))
        assert len(ticks) == 3
