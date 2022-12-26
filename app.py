import boto3
import datetime
import logging
import os
from django.db import transaction  # type: ignore
from openstates.cli.reports import generate_session_report
import urllib.parse
import json

logger = logging.getLogger("openstates")
s3_client = boto3.client("s3")
s3_resource = boto3.resource("s3")


def archive_file(bucket, all_keys, dest="archive"):
    """
    Archive the processed file to avoid possible scenarios of race conditions.
    We currently use meta.client.copy instead of client.copy b/c it can copy
    multiple files via multiple threads, since we have batching in view.

    Args:
        bucket (str): The s3 bucket name
        all_keys (list): The key of the file to be archived
        dest (str): The destination folder to move the file to
    Returns:
        None

    Example:
        >>> archive_processed_file("my-bucket", "my-file.json")
    """

    for key in all_keys:
        copy_source = {"Bucket": bucket, "Key": key}

        s3_resource.meta.client.copy(copy_source, bucket, f"{dest}/{key}")
        logger.info(f"Archived file :: {key}")

        # delete object from original bucket
        s3_client.delete_object(Bucket=bucket, Key=key)
        logger.info(f"Deleted file :: {key}")


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
        VisibilityTimeout=0,
        WaitTimeSeconds=0,
    )

    messages = response.get("Messages", [])
    message_bodies = []

    if messages:

        for message in messages:
            message_bodies.append(message.get("Body"))

            receipt_handle = message["ReceiptHandle"]

            # Delete received message from queue
            sqs.delete_message(QueueUrl=sqs_url, ReceiptHandle=receipt_handle)
            logger.info(f"Received and deleted message: {message}")

    return message_bodies


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
    all_files = []

    unique_jurisdictions = {}

    # Get the uploaded file's information
    messages = retrieve_messages_from_queue()
    if not messages:
        return

    bucket = messages[0].get("bucket")

    for message in messages:
        message = json.loads(message)
        bucket = message.get("bucket")
        key = message.get("file_path")
        jurisdiction_id = message.get("jurisdiction_id")

        # for some reason, the key is url encoded sometimes
        key = urllib.parse.unquote(key, encoding="utf-8")

        # we want to ignore the trigger for files that are dumped in archive
        if key.startswith("archive"):
            return

        # Get the bytes from S3

        key_list = key.split("/")

        jurisdiction_abbreviation = key_list[0]  # e.g az, al, etc

        # we want to filter out unique jurisdiction

        unique_jurisdictions[jurisdiction_abbreviation]["id"] = jurisdiction_id
        unique_jurisdictions[jurisdiction_abbreviation]["keys"].append(key)

        name_of_file = key_list[-1]  # e.g. bills.json, votes.json, etc
        filedir = f"{datadir}{name_of_file}"

        all_files.append(filedir)
        # Download this file to writable tmp space.
        s3_client.download_file(bucket, key, filedir)

    # Process imports for all files per jurisdiction in a batch
    for abbreviation, juris in unique_jurisdictions.items():

        logger.info(f"importing {juris['id']}...")
        try:
            do_import(juris[id], f"{datadir}{abbreviation}")
        except Exception as e:
            logger.error(f"Error importing {juris['id']}: {e}")
            # TODO: Move files to error directory
            continue
        archive_file(bucket, juris["keys"])

    for file in all_files:
        try:
            os.remove(file)
        except Exception as e:

            logger.warning(f"Failed to remove file :: {e}")
        finally:
            logger.info(">>>> DONE IMPORTING <<<<")

        # archive the files


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
    bill_importer = BillImporter(jurisdiction_id)
    vote_event_importer = VoteEventImporter(jurisdiction_id, bill_importer)
    event_importer = EventImporter(jurisdiction_id, vote_event_importer)
    report = {}
    logger.info(f"Datadir: {datadir}")
    with transaction.atomic():
        logger.info("import jurisdictions...")
        report.update(juris_importer.import_directory(datadir))

    with transaction.atomic():
        logger.info("import bills...")
        report.update(bill_importer.import_directory(datadir))

    with transaction.atomic():
        logger.info("import vote events...")
        report.update(vote_event_importer.import_directory(datadir))

    with transaction.atomic():
        logger.info("import events...")
        report.update(event_importer.import_directory(datadir))

    with transaction.atomic():
        Jurisdiction.objects.filter(id=jurisdiction_id).update(
            latest_bill_update=datetime.datetime.utcnow()
        )

    # compile info on all sessions that were updated in this run
    seen_sessions = set()
    seen_sessions.update(bill_importer.get_seen_sessions())
    seen_sessions.update(vote_event_importer.get_seen_sessions())
    for session in seen_sessions:
        generate_session_report(session)
