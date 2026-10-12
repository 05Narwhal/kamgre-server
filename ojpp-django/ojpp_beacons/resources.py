from import_export import resources
from import_export import fields
from import_export import widgets

from .models import *

class VehicleBeaconResource(resources.ModelResource):
    vehicle__lpp_id = fields.Field(
        column_name='vehicle__lpp_id',
        attribute='vehicle',
        widget=widgets.ForeignKeyWidget(
            Vehicle,
            field='lpp_id'
        )
    )
    
    class Meta:
        model = VehicleBeacon