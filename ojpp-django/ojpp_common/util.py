import csv
import math
import warnings
from collections import defaultdict
from datetime import datetime, timedelta, date
from functools import cache
from typing import Iterable, List, Callable

import requests
from django.apps import apps
from django.contrib import messages
from django.contrib.gis.geos import Point
from django.db import transaction
from django.db.models import Model, QuerySet
from django.utils.html import format_html
from urllib.parse import quote as urlquote

from ojpp_common.models import Schedule, StopTime
from ojpp_common.metrics import G_DISCARDED_LOCATIONS, G_DISCARDED_BY_TIME, G_DISCARDED_BY_COORDS


def merge_model_objects(primary_object, alias_objects=[], keep_old=False):
    from django.contrib.contenttypes.fields import GenericForeignKey
    """
    Use this function to merge model objects (i.e. Users, Organizations, Polls,
    etc.) and migrate all of the related fields from the alias objects to the
    primary object.

    Usage:
    from django.contrib.auth.models import User
    primary_user = User.objects.get(email='good_email@example.com')
    duplicate_user = User.objects.get(email='good_email+duplicate@example.com')
    merge_model_objects(primary_user, duplicate_user)
    """
    if not isinstance(alias_objects, list):
        alias_objects = [alias_objects]

    # check that all aliases are the same class as primary one and that
    # they are subclass of model
    primary_class = primary_object.__class__

    if not issubclass(primary_class, Model):
        raise TypeError('Only django.db.models.Model subclasses can be merged')

    for alias_object in alias_objects:
        if not isinstance(alias_object, primary_class):
            raise TypeError('Only models of same class can be merged')

    # Get a list of all GenericForeignKeys in all models
    # TODO: this is a bit of a hack, since the generics framework should provide a similar
    # method to the ForeignKey field for accessing the generic related fields.
    generic_fields = []
    for model_map in apps.all_models.values():
        for model in model_map.values():
            for field_name, field in filter(lambda x: isinstance(x[1], GenericForeignKey), model.__dict__.items()):
                generic_fields.append(field)

    # Loop through all alias objects and migrate their data to the primary object.
    for alias_object in alias_objects:
        # Migrate all foreign key references from alias object to primary object.
        links = [
            f for f in alias_object._meta.get_fields()
            if (f.one_to_many or f.one_to_one) and f.auto_created and not f.concrete
        ]
        for related_object in links:
            # The variable name on the alias_object model.
            alias_varname = related_object.get_accessor_name()
            # The variable name on the related model.
            obj_varname = related_object.field.name
            related_objects = getattr(alias_object, alias_varname)
            for obj in related_objects.all():
                setattr(obj, obj_varname, primary_object)
                obj.save()

        # Migrate all many to many references from alias object to primary object.
        links = [
            f for f in alias_object._meta.get_fields()
            if f.many_to_many and f.auto_created and not f.concrete
        ]
        for related_many_object in links:
            alias_varname = related_many_object.get_accessor_name()
            obj_varname = related_many_object.field.name

            if alias_varname is not None:
                # standard case
                related_many_objects = getattr(alias_object, alias_varname).all()
            else:
                # special case, symmetrical relation, no reverse accessor
                related_many_objects = getattr(alias_object, obj_varname).all()
            for obj in related_many_objects.all():
                getattr(obj, obj_varname).remove(alias_object)
                getattr(obj, obj_varname).add(primary_object)

        # Migrate all generic foreign key references from alias object to primary object.
        for field in generic_fields:
            filter_kwargs = {}
            filter_kwargs[field.fk_field] = alias_object._get_pk_val()
            filter_kwargs[field.ct_field] = field.get_content_type(alias_object)
            for generic_related_object in field.model.objects.filter(**filter_kwargs):
                setattr(generic_related_object, field.name, primary_object)
                generic_related_object.save()

        # Try to fill all missing values in primary object by values of duplicates
        filled_up = set()
        for field_name in [field.attname for field in primary_object._meta.local_fields if field.attname != 'id']:
            primary_val = getattr(primary_object, field_name)
            alias_val = getattr(alias_object, field_name)

            if alias_val not in [None, '']:
                if isinstance(alias_val, list) and isinstance(primary_val, list):
                    alias_val = list(set(primary_val + alias_val))
                setattr(primary_object, field_name, alias_val)
                filled_up.add(field_name)

        if not keep_old:
            alias_object.delete()
    primary_object.save()
    return primary_object


def merge_objects_action(modeladmin, request, queryset):
    with transaction.atomic():
        primary_object = queryset.first()
        alias_objects = queryset.exclude(pk=primary_object.pk)
        obj = merge_model_objects(primary_object, list(alias_objects))
        msg_dict = {
            "name": modeladmin.opts.verbose_name,
            "obj": format_html('<a href="{}">{}</a>', urlquote(request.path), obj),
        }
        msg = format_html("The {name} objects were merged successfully: “{obj}”", **msg_dict)
        modeladmin.message_user(request, msg, messages.SUCCESS)
    # url = reverse('admin:%s_%s_change' % (obj._meta.app_label, obj._meta.model_name), args=[obj.id])
    # return redirect(url)


