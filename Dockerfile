FROM python:3.9-alpine
RUN apk add --update --no-cache build-base libffi-dev

ENV AWS_ACCESS_KEY_ID=XXXXX
ENV AWS_SECRET_ACCESS_KEY=XXXXX
ENV AWS_DEFAULT_REGION=us-east-1

RUN pip install poetry

COPY . /app

WORKDIR /app

RUN poetry install --no-root

RUN poetry run zappa update prod
