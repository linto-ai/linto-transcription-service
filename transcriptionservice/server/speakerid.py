#!/usr/bin/env python3

""" The speakerid module implements the /speaker-identification routes used to manage
speaker identification voiceprints and collections through the diarization workers."""

import os
import re

from celery.exceptions import TimeoutError as CeleryTimeoutError
from flask import Blueprint, json, request

from transcriptionservice import logger
from transcriptionservice.broker.celeryapp import celery
from transcriptionservice.broker.discovery import list_available_services
from transcriptionservice.server.utils import fileHash
from transcriptionservice.server.utils.ressources import write_ressource
from transcriptionservice.transcription.utils.serviceresolve import ServicePolicy

AUDIO_FOLDER = "/opt/audio"

# Synchronous Celery timeouts (seconds)
VOICEPRINT_TIMEOUT = 120
SPEAKER_UPSERT_TIMEOUT = 15
SPEAKER_DELETE_TIMEOUT = 15
COLLECTION_DROP_TIMEOUT = 30

HEX24_PATTERN = re.compile(r"^[0-9a-f]{24}$")
SPEAKER_ID_PATTERN = re.compile(r"^(label|user):[0-9a-f]{24}$")

speakerid_bp = Blueprint("speaker_identification", __name__)


def check_speaker_id_token(headers):
    """Check the optional static speaker identification API token.

    If the SPEAKER_ID_API_TOKEN environment variable is set, the X-Speaker-Id-Token
    header is required and must match.

    Returns a (message, status_code) tuple on failure, None otherwise.
    """
    expected_token = os.environ.get("SPEAKER_ID_API_TOKEN")
    if expected_token:
        if headers.get("X-Speaker-Id-Token") != expected_token:
            return "Invalid or missing X-Speaker-Id-Token header", 401
    return None


def check_speaker_id_auth(headers, organization_id: str):
    """Check speaker identification headers for a /transcribe request.

    The X-Organization-Id header is required and must match the organizationId
    declared in the speakerIdentificationConfig.

    Returns a (message, status_code) tuple on failure, None otherwise.
    """
    token_error = check_speaker_id_token(headers)
    if token_error is not None:
        return token_error
    if headers.get("X-Organization-Id") != organization_id:
        return (
            "X-Organization-Id header is required and must match speakerIdentificationConfig.organizationId",
            403,
        )
    return None


def _authenticate_request(headers, collections: list = []):
    """Validate the shared requirements of the /speaker-identification routes.

    Returns a (organization_id, error) tuple where error is None or a
    (response_body, status_code) tuple.
    """
    organization_id = headers.get("X-Organization-Id")
    if not organization_id or not HEX24_PATTERN.match(organization_id):
        return None, (
            json.dumps(
                {
                    "error": "X-Organization-Id header is required and must be a 24 character hexadecimal identifier"
                }
            ),
            400,
        )
    token_error = check_speaker_id_token(headers)
    if token_error is not None:
        return None, (json.dumps({"error": token_error[0]}), token_error[1])
    collection_pattern = re.compile(r"^spkid_" + organization_id + r"_[0-9a-f]{24}$")
    for collection in collections:
        if not collection_pattern.match(collection):
            return None, (
                json.dumps(
                    {
                        "error": "speaker identification collections do not belong to the declared organization"
                    }
                ),
                403,
            )
    return organization_id, None


def speaker_id_service_info(service) -> dict:
    """Return the parsed info field of a speaker identification capable service, None otherwise."""
    info = service.info
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except json.JSONDecodeError:
            return None
    if isinstance(info, dict) and info.get("speaker_identification") is True:
        return info
    return None


def resolve_speaker_id_service(service_name: str = None, ensure_alive: bool = True):
    """Resolve a speaker identification capable diarization service.

    Args:
        service_name (str, optional): Specific service name requested by the client.
        ensure_alive (bool): If true, check the registered services against the broker.

    Returns:
        Service: The resolved service or None if no capable service is available.
    """
    services = list_available_services(ensure_alive=ensure_alive).get("diarization", {})
    candidates = {
        name: service
        for name, service in services.items()
        if speaker_id_service_info(service) is not None
    }
    if not candidates:
        return None
    if service_name is not None:
        return candidates.get(service_name)
    if ServicePolicy.from_env() == ServicePolicy.DEFAULT:
        default_name = os.environ.get("DIARIZATION_DEFAULT", None)
        if default_name in candidates:
            return candidates[default_name]
    return list(candidates.values())[0]


def _run_task(task_name: str, queue: str, args: list, timeout: int):
    """Send a task on the resolved service queue and wait synchronously for its result.

    Returns a (result, error) tuple where error is None or a
    (response_body, status_code) tuple.
    """
    task = celery.send_task(name=task_name, queue=queue, args=args)
    try:
        return task.get(timeout=timeout), None
    except CeleryTimeoutError:
        logger.error(f"Task {task_name} timed out after {timeout}s")
        return None, (
            json.dumps({"error": f"{task_name} timed out after {timeout}s"}),
            504,
        )
    except Exception as error:
        logger.error(f"Task {task_name} failed: {str(error)}")
        return None, (json.dumps({"error": str(error)}), 502)


def _resolve_or_error(service_name: str = None, ensure_alive: bool = True):
    """Resolve a speaker identification service. Returns a (service, error) tuple."""
    service = resolve_speaker_id_service(service_name, ensure_alive=ensure_alive)
    if service is None:
        return None, (
            json.dumps({"error": "No speaker identification service available"}),
            404,
        )
    return service, None


