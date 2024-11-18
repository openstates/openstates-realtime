# Openstates Realtime Lambda

## Overview

This is a lambda function that is triggered by an upload of outputs from the openstates-scrapers to an S3 bucket. The
lambda function then parses the file and inserts the data into a postgres database. The lambda function is written
in python and uses the django library to connect to the database. The lambda function is deployed using Zappa.

## Setup

Run the following commands to setup the project

```bash
poetry install
```

### ZAPPA BUG NOTE

Please note that right now setuptools is pinned to an old version to mitigate a Zappa bug that was very recently fixed,
but seems to not be released in any easy-to-poetry-install way. [Bug details here.](https://github.com/zappa/Zappa/issues/1349)

## Deployment

Deployment depends on setup above, as well as having the
[AWS CLI installed](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) and a login profile
for the CLI that has access to the Open States AWS project. You will use `AWS_DEFAULT_PROFILE` in commands below to
indicate the name of that login profile. In these examples it will be `openstates`.


For the first deployment, run the following command

```bash
AWS_DEFAULT_PROFILE=openstates poetry run zappa deploy [stage]
```

For subsequent deployments, run the following command

```bash
AWS_DEFAULT_PROFILE=openstates poetry run zappa update [stage]
```

Where [stage] is the stage to deploy to. This can be either dev or prod.

## Deploy via Docker
- Make a copy of Dockerfile-example to create Dockerfile
- Update  `AWS_ACCESS_KEY_ID` and  `AWS_SECRET_ACCESS_KEY` with your creds
- Run `docker build --progress=plain .`

## S3 Bucket Lifecyle

The S3 bucket that the lambda function is uses should have a lifecycle policy that deletes the files after 2
days. The CLI command for this is below:

```bash
aws s3api put-bucket-lifecycle-configuration --bucket openstates-realtime-bills --lifecycle-configuration '{
  "Rules": [
    {
      "Status": "Enabled",
      "Filter": {
        "Prefix": "archive/"
      },
      "Expiration": {
        "Days": 2
      },
      "ID": "Delete after 2 days"
    }
  ]
}'
```

## Debug a realtime processing import failure

If realtime data processing fails for a particular jurisdiction batch, you'll see a message in the AWS Lambda logs
that looks like this:

> 17:37:32 ERROR root: Error importing jurisdiction ocd-jurisdiction/country:us/government, stored snapshot of
> import dir as archive/usa-2024-11-18T17:37:31.789982.zip, error: get() returned more than one VoteEvent -- 
> it returned 2!

The error message will of course vary, but the "Error importing jurisdiction" text is a key you can look for regardless.
As the message indicates, the code now stores a zipfile containing the objects that were included in the juris-batch
for which import was attempted. In this case the file is available within the realtime processing S3 bucket at the
obejct prefix `archive/usa-2024-11-18T17:37:31.789982.zip`. 

This file is an import failure snapshot, and consists of pertaining to one specific jurisdiction import batch. The
entrypoint function does the work of collecting a bunch of SQS messages, sorting data from those into jurisdictions,
and then executing import for individual jurisdiction (sub) batches. These instructions are for debugging one particular
snapshot.

To debug this failure locally, follow these steps:

1. Download the file to your machine
2. Unzip the file so that its contents occupy a unique directory, i.e. `unzip -d usa-2024-11-18T17:37:31.789982 usa-2024-11-18T17:37:31.789982.zip`
3. Decide if you are testing the import into a LOCAL database, or into the AWS Open States database.
4. Prepare parameters for running `app.py`: `do_import`, `{os_jurisdiction_id}`, `{path_to_snapshot_folder}`
    * `do_import` this tells app.py to run the `do_import` function, rather than exec the whole entrypoint function
    * `{os_jurisdiction_id}` in the form `ocd-jurisdiction/country:us/state:ma/government`
    * `{path_to_snapshot_folder}` which should be a path to the folder you unzipped into, like
      `/path/to/usa-2024-11-18T17:37:31.789982`
5. Prepare environment variables for running `app.py`
    * `AWS_DEFAULT_PROFILE`: necessary if importing into the AWS Open States database, to access parameter store
    * `STAGE_PARAM_NAME=/passwords/os_realtime_bill`: necessary if importing into the AWS OS DB
    * `POSTGRES_HOST`: hostname for the database into which you will import
    * `POSTGRES_NAME`: name of the postgres database
    * `POSTGRES_USER`: name of the postgres database user account
    * `DJANGO_SETTINGS_MODULE=settings`
6. Execute the script with the above parameters and env vars

You should now be able to reproduce whatever error occurred during the original import of that batch, including the
ability to step it through the debugger.
