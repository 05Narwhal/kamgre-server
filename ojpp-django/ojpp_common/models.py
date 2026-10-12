import logging

from colorfield.fields import ColorField
from computedfields.models import computed, ComputedFieldsModel
from django.contrib.gis.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.urls import reverse
from galleryfield.fields import GalleryField
from psqlextra.models import PostgresModel
from django.contrib.gis.geos import Point, LineString, MultiLineString


class Stop(PostgresModel, ComputedFieldsModel):
    location = models.PointField(null=True)
    marprom_id = models.PositiveIntegerField(unique=True, db_index=True, blank=True, null=True)
    ijpp_id = models.PositiveIntegerField(unique=True, db_index=True, blank=True, null=True)
    lpp_id = models.PositiveIntegerField(unique=True, db_index=True, blank=True, null=True)
    name = models.CharField(max_length=50, null=True)
    is_active = models.BooleanField(default=True)

    @computed(models.PositiveSmallIntegerField(default=0), depends=[('stoplocation_set', ['id'])])
    def location_count(self):
        if self.id is not None:
            return self.stoplocation_set.count()
        return 0

    def get_absolute_url(self):
        return reverse('stop_detail', kwargs=dict(pk=self.id))

    def __str__(self):
        return self.name


class StopLocation(PostgresModel):
    stop = models.ForeignKey(Stop, on_delete=models.CASCADE, null=True)
    marprom_id = models.PositiveIntegerField(unique=True, db_index=True, blank=True, null=True)
    ijpp_id = models.PositiveIntegerField(unique=True, db_index=True, blank=True, null=True)
    lpp_id = models.PositiveIntegerField(unique=True, db_index=True, blank=True, null=True)
    location = models.PointField(null=True)
    name = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    photo = models.ImageField(null=True, blank=True)
    operator_stop_id = models.CharField(max_length=10, null=True, blank=True)

    def details_dict(self):
        return {
            'id': self.id,
            'name': self.name if self.name else self.stop.name,
            'marprom_id': self.marprom_id,
            'ijpp_id': self.ijpp_id,
            'lpp_id': self.lpp_id,
            'location': {
                'lat': self.location.y,
                'lon': self.location.x,
            },
            'stop_group_id': self.stop.id,
        }
    def __str__(self):
        return f'{self.stop.name if self.stop else "??"} - {self.name}'

    def get_absolute_url(self):
        return reverse('stop_location_detail', kwargs=dict(pk=self.id))

    def get_routes(self):
        return Route.objects.filter(trip__stoptime__stop_location=self).distinct()


class Operator(PostgresModel, ComputedFieldsModel):
    name = models.CharField(max_length=100, null=True)
    short_name = models.CharField(max_length=50, null=True, blank=True)
    slug = models.SlugField(max_length=100, unique=True, null=True)
    ijpp_avl_id = models.CharField(max_length=100, db_index=True, verbose_name='IJPP AVL ID', help_text='VehicleRef', unique=True)
    ijpp_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    ijpp_šifra = models.CharField(max_length=4, db_index=True, verbose_name='IJPP šifra', unique=True, blank=True, null=True)
    # nap_id = models.CharField(max_length=57, null=True, blank=True, db_index=True, unique=True)
    logo = models.ImageField(null=True, blank=True)
    logo_square = models.ImageField(null=True, blank=True)
    color = ColorField(default='#444444', null=True, blank=True)
    active = models.BooleanField(default=True)
    website = models.URLField(null=True, blank=True)
    tax_id = models.CharField(max_length=10, null=True, blank=True)

    aliases = models.CharField(max_length=100, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    def get_short_name(self):
        return self.short_name if self.short_name else self.name

    class Meta:
        ordering = ('name',)

    def get_absolute_url(self):
        return reverse('operator_detail', kwargs=dict(pk=self.id))

    def __str__(self):
        return self.name

    def get_logo(self):
        return self.logo.url if self.logo else self.logo_square.url if self.logo_square else None

    def get_short_name(self):
        return self.short_name if self.short_name else self.name.replace('d.o.o.', '').strip(' ,.')


class RouteGroup(PostgresModel):
    number = models.CharField(max_length=5, null=True, blank=True)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, null=True, blank=True)
    color = ColorField(default='#444444')

    marprom_id = models.PositiveIntegerField(unique=True, db_index=True, blank=True, null=True)

    def __str__(self):
        return f'{self.number}: {self.name}'


