import logging
import requests
import json

from itertools import chain, islice
from datetime import datetime
from google.cloud import datastore
from flask import Flask, request
from requests_oauthlib import OAuth1Session
from collections import namedtuple

app = Flask(__name__)

Sensor = namedtuple('Sensor', ['id', 'name', 'max_timestamp'])


def get_sensors(telldus):
    url = 'https://api.telldus.com/json/sensors/list'
    res = telldus.get(url)

    if res.status_code != 200:
        raise Exception('failed', res.content)

    sensors = [
        get_sensor(s)
        for s in json.loads(res.content)['sensor']
    ]

    return sensors


def get_sensor(s):
    sensor_id = int(s['id'])
    sensor_name = s['name']

    ds = datastore.Client()
    entity = ds.get(ds.key('sensors', str(sensor_id)))

    return Sensor(sensor_id, sensor_name, entity.get('max_timestamp', 0))


def get_sensor_values(telldus, sensor):
    url = 'https://api.telldus.com/json/sensor/history'
    app.logger.info('fetching sensor values for %d from %d', sensor.id, sensor.max_timestamp)
    res = telldus.get(url, params={'id': sensor.id, 'from': sensor.max_timestamp})

    if res.status_code != 200:
        raise Exception('failed', res.content)

    events = json.loads(res.content)['history']

    for event in events:
        data_points = event['data']
        for data_point in data_points:
            data_point['ts'] = event['ts']
            data_point['sensor'] = sensor.id
            yield data_point


def prepare_sensor_value(data_point):
    sensor = data_point['sensor']
    timestamp = datetime.utcfromtimestamp(data_point['ts'])
    name = data_point['name']
    typ = {'temp': u'temperature'}.get(name, name)
    value = data_point['value']
    key = '%s-%d' % (typ, data_point['ts'])

    return key, {
        'sensor': sensor,
        'timestamp': timestamp,
        'type': typ,
        'value': float(value)
    }


def update_sync_time(sensor, max_timestamp, last_sync):
    ds = datastore.Client()
    ds_key = ds.key('sensors', str(sensor.id))
    entity = datastore.Entity(key=ds_key)
    value = {
        'last_sync': last_sync,
        'max_timestamp': max_timestamp,
        'name': sensor.name,
        'id': sensor.id
    }
    entity.update(value)
    ds.put(entity)

    return Sensor(sensor.id, sensor.name, max_timestamp)


def store_sensor_values(sensor, rows):
    ds = datastore.Client()
    created_at = datetime.utcnow()

    max_ts = sensor.max_timestamp
    entities = []
    for row in rows:
        key, value = prepare_sensor_value(row)
        max_ts = max(max_ts, row['ts'])
        ds_key = ds.key('sensor_values', key)
        entity = datastore.Entity(key=ds_key)
        value['created_at'] = created_at

        entity.update(value)
        entities.append(entity)

    for chunk in chunks(entities, size=500):
        ds.put_multi(chunk)

    update_sync_time(sensor, max_ts, created_at)

    return len(entities)


def chunks(iterable, size=10):
    iterator = iter(iterable)
    for first in iterator:
        yield chain([first], islice(iterator, size - 1))


def get_config():
    ds = datastore.Client()
    client_key = ds.get(ds.key('settings', 'CLIENT_KEY'))['value']
    client_secret = ds.get(ds.key('settings', 'CLIENT_SECRET'))['value']
    resource_owner_key = ds.get(
        ds.key('settings', 'RESOURCE_OWNER_KEY'))['value']
    resource_owner_secret = ds.get(
        ds.key('settings', 'RESOURCE_OWNER_SECRET'))['value']

    return client_key, client_secret, resource_owner_key, resource_owner_secret


@app.route('/sync', methods=['GET'])
def sync():
    client_key, client_secret, resource_owner_key, resource_owner_secret = get_config(
    )
    telldus = OAuth1Session(
        client_key,
        client_secret=client_secret,
        resource_owner_key=resource_owner_key,
        resource_owner_secret=resource_owner_secret)
    sensors = get_sensors(telldus)

    stored_total = 0
    for sensor in sensors:
        stored = store_sensor_values(sensor, get_sensor_values(telldus, sensor))
        stored_total += stored
        app.logger.info('synced %d values for sensor %d', stored, sensor.id)

    return 'synced %d sensor values' % stored_total, 200


@app.errorhandler(500)
def server_error(e):
    logging.exception('An error occurred during a request.')
    return 'An internal error occurred.', 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
