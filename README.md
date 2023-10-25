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
