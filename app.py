import datetime
import logging
import os
import typing

import boto3
from django.db import transaction  # type: ignore
from openstates.cli.reports import generate_session_report


logger = logging.getLogger("openstates")
s3_client = boto3.client('s3')


def process_upload_function(event, context):
    """
    Process a file upload.
    """

    # Get the uploaded file's information
    bucket = event['Records'][0]['s3']['bucket']['name']  # Will be `my-bucket`
    key = event['Records'][0]['s3']['object']['key']  # Will be the file path of whatever file was uploaded.

    # Get the bytes from S3
    datadir = "/tmp/"

    state_acronym = key.split("/")[0]  # e.g az, al, etc

    name_of_file = key.split("/")[-1]  # e.g. bills.json, votes.json, etc
    filedir = f"{datadir}{name_of_file}"

    s3_client.download_file(bucket, key, filedir)  # Download this file to writable tmp space.

    jurisdiction_id = f"ocd-jurisdiction/country:us/state:{state_acronym}/government"

    logger.info(f"importing {jurisdiction_id}...")
    do_import(jurisdiction_id, datadir)

    try:
        os.remove(filedir)
    except Exception as e:
        pass
    finally:
        logger.info(">>>> DONE IMPORTING <<<<")


def do_import(jurisdiction_id: str, datadir: str) -> dict[str, typing.Any]:
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
        logger.info("import bills...")
        report.update(bill_importer.import_directory(datadir))
        logger.info("import vote events...")
        report.update(vote_event_importer.import_directory(datadir))
        logger.info("import events...")
        report.update(event_importer.import_directory(datadir))

        DatabaseJurisdiction.objects.filter(id=jurisdiction_id).update(
            latest_bill_update=datetime.datetime.utcnow()
        )

    # compile info on all sessions that were updated in this run
    seen_sessions = set()
    seen_sessions.update(bill_importer.get_seen_sessions())
    seen_sessions.update(vote_event_importer.get_seen_sessions())
    for session in seen_sessions:
        generate_session_report(session)
