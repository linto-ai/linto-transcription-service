""" The transcription_task module implements the transcription's task steps to be served by the request celery workers."""
import logging
import os
import time
import celery.states as celery_states

from transcriptionservice.broker.celeryapp import celery
from transcriptionservice.server.mongodb.db_client import DBClient
from transcriptionservice.transcription.configs.transcriptionconfig import (
    TranscriptionConfig,
)
from transcriptionservice.transcription.transcription_result import TranscriptionResult
from transcriptionservice.transcription.utils.audio import (
    splitFile,
    splitUsingTimestamps,
    transcoding,
    getDuration,
)
from transcriptionservice.transcription.utils.serviceresolve import (
    ResolveException,
    ServiceResolver,
)
from transcriptionservice.transcription.utils.taskprogression import (
    StepState,
    TaskProgression,
)

__all__ = ["transcription_task"]

# Create shared mongoclient
db_info = {
    "db_host": os.environ.get("MONGO_HOST", None),
    "db_port": int(os.environ.get("MONGO_PORT", None)),
    "service_name": os.environ.get("SERVICE_NAME", None),
    "db_name": "transcriptiondb",
}

db_client = DBClient(db_info)


@celery.task(name="transcription_task", bind=True)
def transcription_task(self, task_info: dict, file_path: str):
    """Transcription task processes a transcription request.

    task_info contains the following field:
    - "transcription_config" : Transcription configuration
    - "result_db" : Connexion info to the result database
    - "service": Name of the transcription service
    - "hash": Audio File Hash
    - "keep_audio": If False, the audio file is deleted after the task.
    - "timestamps" : (Optionnal) Audio spliting timestamps
    """
    try:
        return transcription_task_(self, task_info, file_path)
    except Exception as error:
        import traceback
        raise Exception(f"Task failed: {str(error)}\n\n{traceback.format_exc()}")