class Route(ComputedFieldsModel, PostgresModel):
    active = models.BooleanField(default=True)

    name = models.CharField(max_length=250, null=True, blank=True)
    name_via = models.CharField(max_length=250, null=True, blank=True)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='routes')
    route_group = models.ForeignKey(RouteGroup, on_delete=models.CASCADE, null=True, blank=True)

    ijpp_id = models.PositiveIntegerField(unique=True, blank=True, null=True)
    marprom_id = models.CharField(max_length=100, unique=True, db_index=True, blank=True, null=True)
    lpp_id = models.CharField(max_length=36, null=True, blank=True)

    nvr_name = models.CharField(max_length=100, null=True, blank=True)
    nvr_number = models.CharField(max_length=16, null=True, blank=True)
    nvr_version = models.CharField(max_length=8, null=True, blank=True)

    route_type = models.CharField(max_length=50, null=True, blank=True)

    note = models.TextField(null=True, blank=True)

    def get_name(self):
        if self.name:
            return self.name
        try:
            return self.first_stop.name + ' - ' + self.last_stop.name
        except AttributeError:
            return '#%s' % self.id

    def save(
        self,
        force_insert = False,
        force_update = False,
        using = None,
        update_fields = None,
        skip_computedfields = False
    ) -> None:

        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
            skip_computedfields=skip_computedfields or self.id is None
        )

    def __str__(self):
        return f'#{self.id}'

    def get_absolute_url(self):
        return reverse('route_detail', kwargs=dict(pk=self.id))

    @computed(models.ForeignKey(Stop, on_delete=models.SET_NULL, null=True, related_name='_first_stop'), depends=[('trips', ['id'])])
    def first_stop(self):
        try:
            return self.trips.first().stoptimes.order_by('sequence_num').first().stop_location.stop.id
        except AttributeError:
            return None

    @computed(models.ForeignKey(Stop, on_delete=models.SET_NULL, null=True, related_name='_last_stop'), depends=[('trips', ['id'])])
    def last_stop(self):
        try:
            return self.trips.first().stoptimes.order_by('sequence_num').last().stop_location.stop.id
        except AttributeError:
            return None

    def geometry(self):
        try:
            return MultiLineString(LineString([
                st.stop_location.location
                for st in self.trips.first().stoptimes.order_by('sequence_num').prefetch_related('stop_location') if st.stop_location.location
            ]))
        except AttributeError:
            return None


class RouteSegment(PostgresModel):
    active = models.BooleanField(default=True)

    start_stop = models.ForeignKey(StopLocation, on_delete=models.CASCADE, related_name='segments_start')
    end_stop = models.ForeignKey(StopLocation, on_delete=models.CASCADE, related_name='segments_end')
    time = models.DurationField(null=True, blank=True)
    length = models.FloatField(null=True, blank=True)
    ijpp_id = models.PositiveIntegerField(unique=True, blank=True, null=True)
    ijpp_geometry = models.LineStringField(srid=4326, null=True, blank=True)
    osm_geometry = models.LineStringField(srid=4326, null=True, blank=True)