@speakerid_bp.route("/speaker-identification/voiceprint", methods=["POST"])
def compute_voiceprint():
    """Compute a voiceprint vector from one or several enrollment audio files."""
    _, error = _authenticate_request(request.headers)
    if error is not None:
        return error

    files = []
    for file_key in request.files.keys():
        files.extend(request.files.getlist(file_key))
    if not len(files):
        return json.dumps({"error": "Not file attached to request"}), 400

    service, error = _resolve_or_error(request.args.get("serviceName"))
    if error is not None:
        return error

    file_paths = []
    try:
        try:
            for uploaded_file in files:
                extension = uploaded_file.filename.split(".")[-1]
                random_hash = fileHash(os.urandom(32))
                file_paths.append(
                    write_ressource(
                        uploaded_file.read(),
                        f"voiceprint_{random_hash}",
                        AUDIO_FOLDER,
                        extension,
                    )
                )
        except Exception as e:
            logger.error("Failed to write ressource: {}".format(e))
            return json.dumps({"error": "Server Error: Failed to write ressource"}), 500

        logger.debug(
            f"Sending voiceprint_compute_task ({len(file_paths)} file(s)) on {service.queue_name}"
        )
        result, error = _run_task(
            "voiceprint_compute_task", service.queue_name, [file_paths], VOICEPRINT_TIMEOUT
        )
        if error is not None:
            return error
        return (
            json.dumps(
                {
                    "vector": result["vector"],
                    "modelId": result["model_id"],
                    "dim": result["dim"],
                    "durationUsed": result["duration_used"],
                }
            ),
            200,
        )
    finally:
        for file_path in file_paths:
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning("Failed to remove ressource {}: {}".format(file_path, str(e)))


@speakerid_bp.route(
    "/speaker-identification/collections/<collection>/speakers/<speaker_id>",
    methods=["PUT"],
)
def upsert_speaker(collection, speaker_id):
    """Create or replace a speaker voiceprint within a collection."""
    _, error = _authenticate_request(request.headers, collections=[collection])
    if error is not None:
        return error
    if not SPEAKER_ID_PATTERN.match(speaker_id):
        return (
            json.dumps({"error": "speakerId must match (label|user):{24 hexadecimal characters}"}),
            400,
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return json.dumps({"error": "A JSON body is required"}), 400
    name = body.get("name")
    vector = body.get("vector")
    model_id = body.get("modelId")
    if not isinstance(name, str) or not name.strip():
        return json.dumps({"error": "name is required and must be a non-empty string"}), 400
    if (
        not isinstance(vector, list)
        or not len(vector)
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in vector
        )
    ):
        return json.dumps({"error": "vector is required and must be a list of numbers"}), 400
    if not isinstance(model_id, str) or not model_id:
        return json.dumps({"error": "modelId is required and must be a string"}), 400

    service, error = _resolve_or_error(request.args.get("serviceName"))
    if error is not None:
        return error

    logger.debug(f"Sending speaker_upsert_task for {speaker_id} on {service.queue_name}")
    _, error = _run_task(
        "speaker_upsert_task",
        service.queue_name,
        [collection, speaker_id, name, vector, model_id],
        SPEAKER_UPSERT_TIMEOUT,
    )
    if error is not None:
        return error
    return json.dumps({"status": "ok"}), 200


@speakerid_bp.route(
    "/speaker-identification/collections/<collection>/speakers/<speaker_id>",
    methods=["DELETE"],
)
def delete_speaker(collection, speaker_id):
    """Delete a speaker voiceprint from a collection."""
    _, error = _authenticate_request(request.headers, collections=[collection])
    if error is not None:
        return error
    if not SPEAKER_ID_PATTERN.match(speaker_id):
        return (
            json.dumps({"error": "speakerId must match (label|user):{24 hexadecimal characters}"}),
            400,
        )

    service, error = _resolve_or_error(request.args.get("serviceName"))
    if error is not None:
        return error

    logger.debug(f"Sending speaker_delete_task for {speaker_id} on {service.queue_name}")
    _, error = _run_task(
        "speaker_delete_task",
        service.queue_name,
        [collection, [speaker_id]],
        SPEAKER_DELETE_TIMEOUT,
    )
    if error is not None:
        return error
    return json.dumps({"status": "ok"}), 200


@speakerid_bp.route("/speaker-identification/collections/<collection>", methods=["DELETE"])
def drop_collection(collection):
    """Drop a whole speaker identification collection."""
    _, error = _authenticate_request(request.headers, collections=[collection])
    if error is not None:
        return error

    service, error = _resolve_or_error(request.args.get("serviceName"))
    if error is not None:
        return error

    logger.debug(f"Sending collection_drop_task on {service.queue_name}")
    _, error = _run_task(
        "collection_drop_task", service.queue_name, [collection], COLLECTION_DROP_TIMEOUT
    )
    if error is not None:
        return error
    return json.dumps({"status": "ok"}), 200


@speakerid_bp.route("/speaker-identification/info", methods=["GET"])
def speaker_id_info():
    """Expose the speaker identification capability from the service registry (no Celery call)."""
    _, error = _authenticate_request(request.headers)
    if error is not None:
        return error

    service = resolve_speaker_id_service(request.args.get("serviceName"), ensure_alive=False)
    if service is None:
        return json.dumps({"enabled": False}), 404
    info = speaker_id_service_info(service)
    return (
        json.dumps(
            {
                "enabled": True,
                "modelId": info.get("model_id"),
                "dim": info.get("dim"),
                "serviceName": service.service_name,
            }
        ),
        200,
    )
