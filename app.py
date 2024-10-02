import boto3
import datetime
import json
import logging
import os
import signal
import urllib.parse
from django.db import transaction  # type: ignore
from openstates.utils.instrument import Instrumentation

logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("s3transfer").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")
s3_resource = boto3.resource("s3")

stats = Instrumentation()


def process_import_function(event, context):
    """
    Process a file upload.

    Args:
        event (dict): The event object
        context (dict): The context object
    Returns:
        None

    Example for unique_jurisdictions:
    unique_jurisdictions = {
        "az": {
            "id": "ocd-jurisdiction/country:us/state:az/government",
            "keys": ["az/2021/2021-01-01.json"],
        }
    }

    """

    datadir = "/tmp/"

    # making this a set to avoid duplicate files in queue
    all_files = set()

    unique_jurisdictions = {}

    # Get the uploaded file's information
    messages = batch_retrieval_from_sqs()
    if not messages:
        return

    bucket = messages[0].get("bucket")
    file_archiving_enabled = os.environ.get("FILE_ARCHIVING_ENABLED")
    for message in messages:
        bucket = message.get("bucket")
        key = message.get("file_path")
        jurisdiction_id = message.get("jurisdiction_id")
        jurisdiction_name = message.get("jurisdiction_name")

        # Archiving processed realtime bills defaults to False, except it was
        # explicitly set on cli or on task-definitions Repo as <--archive>
        # or added on AWS admin console for os-realtime lambda function
        # config as FILE_ARCHIVING_ENABLED=True
        file_archiving_enabled = (
            message.get("file_archiving_enabled") or file_archiving_enabled
        )

        # for some reason, the key is url encoded sometimes
        key = urllib.parse.unquote(key, encoding="utf-8")

        # we want to ignore the trigger for files that are dumped in archive
        if key.startswith("archive"):
            return

        # Get the bytes from S3

        key_list = key.split("/")

        jurisdiction_abbreviation = key_list[0]  # e.g az, al, etc

        # we want to filter out unique jurisdiction

        if jurisdiction_abbreviation not in unique_jurisdictions:
            unique_jurisdictions[jurisdiction_abbreviation] = {
                "id": jurisdiction_id,
                "name": jurisdiction_name,
                "keys": [],
            }
        unique_jurisdictions[jurisdiction_abbreviation]["keys"].append(key)

        # name_of_file = key_list[-1]  # e.g. bills.json, votes.json, etc

        filedir = f"{datadir}{key}"

        # Check if the directory for jurisdiction exists
        dir_path = os.path.join(datadir, jurisdiction_abbreviation)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        all_files.add(filedir)
        # Download this file to writable tmp space.
        try:
            s3_client.download_file(bucket, key, filedir)
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            all_files.remove(filedir)
            continue
    # Process imports for all files per jurisdiction in a batch
    for abbreviation, juris in unique_jurisdictions.items():
        file_paths = juris["keys"]
        jur_id = juris["id"]
        logger.info(f"importing {jur_id}...")
        try:
            do_import(jur_id, f"{datadir}{abbreviation}")
            stats.write_stats(
                [
                    {
                        "metric": "objects",
                        "fields": {"realtime_import": 1},
                        "tags": {"jurisdiction": juris["name"]},
                    }
                ]
            )
            # Possible that these values are strings instead of booleans
            if (
                file_archiving_enabled
                and isinstance(file_archiving_enabled, bool)
            ) or file_archiving_enabled == "True":
                archive_files(bucket, file_paths)

            # delete object from original bucket
            s3_client.delete_object(Bucket=bucket, Key=file_paths)
            logger.info(f"Deleted files :: {file_paths}")
        except Exception as e:
            logger.error(
                f"Error importing jurisdiction {jur_id}: {e}"
            )  # noqa: E501
            continue

    logger.info(f"{len(all_files)} files processed")
    stats.close()


def remove_duplicate_message(items):
    """
    Remove duplicate messages from the list
    """

    # parse the JSON strings and create a list of dictionaries
    parsed_items = [json.loads(item) for item in items]

    # Use another list comprehension to create a list of unique dictionaries
    filtered_items = [
        dict(i)
        for i in set(tuple(i.items()) for i in parsed_items)  # noqa: E501
    ]

    return filtered_items