class Trip(ComputedFieldsModel, PostgresModel):
    active = models.BooleanField(default=True)

    ijpp_id = models.PositiveIntegerField(unique=True, blank=True, null=True)
    piran_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    marprom_id = models.PositiveIntegerField(unique=True, db_index=True, blank=True, null=True)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, null=True, blank=True, related_name='trips')
    seq_number = models.PositiveSmallIntegerField(null=True, blank=True)
    geometry = models.LineStringField(srid=4326, null=True, blank=True)
    geometry_is_final = models.BooleanField(default=False)
    schedule = models.ForeignKey('Schedule', on_delete=models.SET_NULL, null=True, blank=True)
    headsign = models.CharField(max_length=256, null=True, blank=True)

    def get_absolute_url(self):
        return reverse('trip_detail', kwargs=dict(pk=self.id))

    @computed(models.CharField(blank=True, null=True, max_length=300), depends=[('route', ['name']), ('stoptimes', ['id'])])
    def name(self):
        try:
            if self.route_id is None:
                return '#' + str(self.id)
            #if self.route.name:
            #    return self.route.name
            else:
                st = self.stoptimes.order_by('sequence_num').select_related('stop_location__stop')
                if self.stoptimes.exists():
                    return f'{st.first().stop_location.stop.name} - {st.last().stop_location.stop.name}'
                else:
                    return '#' + str(self.id)
        except:
            logging.exception('Error calculating trip name')
            return '#' + str(self.id)

    def details_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'route': self.route.id if self.route else None,
            'stop_times': [st.details_dict() for st in self.stoptimes.order_by('sequence_num')]
        }

    def __str__(self):
        return f'#{self.id} {self.name}'

class StopTime(PostgresModel):
    active = models.BooleanField(default=True)

    # route = models.ForeignKey(Route, on_delete=models.CASCADE)
    ijpp_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='stoptimes')
    stop_location = models.ForeignKey(StopLocation, on_delete=models.CASCADE)
    time_arrival = models.TimeField(null=True, blank=True)
    time_departure = models.TimeField(null=True, blank=True)
    sequence_num = models.PositiveSmallIntegerField()

    def __str__(self):
        return f'{self.trip} to {self.stop_location} at {self.time_arrival}'

    def details_dict(self):
        return {
            'id': self.id,
            'stop': self.stop_location.details_dict(),
            'time_arrival': self.time_arrival.strftime('%H:%M') if self.time_arrival else None,
            'time_departure': self.time_departure.strftime('%H:%M') if self.time_departure else None,
            'sequence_num': self.sequence_num
        }

    class Meta:
        unique_together = ('ijpp_id', 'trip', 'stop_location', 'sequence_num')


class VehicleModel(PostgresModel):
    name = models.CharField(max_length=150)
    low_floor = models.BooleanField(default=False)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('vehicle_list') + '?model=' + str(self.id)


class Vehicle(PostgresModel):
    class Type(models.TextChoices):
        BUS = 'BUS', 'Avtobus'
        TRAIN = 'TRN', 'Vlak'

    plate = models.CharField(max_length=10, null=True, blank=True)
    ijpp_id = models.PositiveIntegerField(db_index=True, null=True, blank=True, unique=True)
    lpp_id = models.CharField(max_length=37, null=True, blank=True, db_index=True, unique=True)
    operator_vehicle_id = models.CharField(max_length=10, null=True, blank=True)

    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, null=True, related_name='vehicles')
    model = models.ForeignKey(VehicleModel, on_delete=models.SET_NULL, null=True, blank=True)

    photos = GalleryField(blank=True, null=True, target_model='galleryfield.BuiltInGalleryImage')
    type = models.CharField(max_length=3, choices=Type.choices, default=Type.BUS)
    vin = models.CharField(max_length=17, blank=True, null=True)

    def get_absolute_url(self):
        return reverse('vehicle_detail', kwargs=dict(pk=self.id))

    def details_dict(self):
        # Only used in map sidebar
        return {
            'id': self.id,
            'plate': self.plate,
            'ijpp_id': self.ijpp_id,
            'lpp_id': self.lpp_id,
            'operator_vehicle_id': self.operator_vehicle_id,
            'operator': {
                'id': self.operator.id,
                'name': self.operator.name,
            },
            'model': self.model.name if self.model else None,
            # ternary loop which gets photo.image.url for each photo in self.photos
            'photos': [photo.image.url for photo in self.photos.objects.all()] if self.photos else None,
            'type': self.type,
            'vin': self.vin,
        }

    def __str__(self):
        return f'{self.operator.get_short_name()}: {self.plate}'

    class _base_manager(models.Manager):
        def get_queryset(self):
            return super().get_queryset().select_related('operator',)

    objects = _base_manager()