def transcription_task_(self, task_info: dict, file_path: str):
    # Logging task
    logging.basicConfig(
        filename=f"/usr/src/app/logs/{self.request.id}.txt",
        filemode="a",
        format="%(asctime)s,%(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        level=logging.DEBUG,
        force=True,
    )

    logging.info(f"Running task {self.request.id}")

    self.update_state(state="STARTED", meta={"steps": {}})

    config = TranscriptionConfig(task_info["transcription_config"])

    # Disable diarization if timestamps are uploaded
    if task_info["timestamps"]:
        config.diarizationConfig.isEnabled = False
        logging.debug("Disabling diarization due to timestamps information")

    logging.info(config)

    # Resolve required task queues
    resolver = ServiceResolver()

    for task in config.tasks:
        try:
            resolver.resolve_task(task)
            logging.info(
                f"Task {task} successfuly resolved -> {task.serviceName}:{task.serviceQueue} (Policy={resolver.service_policy})"
            )
        except ResolveException as error:
            logging.error(str(error))
            raise ResolveException(f"Failed to resolve: {str(error)}")

    # Task progression
    progress = TaskProgression(
        [
            ("preprocessing", True),
            ("transcription", True),
            ("diarization", config.diarizationConfig.isEnabled),
            ("punctuation", config.punctuationConfig.isEnabled),
            ("postprocessing", True),
        ]
    )
    progress.steps["preprocessing"].state = StepState.STARTED
    self.update_state(state="STARTED", meta=progress.toDict())

    # Preprocessing
    ## Transtyping
    logging.info(f"Converting input file to wav.")
    file_name = transcoding(file_path)

    task_hash = task_info["hash"] + "-" + str(config.language)

    # Check for available transcription
    logging.info(f"Checking for available transcription for {task_hash}")

    if not task_info["timestamps"]:
        available_transcription = db_client.fetch_transcription(task_hash)
    else:
        available_transcription = None

    if available_transcription:
        logging.info("Transcription result already available")
        try:
            transcription_result = TranscriptionResult(None)
            transcription_result.setTranscription(available_transcription["words"], available_transcription.get("words_language"))
            progress.steps["transcription"].state = StepState.DONE
            progress.steps["preprocessing"].state = StepState.DONE
        except Exception as e:
            logging.warning("Failed to fetch transcription: {}".format(str(e)))
            available_transcription = None
    self.update_state(state="STARTED", meta=progress.toDict())

    if available_transcription is None:
        # Split using VAD
        if task_info["timestamps"]:
            logging.info(f"Split using provided timestamps ...")
            subfiles, total_duration = splitUsingTimestamps(
                file_name, task_info["timestamps"]
            )
            logging.info(f"Input file has been split into {len(subfiles)} subfiles")
        elif not config.vadConfig.isEnabled:
            logging.info(f"Split in one chunk (VAD disabled)")
            total_duration = getDuration(file_name)
            subfiles = [(file_name, 0.0, total_duration)]
        else:
            logging.info(f"Splitting using VAD ...")
            if config.vadConfig.minDuration:
                # Values for ASR like Whisper which pad small segments anyway
                kwargs = {
                    "min_segment_duration": config.vadConfig.minDuration,
                    "max_segment_duration": config.vadConfig.maxDuration,
                    "min_length": config.vadConfig.minDuration,
                    # "min_silence": 0.6,
                }
            else:
                # Historical values for Kaldi
                kwargs = {
                    "min_segment_duration": None,
                    "max_segment_duration": 1200.0, # New, to avoid memory errors
                    "min_length": 10,
                    # "min_silence": 0.6,
                }
            subfiles, stats_duration = splitFile(
                file_name,
                method=config.vadConfig.methodName,
                **kwargs,
            )
            total_duration = stats_duration["total"]
            logging.info(f"Split in {len(subfiles)} chunks of around {config.vadConfig.minDuration} seconds ({', '.join([k+'='+str(round(v, 2)) for k,v in stats_duration.items()])})")

        # Progress monitoring
        speakers = None
        progress.steps["preprocessing"].state = StepState.DONE
        self.update_state(state="STARTED", meta=progress.toDict())

        # Transcription
        transJobIds = []
        progress.steps["transcription"].state = StepState.STARTED
        for subfile_path, offset, duration in subfiles:
            transJobId = celery.send_task(
                name="transcribe_task",
                queue=task_info["service_name"],
                args=[subfile_path, True, config.language],
            )
            transJobIds.append((transJobId, offset, duration, subfile_path))

        self.update_state(state="STARTED", meta=progress.toDict())

    # Diarization (In parallel)
    if config.diarizationConfig.isEnabled:
        logging.info(
            f"Processing diarization task on {config.diarizationConfig.serviceQueue}..."
        )
        progress.steps["diarization"].state = StepState.STARTED
        args=[
            file_name,
            config.diarizationConfig.numberOfSpeaker,
            config.diarizationConfig.maxNumberOfSpeaker,
        ]
        if config.diarizationConfig.speakerIdentificationConfig:
            speaker_id_config = config.diarizationConfig.speakerIdentificationConfig
            # The worker has no use for the organizationId: collection isolation
            # is already enforced at the ingress level.
            args.append(
                {
                    "collections": speaker_id_config["collections"],
                    "speakers": speaker_id_config["speakers"],
                    "minSimilarity": speaker_id_config["minSimilarity"],
                }
            )
        elif config.diarizationConfig.speakerIdentification:
            args.append(config.diarizationConfig.speakerIdentification)
        diarJobId = celery.send_task(
            name=config.diarizationConfig.task_name,
            queue=config.diarizationConfig.serviceQueue,
            args=args,
        )
        self.update_state(state="STARTED", meta=progress.toDict())

    # Wait for all the transcription jobs
    if available_transcription is None:
        transcriptions = []
        failed = False
        transcription = None
        for jobId, offset, duration, subfile_path in transJobIds:
            if failed:
                if subfile_path != file_name and os.path.exists(subfile_path):
                    os.remove(subfile_path)
                jobId.revoke()
                continue
            transcription = jobId.get(disable_sync_subtasks=False)
            if subfile_path != file_name and os.path.exists(subfile_path):
                os.remove(subfile_path)
            if jobId.status != celery_states.SUCCESS:
                failed = True
                continue
            transcriptions.append((transcription, offset))
            progress.steps["transcription"].progress += duration / total_duration
            self.update_state(state="STARTED", meta=progress.toDict())
        logging.info(f"Transcription task complete")
        progress.steps["transcription"].state = StepState.DONE

        self.update_state(state="STARTED", meta=progress.toDict())

        if failed:
            raise Exception("Transcription has failed: {}".format(transcription))

        # Merge Transcription results
        if task_info["timestamps"]:
            transcription_result = TranscriptionResult(
                transcriptions, [x["spk_id"] for x in task_info["timestamps"]]
            )
        else:
            transcription_result = TranscriptionResult(transcriptions)

        # Save transcription in DB
        words = transcription_result.words
        words_language = transcription_result.words_language
        try:
            db_client.push_transcription(task_hash, words, words_language)
        except Exception as e:
            logging.warning("Failed to push transcription to DB: {}".format(e))

    # Diarization result
    if config.diarizationConfig.isEnabled:
        speakers = diarJobId.get(disable_sync_subtasks=False)
        progress.steps["diarization"].state = StepState.DONE
        self.update_state(state="STARTED", meta=progress.toDict())
        logging.info(f"Diarization task complete")
        if diarJobId.status != celery_states.SUCCESS:
            raise Exception("Diarization has failed: {}".format(speakers))
        transcription_result.setDiarizationResult(speakers)
    elif not task_info["timestamps"]:
        transcription_result.setNoDiarization()

    # Punctuation
    if config.punctuationConfig.isEnabled:
        logging.info(
            f"Processing punctuation task on {config.punctuationConfig.serviceQueue} ..."
        )
        progress.steps["punctuation"].state = StepState.STARTED
        self.update_state(state="STARTED", meta=progress.toDict())
        puncJobId = celery.send_task(
            name=config.punctuationConfig.task_name,
            queue=config.punctuationConfig.serviceQueue,
            args=[[seg.toString() for seg in transcription_result.segments]],
        )
        try:
            punctuated_text = puncJobId.get(disable_sync_subtasks=False)
            logging.info(f"Punctuation task complete.")
        except Exception as e:
            progress.steps["punctuation"].state = StepState.DONE
            logging.error(f"Punctuation task complete")
            raise Exception("Punctuation has failed: {}".format(str(e)))
        self.update_state(state="STARTED", meta=progress.toDict())
        transcription_result.setProcessedSegment(punctuated_text)

    logging.info(f"Task complete, post processing ...")

    # Write result in database
    progress.steps["postprocessing"].state = StepState.STARTED
    self.update_state(state="STARTED", meta=progress.toDict())
    try:
        result_id = db_client.push_result(
            file_hash=task_hash,
            job_id=self.request.id,
            origin="origin",
            service_name=task_info["service_name"],
            config=config,
            result=transcription_result,
        )
    except Exception as e:
        raise Exception("Failed to process result")

    # Free ressource
    if not task_info["keep_audio"]:
        try:
            os.remove(file_name)
        except Exception as e:
            logging.warning("Failed to remove ressource {}".format(file_name))
    progress.steps["postprocessing"].state = StepState.DONE
    return result_id
