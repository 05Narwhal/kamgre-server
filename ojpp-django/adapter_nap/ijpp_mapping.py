import uuid

# TODO: convert to ints
ijppId_C = {
    "Prevoznik": b'\x01\x00',
    "Postajalisce": b'\x02\x00',
    "PostajnaTocka": b'\x03\x00',
    "Voznja": b'\x08\x00',
    "VoznjaOpis": b'\x09\x00',
}

IJPP_NETEX_TYPE_MAP = {
    'Prevoznik': 'Operator',
    'Postajalisce': 'StopPlace',
    'PostajnaTocka': 'Quay',
    'Voznja': 'ServiceJourney',
    'VoznjaOpis': 'TimetabledPassingTime',
    'VozniRed': 'Line',
}

NETEX_IJPP_TYPE_MAP = dict((v, k) for k, v in IJPP_NETEX_TYPE_MAP.items())

def make_realis_id(netex_type_name, guid_str, country="SI", region="SI0", external_system_name="IJPP"):
    epip_frame_name = ""  # TODO: what?
    return ":".join((
        country,
        region,
        netex_type_name,
        epip_frame_name + ("" if not epip_frame_name.strip() else "_") + guid_str,
        external_system_name,
    ))

def make_ijpp_guid(ijpp_type, netex_type, id: int, id1=0, id2=0):
    data = bytes()
    data += id2.to_bytes(4, byteorder='big')
    data += b'\x77\x11' # TODO: what is ijppId_B?
    data += ijppId_C[ijpp_type]
    data += id1.to_bytes(4, byteorder='big')
    data += id.to_bytes(4, byteorder='big')

    guid = uuid.UUID(bytes_le=data)

    return guid

def ijpp_to_realis(ijpp_id: int, ijpp_type: str) -> str:
    typ = IJPP_NETEX_TYPE_MAP[ijpp_type]
    guid = make_ijpp_guid(ijpp_type, typ, ijpp_id)
    rid = make_realis_id(typ, str(guid))
    return rid


def parse_ijpp_guid(guid_str: str):
    guid = uuid.UUID(guid_str)
    data = guid.bytes_le
    ijpp_id = int.from_bytes(data[-4:], byteorder="big")
    return ijpp_id


def realis_to_ijpp(realis_id: str) -> (int, str):
    parts = realis_id.split(":")
    if len(parts) != 5:
        raise ValueError("Invalid realis_id: %s" % realis_id)
    # TODO: get type from GUID parsing instead, using ijppId_C
    ijpp_type = NETEX_IJPP_TYPE_MAP.get(parts[2])
    guid = parts[3]
    ijpp_id = parse_ijpp_guid(guid)
    return ijpp_id, ijpp_type


######################
#   TEST FUNCTIONS   #
######################

# TODO: factor this out into tests.py

tests = [
    # Arriva (oJPP Operator)
    ("Prevoznik", 1123, "SI:SI0:Operator:00000000-1177-0001-0000-000000000463:IJPP"),
    # SŽ PP (oJPP Operator)
    ("Prevoznik", 1161, "SI:SI0:Operator:00000000-1177-0001-0000-000000000489:IJPP"),
    # Sp. Hajdina (oJPP StopLocation)
    ("Postajalisce", 140614, "SI:SI0:StopPlace:00000000-1177-0002-0000-000000022546:IJPP"),
    ("PostajnaTocka", 1130359, "SI:SI0:Quay:00000000-1177-0003-0000-000000113f77:IJPP"),
    # Voznja 301953: Notranje Gorice obr. - Preserje/Krimom (oJPP Trip)
    ("Voznja", 301953, "SI:SI0:ServiceJourney:00000000-1177-0008-0000-000000049b81:IJPP"),
    # Voznja 301953 -- VoznjaOpis Sp. Hajdina @ 12:46 (oJPP StopTime)
    ("VoznjaOpis", 7353024, "SI:SI0:TimetabledPassingTime:00000000-1177-0009-0000-0000007032c0:IJPP"),
]


def test_ijpp_to_realis():
    for ijpp_type, ijpp_id, realis_id in tests:
        assert ijpp_to_realis(ijpp_id, ijpp_type) == realis_id


def test_realis_to_ijpp():
    for ijpp_type, ijpp_id, realis_id in tests:
        assert realis_to_ijpp(realis_id) == (ijpp_id, ijpp_type)


if __name__ == '__main__':
    test_ijpp_to_realis()
    test_realis_to_ijpp()