class VehicleLocation(PostgresModel):
    location = models.PointField(null=True)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, null=True, blank=True)
    bearing = models.PositiveSmallIntegerField(null=True, blank=True)
    time = models.DateTimeField(db_index=True)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, related_name='location_history', db_index=True)

    def __str__(self):
        return f'#{self.id}'

    class Meta:
        unique_together = ('vehicle', 'time', )


class Schedule(PostgresModel):
    ijpp_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    marprom_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    ijpp_tag = models.CharField(max_length=10, null=True, blank=True)

    name = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    default_state = models.BooleanField(default=False)

    def __str__(self):
        return f'#{self.pk} ({self.name or self.ijpp_tag})'

    def get_absolute_url(self):
        return reverse('schedule_detail', kwargs=dict(pk=self.id))


class TimetablePeriod(PostgresModel):
    ijpp_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    marprom_id = models.TextField(unique=True, null=True, blank=True)
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name='periods')
    action = models.BooleanField(choices=[(True, 'SET'), (False, 'UNSET')])

    day_from = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(31)])
    month_from = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)], choices=[(i, str(i)) for i in range(1, 13)])
    year_from = models.PositiveSmallIntegerField(validators=[MinValueValidator(2016), MaxValueValidator(2100)], null=True, blank=True)
    day_to = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(31)])
    month_to = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)], choices=[(i, str(i)) for i in range(1, 13)])
    year_to = models.PositiveSmallIntegerField(validators=[MinValueValidator(2016), MaxValueValidator(2100)], null=True, blank=True)

    monday = models.BooleanField(default=False)
    tuesday = models.BooleanField(default=False)
    wednesday = models.BooleanField(default=False)
    thursday = models.BooleanField(default=False)
    friday = models.BooleanField(default=False)
    saturday = models.BooleanField(default=False)
    sunday = models.BooleanField(default=False)
    holidays = models.BooleanField(default=False)

    def days_of_week(self):
        DAYS_OF_WEEK = (('monday', 0), ('tuesday', 1), ('wednesday', 2), ('thursday', 3), ('friday', 4), ('saturday', 5), ('sunday', 6))
        return [value for day, value in DAYS_OF_WEEK if getattr(self, day)]

    def __str__(self):
        return f'Period #{self.id} - {self.day_from}.{self.month_from}. - {self.day_to}.{self.month_to}.'


class TimetableException(PostgresModel):
    ijpp_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    marprom_id = models.TextField(unique=True, null=True, blank=True)
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name='exceptions')
    action = models.BooleanField(choices=[(True, 'SET'), (False, 'UNSET')])

    date = models.DateField()

    def __str__(self):
        return f'Exception #{self.id} - {self.date}'


class TripInstance(PostgresModel):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='instances')
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='trips')
    created = models.DateTimeField()

    def __str__(self):
        return f'TripInst #{self.id}'

    def get_absolute_url(self):
        return reverse('tripinstance_detail', kwargs={'pk': self.pk})

class StopTimeInstance(PostgresModel):
    trip_instance = models.ForeignKey(TripInstance, on_delete=models.CASCADE, related_name='stoptimes')
    vehicle_location = models.ForeignKey(VehicleLocation, on_delete=models.CASCADE, related_name='stoptimes')
    stoptime = models.ForeignKey(StopTime, on_delete=models.CASCADE, related_name='instances')
    time_arrival = models.DateTimeField(blank=True, null=True)
    time_departure = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f'StopTimeInst #{self.id}'
