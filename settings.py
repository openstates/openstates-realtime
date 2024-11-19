import os

import boto3
import dj_database_url  # type: ignore

# Get secret and access key
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_SESSION_TOKEN = os.environ.get("AWS_SESSION_TOKEN")

# Get db paasword from AWS SSM
session = boto3.Session(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    aws_session_token=AWS_SESSION_TOKEN,
)

ssm = session.client("ssm")
parameter = ssm.get_parameter(
    Name=os.environ.get("STAGE_PARAM_NAME"), WithDecryption=True
)
POSTGRES_PASSWORD = os.environ.get(
    "POSTGRES_PASSWORD", parameter["Parameter"]["Value"]
)

# django settings for tests
SECRET_KEY = "test"
INSTALLED_APPS = (
    "django.contrib.contenttypes",
    "openstates.data",
)

MIDDLEWARE_CLASSES = ()
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_NAME", "test"),
        "USER": os.environ.get("POSTGRES_USER", "test"),
        "PASSWORD": POSTGRES_PASSWORD,
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}
TIME_ZONE = "UTC"
DATABASE_URL = os.environ.get("OVERRIDE_DATABASE_URL")
if DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
