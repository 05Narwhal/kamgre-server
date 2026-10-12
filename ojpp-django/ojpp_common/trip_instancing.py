import logging
import os
from datetime import timedelta
from typing import Optional


if __name__ == '__main__':
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ojpp_core.settings')
    django.setup()

from django.contrib.gis.db.models.functions import Distance

from ojpp_common.models import VehicleLocation, TripInstance, StopTimeInstance, Vehicle, Trip

MAX_STALE_TRIP_INSTANCE = timedelta(hours=6)
MAX_DISTANCE_METERS = 100

logger = logging.getLogger(__name__)

LAST_STOPTIME_CACHE = {}
def get_last_stoptime(trip: Trip, vehicle: Vehicle) -> Optional[StopTimeInstance]:
    key = (trip.id, vehicle.id)
    #if key in LAST_STOPTIME_CACHE:
    #    return LAST_STOPTIME_CACHE[key]
    st = StopTimeInstance.objects.filter(trip_instance__trip=trip, trip_instance__vehicle=vehicle).order_by('-time_arrival').first()
    LAST_STOPTIME_CACHE[key] = st
    return st

def process_vehicle_location(loc: VehicleLocation):
    if loc.trip is None:
        logger.debug(f"  Location has no trip: {loc}")
        return
    last_stoptime_instance = get_last_stoptime(loc.trip, loc.vehicle)
    last_seq = last_stoptime_instance.stoptime.sequence_num if last_stoptime_instance else 0

    # Find possible stops, which need to be:
    #  - in the future (sequence_num is bigger than the last one)
    #  - within the radius
    nearest_stoptimes = loc.trip.stoptimes.annotate(
        distance=Distance('stop_location__location', loc.location)
    ).filter(
        sequence_num__gt=last_seq,
        distance__isnull=False,  # TODO: why is distance sometimes null?
    ).order_by('distance')  # Relies on rows being naturally sorted by seq

    stoptime = nearest_stoptimes.first()

    # If none are found, skip this location - not entirely sure how this can happen
    if not stoptime:
        logger.debug(f"    No stoptime found for {loc}")
        return
    if stoptime.distance.m > MAX_DISTANCE_METERS:
        logger.debug(f"    No stoptime found for {loc} (distance {stoptime.distance.m} m)")
        # TODO: maybe handle departure here?
        return

    # This is a new trip or it's a new instance of this trip (previous instance is too old)
    if not last_stoptime_instance or loc.time - last_stoptime_instance.time_arrival > MAX_STALE_TRIP_INSTANCE:
        trip_instance = TripInstance.objects.create(trip=loc.trip, vehicle=loc.vehicle, created=loc.time)
        logger.debug(f"  Created trip instance {trip_instance}")
        # TODO: end any previous trip instances

    # The last stop time instance is still valid, use its trip instance
    else:
        trip_instance = last_stoptime_instance.trip_instance
        logger.debug(f"  Found existing trip instance {trip_instance}")

    # Check for existing stop time instance
    stoptime_instance = StopTimeInstance.objects.filter(trip_instance=trip_instance, stoptime=stoptime).first()
    if stoptime_instance:
        # TODO: maybe update existing stoptime instance?
        logger.debug(f"    Found existing stop time instance {stoptime_instance}")
    else:
        # Create new stop time instance
        stoptime_instance = StopTimeInstance.objects.create(trip_instance=trip_instance, vehicle_location=loc, stoptime=stoptime, time_arrival=loc.time,)
        LAST_STOPTIME_CACHE[(trip_instance.trip_id, loc.vehicle.id)] = stoptime_instance
        logger.debug(f"    Created stop time instance {stoptime_instance}")

    pass



if __name__ == '__main__':


    # find trip with most locations
    # trips = Trip.objects.annotate(num_locations=Count('vehiclelocation')).order_by('-num_locations')[:10]

    logger.setLevel(logging.DEBUG)

    locs = VehicleLocation.objects.filter(vehicle_id=440).order_by('time')
    logger.debug(f"Processing {len(locs)} locations")

    pass

    for loc in locs:
        logger.debug(f"Processing {loc.id} ({loc.time})")
        process_vehicle_location(loc)
        pass