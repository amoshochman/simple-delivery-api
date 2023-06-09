from flask import Flask, request, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from marshmallow import ValidationError
from models import Timeslot, Delivery, Address, db, as_dict
from schemas import AddressSchema, OneLineAddressSchema, DeliverySchema
from functools import wraps
import requests
from requests.structures import CaseInsensitiveDict
import urllib.parse
import json
from datetime import date, timedelta
from dotenv import load_dotenv
import os
from common_utils import get_date_for_timeslot, get_deliveries_num_per_date, InvalidTimeSlotException, \
    get_deliveries_num_per_timeslot

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///delivery-api.sqlite3'
db.init_app(app)

load_dotenv()

geoapify_key = os.getenv("GEO_APIFY_KEY")

MAX_DELIVERIES_PER_DAY = 10
MAX_DELIVERIES_PER_TIMESLOT = 2


def required_params(schema):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                schema.load(request.get_json())
            except ValidationError as err:
                error = {
                    "status": "error",
                    "messages": err.messages
                }
                return jsonify(error), 400
            return fn(*args, **kwargs)

        return wrapper

    return decorator


@app.post('/timeslots')
@required_params(AddressSchema())
def timeslots():
    postcode = request.get_json()['postcode']
    timeslots = Timeslot.query.filter_by(postcode=postcode).all()
    return [as_dict(timeslot) for timeslot in timeslots]


@app.post('/resolve-address')
@required_params(OneLineAddressSchema())
def resolve_address():
    address = request.get_json()['searchTerm']
    address_for_url = urllib.parse.quote(address)
    url = "https://api.geoapify.com/v1/geocode/search?text=" + address_for_url + "&apiKey=" + geoapify_key
    headers = CaseInsensitiveDict()
    headers["Accept"] = "application/json"
    resp = requests.get(url, headers=headers)
    parsed_address = json.loads(resp.content)['query']['parsed']
    return parsed_address


def get_max_capacity_error(max_capacity_reached, max_capacity_reached_for, max_capacity_reached_for_id):
    return "Maximum business capacity (" + str(
        max_capacity_reached) + ") reached for the requested " + max_capacity_reached_for + " " + str(
        max_capacity_reached_for_id)


@app.post('/deliveries')
@required_params(DeliverySchema())
def deliveries():
    input_json = request.get_json()
    timeslot_id = input_json['timeslotId']
    if MAX_DELIVERIES_PER_TIMESLOT <= get_deliveries_num_per_timeslot(timeslot_id):
        error = get_max_capacity_error(MAX_DELIVERIES_PER_TIMESLOT, "timeslot", timeslot_id)
        return Response(error, status=400)
    try:
        timeslot_date = get_date_for_timeslot(timeslot_id)
    except InvalidTimeSlotException:
        return Response("Timeslot " + str(timeslot_id) + " not found", status=400)
    if MAX_DELIVERIES_PER_DAY <= get_deliveries_num_per_date(timeslot_date):
        error = get_max_capacity_error(MAX_DELIVERIES_PER_DAY, "date", timeslot_date)
        return Response(error, status=400)
    user_id = input_json['userId']
    new_delivery = Delivery(user_id, timeslot_id)
    db.session.add(new_delivery)
    db.session.commit()
    return as_dict(new_delivery)


@app.delete('/deliveries/<int:delivery_id>')
def delete_delivery(delivery_id):
    delivery = Delivery.query.get(delivery_id)
    if not delivery:
        return Response("Delivery " + str(delivery_id) + " not found", status=400)
    delivery.status = "cancelled"
    db.session.commit()
    return as_dict(delivery)


@app.get('/deliveries/daily')
def deliveries_daily():
    deliveries = Delivery.query.join(Timeslot).filter(func.date(Timeslot.start_time) == date.today()).all()
    return [as_dict(delivery) for delivery in deliveries]


@app.get('/deliveries/weekly')
def deliveries_weekly():
    weekday = date.today().weekday()
    week_start = date.today() - timedelta(days=weekday)
    week_end = week_start + timedelta(days=6)
    deliveries = Delivery.query.join(Timeslot).filter(week_start <= func.date(Timeslot.start_time))
    deliveries = deliveries.filter(func.date(Timeslot.start_time) <= week_end).all()
    return [as_dict(delivery) for delivery in deliveries]


# if __name__ == '__main__':
#     app.run(host='localhost', port=8000, debug=True, use_reloader=True)
