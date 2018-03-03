# telldus-sensor-sync

Sync telldus sensor sticks to google cloudstore

## Deploy

The application is built for running on Google app engine

### Application

```
gcloud app deploy app.yaml
```

### Cron schedule

```
gcloud app deploy cron.yaml
```

## Development

Set up virtualenv and download dependencies.

```
virtualenv env
source env/bin/activate
pip install -r requirements.txt
```
Run with

```
GOOGLE_APPLICATION_CREDENTIALS=path_to_credentials.json python main.py
```
