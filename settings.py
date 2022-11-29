import os
import dj_database_url  # type: ignore
import boto3

# Get db paasword from AWS SSM
session = boto3.Session(profile_name="civic-eagle")
ssm = session.client("ssm")

parameter = ssm.get_parameter(
    Name=os.environ.get("STAGE_PARAM_NAME"), WithDecryption=True
)
POSTGRES_PASSWORD = parameter["Parameter"]["Value"]


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
