# Openstates Realtime Lambda
## Overview
This is a lambda function that is triggered by an upload of outputs from the openstates-scrapers to an S3 bucket. The 
lambda function then  parses the file  and inserts the data into a postgres database. The lambda function is written 
in python and uses the django library to connect to the database. The lambda function is deployed using Zappa.

## Setup
Run the following commands to setup the project
```bash
poetry install
```

## Deployment
 For the first deployment, run the following command
```bash
poetry run zappa deploy [stage]
```

For subsequent deployments, run the following command
```bash
poetry run zappa update [stage]
```

Where [stage] is the stage to deploy to. This can be either dev or prod.

## S3 Bucket Lifecyle
The S3 bucket that the lambda function is uses should have a lifecycle policy that deletes the files after 2 
days. The CLI command for this is below:
```bash
aws s3api put-lifecycle-configuration --bucket openstates-realtime-bills --lifecycle-configuration '{
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

**Note: Ensure that the `profile` in the `zappa_settings.json` file is set to the correct profile of the AWS account that 
has permissions to deploy the lambda function.**