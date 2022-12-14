import boto3
import datetime
import logging
import os
from django.db import transaction  # type: ignore
from openstates.cli.reports import generate_session_report
import urllib.parse

logger = logging.getLogger("openstates")
s3_client = boto3.client("s3")
s3_resource = boto3.resource("s3")


def archive_processed_file(bucket, key):
    """
    Archive the processed file to avoid possible scenarios of race conditions.
    We currently use meta.client.copy instead of client.copy b/c it can copy
    multiple files via multiple threads, since we have batching in view.

    Args:
        bucket (str): The s3 bucket name
        key (str): The key of the file to be archived
    Returns:
        None

    Example:
        >>> archive_processed_file("my-bucket", "my-file.json")
    """

    copy_source = {"Bucket": bucket, "Key": key}

    s3_resource.meta.client.copy(copy_source, bucket, f"archive/{key}")
    logger.info(f"Archived file :: {key}")

    # delete object from original bucket
    s3_client.delete_object(Bucket=bucket, Key=key)
    logger.info(f"Deleted file :: {key}")


def process_upload_function(event, context):
    """
    Process a file upload.

    Args:
        event (dict): The event object
        context (dict): The context object
    Returns:
        None
    """

    # Get the uploaded file's information
    bucket = event["Records"][0]["s3"]["bucket"]["name"]  # Will be `my-bucket`
    key = event["Records"][0]["s3"]["object"][
        "key"
    ]  # Will be the file path of whatever file was uploaded.

    # for some reason, the key is url encoded sometimes
    key = urllib.parse.unquote(key, encoding="utf-8")

    # we want to ignore the event trigger for files that are dumped in archive
    if key.startswith("archive"):
        return

    # Get the bytes from S3
    datadir = "/tmp/"

    key_list = key.split("/")

    jurisdiction_acronym = key_list[0]  # e.g az, al, etc

    name_of_file = key_list[-1]  # e.g. bills.json, votes.json, etc
    filedir = f"{datadir}{name_of_file}"

    s3_client.download_file(
        bucket, key, filedir
    )  # Download this file to writable tmp space.

    jurisdiction_id = (
        f"ocd-jurisdiction/country:us/state:{jurisdiction_acronym}/government"
    )

    logger.info(f"importing {jurisdiction_id}...")
    do_import(jurisdiction_id, datadir)

    try:
        os.remove(filedir)
    except Exception as e:

        logger.warning(f"Failed to remove file :: {e}")
    finally:
        logger.info(">>>> DONE IMPORTING <<<<")

    # archive the file
    archive_processed_file(bucket, key)


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
    from openstates.data.models import Jurisdiction as DatabaseJurisdiction

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
        DatabaseJurisdiction.objects.filter(id=jurisdiction_id).update(
            latest_bill_update=datetime.datetime.utcnow()
        )

    # compile info on all sessions that were updated in this run
    seen_sessions = set()
    seen_sessions.update(bill_importer.get_seen_sessions())
    seen_sessions.update(vote_event_importer.get_seen_sessions())
    for session in seen_sessions:
        generate_session_report(session)