def archive_files(bucket, all_keys, dest="archive"):
    """
    Archive the processed file to avoid possible scenarios of race conditions.
    We currently use `meta.client.copy` instead of `client.copy` b/c
    it can copy multiple files via multiple threads, since we have batching
    in view.

    Args:
        bucket (str): The s3 bucket name
        all_keys (list): The key of the file to be archived
        dest (str): The destination folder to move the file to.
    Returns:
        None

    Example:
        >>> archive_processed_file("my-bucket", "my-file.json")
    """

    for key in all_keys:
        copy_source = {"Bucket": bucket, "Key": key}

        logger.info(f"Archiving file {key} to {dest}")

        try:
            s3_resource.meta.client.copy(
                copy_source,
                bucket,
                f"{dest}/{datetime.datetime.utcnow().date()}/{key}",  # noqa: E501
            )
        except Exception as e:
            logger.error(f"Error archiving file {key}: {e}")
            continue


def retrieve_messages_from_queue():
    """
    Get the file paths from the SQS.
    """

    # Create SQS client
    sqs = boto3.client("sqs")

    sqs_url = os.environ.get("SQS_QUEUE_URL")

    # Receive message from SQS queue
    response = sqs.receive_message(
        QueueUrl=sqs_url,
        AttributeNames=["SentTimestamp"],
        MaxNumberOfMessages=10,
        MessageAttributeNames=["All"],
        VisibilityTimeout=30,
        WaitTimeSeconds=1,
    )

    messages = response.get("Messages", [])
    message_bodies = []

    if messages:
        for message in messages:
            message_bodies.append(message.get("Body"))

            receipt_handle = message["ReceiptHandle"]

            # Delete received message from queue
            sqs.delete_message(QueueUrl=sqs_url, ReceiptHandle=receipt_handle)
            logger.debug(f"Received and deleted message: {receipt_handle}")
    return message_bodies


def batch_retrieval_from_sqs(batch_size=600):
    """
    Retrieve messages from SQS in batches
    """
    msg = []

    # SQS allows a maximum of 10 messages to be retrieved at a time
    for _ in range(batch_size // 10):
        msg.extend(retrieve_messages_from_queue())
    filtered_messages = remove_duplicate_message(msg)

    logger.info(
        f"message_count: {len(filtered_messages)} received & deleted from SQS"
    )
    return filtered_messages


def do_atomic(func, datadir, type_):
    """
    Run a function in an atomic transaction.

    Args:
        func (function): The function to run
        datadir (str): The directory to run the function on
        type_ (str): The type of import
    Returns:
        The return value of the function

    Note: This some imports usually timeout when there are no results for
     persons or there are more than one result for a unique person. This error
     is meant to be properly handled in the os-core project in the future.

    """
    with transaction.atomic():
        logger.info(f"Running {type_}...")
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(120)
            return func(datadir)
        except TimeoutError:
            logger.error(f"Timeout running {type_}")
            # noqa: E501
        finally:
            # deactivate the alarm
            signal.alarm(0)


def timeout_handler(signum, frame):
    raise TimeoutError("Timeout occurred while running the do_atomic function")


def do_import(jurisdiction_id: str, datadir: str) -> None:
    """
    Import data for a jurisdiction into DB

    Args:
        jurisdiction_id (str): The jurisdiction id
        datadir (str): The directory where the data is stored temproarily
    Returns:
        None

    """
    # import inside here because to avoid loading Django code unnecessarily
    from openstates.importers import (
        JurisdictionImporter,
        BillImporter,
        VoteEventImporter,
        EventImporter,
    )
    from openstates.data.models import Jurisdiction

    # datadir = os.path.join(settings.SCRAPED_DATA_DIR, state)

    juris_importer = JurisdictionImporter(jurisdiction_id)
    # bills postimport disabled because bill postimport does some expensive SQL
    # that we want this to be fast
    bill_importer = BillImporter(jurisdiction_id, do_postimport=False)
    # votes postimport disabled because it will delete all vote events for the
    # related bill except the vote event being processed now, causing votes to
    # be deleted and re-created
    vote_event_importer = VoteEventImporter(
        jurisdiction_id, bill_importer, do_postimport=False
    )
    event_importer = EventImporter(jurisdiction_id, vote_event_importer)
    logger.info(f"Datadir: {datadir}")

    do_atomic(juris_importer.import_directory, datadir, "jurisdictions")
    do_atomic(bill_importer.import_directory, datadir, "bill")  # noqa: E501
    do_atomic(vote_event_importer.import_directory, datadir, "vote_event")
    do_atomic(event_importer.import_directory, datadir, "event")  # noqa: E501
    Jurisdiction.objects.filter(id=jurisdiction_id).update(
        latest_bill_update=datetime.datetime.utcnow()
    )