async def interpolate_bearing(locations, operator):
    from ojpp_common.models import VehicleLocation
    now = datetime.now().astimezone() - timedelta(minutes=5)
    loc_map = {loc['vehicle_id']: loc for loc in locations}
    qs = VehicleLocation.objects.prefetch_related('vehicle').order_by(
        'vehicle_id', '-time', ).distinct('vehicle_id').filter(time__gt=now, vehicle__operator_id=operator.id)
    async for loc in qs:
        if loc.vehicle_id not in loc_map:
            continue

        loc1 = loc.location
        loc2 = loc_map[loc.vehicle_id]['location']
        # calculate bearing using arctangent
        bearing = math.degrees(math.atan2(loc2.x - loc1.x, loc2.y - loc1.y)) % 360

        loc_map[loc.vehicle_id]['bearing'] = bearing
    return loc_map.values()


vehicle_last_timestamp = defaultdict(lambda: None)
vehicle_last_point = defaultdict(lambda: Point(0,0))

def deduplicate_locations(og_locations: Iterable[dict]) -> List[dict]:
    count_point = 0
    count_timestamp = 0
    locations = []
    for vehicle_loc in og_locations:
        vid = vehicle_loc['vehicle_id']
        if vehicle_last_point[vid].equals(vehicle_loc['location']):
            count_point += 1
            continue
        if vehicle_last_timestamp[vid] == vehicle_loc['time']:
            count_timestamp += 1
            continue
        locations.append(vehicle_loc)
        vehicle_last_timestamp[vid] = vehicle_loc['time']
        vehicle_last_point[vid] = vehicle_loc['location']
    print('\t Removed ', count_point, ' because of location and ', count_timestamp, ' because of timestamp')
    G_DISCARDED_BY_TIME.set(count_timestamp)
    G_DISCARDED_BY_COORDS.set(count_point)
    return locations

holiday_cache = None

def get_holidays(year_from=0, year_to=9999):
    global holiday_cache
    if holiday_cache is None:
        resp = requests.get('https://podatki.gov.si/dataset/ada88e06-14a2-49c4-8748-3311822e3585/resource/eb8b25ea-5c00-4817-a670-26e1023677c6/download/seznampraznikovindelaprostihdni20002030.csv')
        rdr = csv.DictReader(resp.text.splitlines(), delimiter=';')
        holiday_cache = {date(int(r['LETO']), int(r['MESEC']), int(r['DAN'])) for r in rdr if r['DELA_PROST_DAN'] == 'da'}  # noqa
    return {d for d in holiday_cache if year_from <= d.year <= year_to}


def is_holiday(d):
    holidays = get_holidays()
    if d.year > 2030:
        warnings.warn('Podatki o praznikih so zastareli!')
    return d in holidays


#
#   Računanje delovnega vektorja (glej stran 87 D_DS3.12A)
#


def sneaky_cache(obj: object, key: str, func: Callable):
    """Sneaky cache: attach a cache to the object to preserve it between function calls"""
    if hasattr(obj, key):
        return getattr(obj, key)
    val = func()
    setattr(obj, key, val)
    return val

def is_schedule_active(schedule: Schedule, d: date):
    """Check if a schedule is running on this date"""
    exceptions = sneaky_cache(schedule, '_exceptions', lambda: list(schedule.exceptions.all()))
    # Exceptions don't have an order
    for exception in exceptions:
        if exception.date == d:
            return exception.action

    periods = sneaky_cache(schedule, '_periods', lambda: sorted(schedule.periods.all(), key=lambda p: -p.id))
    # Since this is supposed to evaluated in order, we need to do it in reverse
    for period in periods:
        # period.day_to >= d.day >= period.day_from and period.month_to >= d.month >= period.month_from:
        if (period.day_from <= d.day and period.month_from <= d.month) and (period.day_to >= d.day and period.month_to >= d.month):
            if d.weekday() in period.days_of_week():
                return period.action
            elif period.holidays and is_holiday(d):
                return period.action

    return schedule.default_state

def calculate_active_days(schedule: Schedule, year):
    """Seznam dni (date) na katere je režim aktiven"""
    mask = []
    d = date(year, 1, 1)
    while d := d + timedelta(days=1):
        if d.year != year:
            break
        active = is_schedule_active(schedule, d)
        if active:
            mask.append(d)
    return mask

def calculate_active_days_mask(schedule: Schedule, year):
    """Seznam vrednosti ali je režim aktiven (list[bool]) za vsak dan v letu"""
    mask = []
    d = date(year, 1, 1)
    while d := d + timedelta(days=1):
        if d.year != year:
            break
        active = is_schedule_active(schedule, d)
        mask.append(active)
    return mask


@cache
def get_schedules_for_date(date: date) -> Iterable[Schedule]:
    return [
        schedule for schedule in Schedule.objects.prefetch_related('periods', 'exceptions')
        if is_schedule_active(schedule, date)
    ]


def get_times_for_active_trips(stoplocation_id, date: date) -> QuerySet[StopTime]:
    schedules = get_schedules_for_date(date)
    times = StopTime.objects.filter(stop_location_id=stoplocation_id, trip__schedule__in=schedules, active=True)
    return times

def format_timedelta(td):
    # Python formats negative timedeltas as "-1 day, 23:59:59.999999"
    # This formats it normally but with a - sign
    if td < timedelta(0):
        return '-' + format_timedelta(-td)
    else:
        return str(td)