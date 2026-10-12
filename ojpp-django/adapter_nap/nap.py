from collections import defaultdict
from io import BytesIO
from typing import List, Dict, Any
from zipfile import ZipFile

from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser


import requests

from adapter_nap.ijpp_mapping import realis_to_ijpp
from generated.uk.org.netex.netex.alternative_texts_rel_structure import DayType
from generated.uk.org.netex.netex.line import Line
from generated.uk.org.netex.netex.passenger_stop_assignment import PassengerStopAssignment
from generated.uk.org.netex.netex.publication_delivery import PublicationDelivery
from generated.uk.org.netex.netex.operator import Operator
from generated.uk.org.netex.netex.route import Route
from generated.uk.org.netex.netex.service_journey import ServiceJourney
from generated.uk.org.netex.netex.service_journey_pattern import ServiceJourneyPattern


class NAP_DATASETS:
    _BASE_URL = 'https://b2b.nap.si/data/'
    STOPS = _BASE_URL + 'b2b.netex.stopplaces'
    LINES = _BASE_URL + 'b2b.netex.lines'
    FARES = _BASE_URL + 'b2b.netex.fares'
    OPERATORS = _BASE_URL + 'b2b.netex.operators'


def _get_creds():
    # TODO: get creds from env
    return ()

def nap_request(method: str, url: str, **kwargs):
    """Make a request to NAP"""
    # TODO: proper OAuth
    resp = requests.request(method, url, **kwargs, auth=_get_creds())
    resp.raise_for_status()
    return resp


def get_operators() -> List[Operator]:
    """Get operators from NAP"""
    resp = nap_request("GET", NAP_DATASETS.OPERATORS)
    data = resp.content

    parser = XmlParser(context=XmlContext())

    with ZipFile(BytesIO(data)) as zip_file:
        # TODO: handle multiple files? probably not needed
        fn = zip_file.filelist[0].filename

        with zip_file.open(fn) as xml_file:
            root = parser.parse(xml_file, PublicationDelivery)

    resource_frame = root.data_objects.composite_frame[0].frames.resource_frame[0]

    return resource_frame.organisations.operator


def get_nap_netex() -> PublicationDelivery:
    with open('/home/franga2000/Downloads/NETEX_PI_01_SI_NAP_NETWORK_20231031.XML', 'rb') as xml_file:
        parser = XmlParser(context=XmlContext())
        root = parser.parse(xml_file, PublicationDelivery)
    return root


