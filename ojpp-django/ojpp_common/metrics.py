from prometheus_client import Gauge

G_LOCATIONS_TOTAL = Gauge('locations_total', 'Total number of locations')

G_DISCARDED_LOCATIONS = Gauge('discarded_locations', 'Discarded locations', ['reason'])
G_DISCARDED_BY_TIME = G_DISCARDED_LOCATIONS.labels(reason='time')
G_DISCARDED_BY_COORDS = G_DISCARDED_LOCATIONS.labels(reason='coords')

G_LOCATIONS = Gauge('locations', 'Received vehicle locations', ['provider'])
G_LOC_IJPP = G_LOCATIONS.labels(provider='ijpp')
G_LOC_MARPROM = G_LOCATIONS.labels(provider='marprom')
G_LOC_LPP = G_LOCATIONS.labels(provider='lpp')

G_VALIDLOCATIONS = Gauge('valid_locations', 'Received vehicle locations', ['provider'])
G_VALIDLOC_IJPP = G_VALIDLOCATIONS.labels(provider='ijpp')
G_VALIDLOC_MARPROM = G_VALIDLOCATIONS.labels(provider='marprom')
G_VALIDLOC_LPP = G_VALIDLOCATIONS.labels(provider='lpp')