if __name__ == '__main__':
    #root = get_nap_netex()

    import pickle
    #with open('nap_netex.pickle', 'wb') as f:
    #    pickle.dump(root, f)
    with open('nap_netex.pickle', 'rb') as f:
        root: PublicationDelivery = pickle.load(f)

    print("init")

    frames = root.data_objects.composite_frame[0].frames
    del root

    stop_places = frames.site_frame[0].stop_places

    # Stop and quay map for easy lookup
    stop_place_map = {}
    quay_map = {}
    for sp in stop_places.stop_place:
        stop_place_map[sp.id] = sp
        for quay in sp.quays.quay:
            quay_map[quay.id] = quay

    #operators = frames.resource_frame[0].organisations.operator

    timetable_frame = frames.timetable_frame[0]
    service_frame = frames.service_frame[0]
    service_calendar_frame = frames.service_calendar_frame[0]
    del frames

    day_type_map: Dict[str, DayType] = {dt.id: dt for dt in service_calendar_frame.day_types.day_type}

    service_link_map = {}
    for service_link in service_frame.service_links.service_link:
        key = service_link.from_point_ref.ref + "_" + service_link.to_point_ref.ref
        service_link_map[key] = service_link

    routes = service_frame.routes.route
    lines = service_frame.lines.line

    routes_on_lines: defaultdict[str, List[Route]] = defaultdict(list)
    for route in routes:
        routes_on_lines[route.line_ref.ref].append(route)

    pattern_by_ijpp_id: Dict[str, ServiceJourneyPattern] = {}
    for pattern in service_frame.journey_patterns.service_journey_pattern:
        ijpp_id, _ = realis_to_ijpp(pattern.id)
        pattern_by_ijpp_id[ijpp_id] = pattern

    service_journey_by_ijpp_id: Dict[str, ServiceJourney] = {}
    for service_journey in timetable_frame.vehicle_journeys.service_journey:
        ijpp_id, _ = realis_to_ijpp(service_journey.id)
        service_journey_by_ijpp_id[ijpp_id] = service_journey

    stop_assignment_by_sheduled_stop_point: Dict[str, PassengerStopAssignment] = {}
    for stop_assignment in service_frame.stop_assignments.passenger_stop_assignment:
        stop_assignment_by_sheduled_stop_point[stop_assignment.scheduled_stop_point_ref.ref] = stop_assignment


    #############
    #   LINES   #
    #############

    for line in lines:
        line_ijpp_id, _ = realis_to_ijpp(line.id)
        print(line_ijpp_id, line.transport_mode.name, line.name.value)
        routes = routes_on_lines[line.id]

        ##############
        #   ROUTES   #
        ##############

        for route in routes:
            route_ijpp_id, _  = realis_to_ijpp(route.id)
            pattern = pattern_by_ijpp_id[route_ijpp_id]
            service_journey = service_journey_by_ijpp_id[route_ijpp_id]

            day_type = service_journey.day_types.day_type_ref[0].ref
            schedule_ijpp_id, _ = realis_to_ijpp(day_type)

            print("\t", "Schedule:", schedule_ijpp_id, day_type_map[day_type].name.value)

            # Extract the passing times
            passing_time_by_ijpp_id = {}
            for passing_time in service_journey.passing_times.timetabled_passing_time:
                ijpp_id, _ = realis_to_ijpp(passing_time.id)
                passing_time_by_ijpp_id[ijpp_id] = passing_time


            print("\t", route_ijpp_id, route.name.value)

            if line.transport_mode.name == 'RAIL':
                print("\t\t", "SŽ ID:", route.name.value.rsplit(" ", 1)[-1])


            print("\t\t", len(pattern.points_in_sequence.stop_point_in_journey_pattern), "Stops:")

            last_scheduled_stop_point_ref = None

            ###################
            #   STOP POINTS   #
            ###################

            for point in pattern.points_in_sequence.stop_point_in_journey_pattern:
                stop_point_ijpp_id, _ = realis_to_ijpp(point.id)
                passing_time = passing_time_by_ijpp_id[stop_point_ijpp_id]

                stop_assignment = stop_assignment_by_sheduled_stop_point[point.scheduled_stop_point_ref.ref]

                stop_place = stop_place_map[stop_assignment.stop_place_ref.ref]
                quay = quay_map[stop_assignment.quay_ref.ref]

                # Get service link
                service_link = None
                if last_scheduled_stop_point_ref is not None:
                    key = last_scheduled_stop_point_ref + "_" + point.scheduled_stop_point_ref.ref
                    service_link = service_link_map.get(key)
                last_scheduled_stop_point_ref = point.scheduled_stop_point_ref.ref

                if service_link is not None and service_link.line_string is not None:
                    pts = service_link.line_string.pos
                    print("\t\t\t", "      ", int(service_link.distance), "m", len(pts), "pts")


                # Printing stuff

                num = str(point.order).rjust(2, ' ') + "."
                at = str(passing_time.arrival_time or "").ljust(8, ' ')
                dt = str(passing_time.departure_time or "").ljust(8, ' ')

                tags = ""
                if point.for_alighting == False:
                    tags += "[NA]"
                if point.for_boarding == False:
                    tags += "[NB]"

                name = stop_place.name.value

                print("\t\t\t", num, at[:-3], dt[:-3], name, tags)








    pass

