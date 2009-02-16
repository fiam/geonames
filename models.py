# This file is part of Django-Geonames
# Copyright (c) 2008, Alberto Garcia Hierro
# See LICENSE file for details

from math import sin, cos, acos, radians

from django.core.cache import cache
from django.db import connection
from django.contrib.gis.db import models
from django.utils.translation import ugettext, get_language
from django.conf import settings

from geonames.decorators import stored_property, cache_set

GLOBE_GEONAME_ID = 6295630


def translate_geoname(g, lang):
    cursor = connection.cursor()
    cursor.execute('''SELECT name FROM alternate_name WHERE language='%(lang)s' \
        AND geoname_id = %(id)d AND preferred=TRUE UNION SELECT name \
        FROM alternate_name WHERE language='%(lang)s' AND geoname_id = %(id)d LIMIT 1''' % \
        { 'lang': lang, 'id': g.id })

    try:
        return cursor.fetchone()[0]
    except TypeError:
        return g.name

def get_geo_translate_func():
    try:
        cnf = settings.GEONAMES_TRANSLATION_METHOD
    except AttributeError:
        cnf = 'NOOP'

    if cnf == 'NOOP':
        return (lambda x: x.name)

    if cnf == 'STATIC':
        lang = settings.LANGUAGE_CODE.split('-')[0]
        if lang == 'en':
            return (lambda x: x.name)

        def geo_translate(self):
            key = 'Geoname_%s_i18n_name' % self.id
            return cache.get(key) or cache_set(key, translate_geoname(self, lang))

        return geo_translate

    if cnf == 'DYNAMIC':
        def geo_translate(self):
            lang = get_language()
            key = 'Geoname_%s_%s_i18n_name' % (self.id, lang)
            return cache.get(key) or cache_set(key, translate_geoname(self, lang))

        return geo_translate


    raise ValueError('Unknown value for GEONAMES_TRANSLATION_METHOD: "%s"' % cnf)

geo_translate_func = get_geo_translate_func()

class Geoname(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=200, db_index=True)
    ascii_name = models.CharField(max_length=200)
    latitude = models.DecimalField(max_digits=20, decimal_places=17)
    longitude = models.DecimalField(max_digits=20, decimal_places=17)
    point = models.PointField(null=True, blank=True)
    fclass = models.CharField(max_length=1, db_index=True)
    fcode = models.CharField(max_length=10, db_index=True)
    country = models.ForeignKey('Country', db_index=True, related_name='geoname_set')
    cc2 = models.CharField(max_length=60)
    admin1 = models.ForeignKey('Admin1Code', null=True, related_name='geoname_set', db_index=True)
    admin2 = models.ForeignKey('Admin2Code', null=True, related_name='geoname_set', db_index=True)
    admin3 = models.ForeignKey('Admin3Code', null=True, related_name='geoname_set', db_index=True)
    admin4 = models.ForeignKey('Admin4Code', null=True, related_name='geoname_set', db_index=True)
    population = models.IntegerField()
    elevation = models.IntegerField()
    gtopo30 = models.IntegerField()
    timezone = models.ForeignKey('Timezone', null=True)
    moddate = models.DateField()

    objects = models.GeoManager()

    class Meta:
        db_table = 'geoname'

    def __unicode__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.gpoint = 'POINT(%s %s)' % (self.longitude, self.latitude)
        super(Geoname, self).save(*args, **kwargs)

    @stored_property
    def i18n_name(self):
        return geo_translate_func(self)

    @stored_property
    def admin1_i18n_name(self):
        if self.fcode in ('', 'CONT', 'PCLI'):
            return u''
        try:
            return self.admin1.geoname.i18n_name
        except (Admin1Code.DoesNotExist, Geoname.DoesNotExist):
            return u''

    @stored_property
    def fcode_name(self):
        try:
            return ugettext(FeatureCode.objects.get(pk=self.fcode).name)
        except FeatureCode.DoesNotExist:
            return u''

    @stored_property
    def country_name(self):
        try:
            return self.country.__unicode__()
        except Country.DoesNotExist:
            return u''

    @stored_property
    def country_i18n_name(self):
        try:
            return self.country.geoname.i18n_name
        except models.Model.DoesNotExist:
            return u''

    @stored_property
    def parent(self):
        if self.id == GLOBE_GEONAME_ID:
            return None
        return self.get_parent

    def get_parent(self):

        if self.fcode == 'CONT':
            return Geoname.globe()

        if self.fcode.startswith('PCL'):
            g_list = [self.country.continent]
        elif self.fcode in ('ADM1', 'ADMD'):
            g_list = [self.country, self.country.continent]
        elif self.fcode == 'ADM2':
            g_list = [self.admin1, self.country, self.country.continent]
        elif self.fcode == 'ADM3':
            g_list = [self.admin2, self.admin1, self.country, self.country.continent]
        elif self.fcode == 'ADM4':
            g_list = [self.admin3, self.admin2, self.admin1, self.country, self.country.continent]
        else:
            g_list = [self.admin4, self.admin3, self.admin2, self.admin1, self.country, self.country.continent]

        for g in g_list:
            try:
                if g.geoname_id != self.id:
                    return g.geoname
            except AttributeError:
                pass

        return None

    @stored_property
    def hierarchy(self):
        hier = []
        parent = self.parent
        while parent:
            hier.append(parent)
            parent = parent.parent

        return hier

    def get_children(self):
        if self.id == GLOBE_GEONAME_ID:
            return Geoname.objects.filter(id__in=[x['geoname'] for x in Continent.objects.values('geoname')])

        if self.fcode == 'CONT':
            return Geoname.objects.filter(id__in=[x['geoname'] for x in Continent.objects.get(geoname=self.id).country_set.values('geoname')])

        if self.fclass != 'A':
            return Geoname.objects.none()

        try:
            if self.fcode.startswith('PCL'):
                s_list = [self.country.geoname_set.filter(fcode=code) for code in ('ADM1', 'ADMD', 'ADM2', 'ADM3', 'ADM4')] + [self.country.geoname_set.filter(fclass='P')]
            elif self.fcode == 'ADM1':
                s_list = [self.admin1.geoname_set.filter(fcode=code) for code in ('ADM2', 'ADM3', 'ADM4')] + [self.admin1.geoname_set.filter(fclass='P')]
            elif self.fcode == 'ADM2':
                s_list = [self.admin2.geoname_set.filter(fcode=code) for code in ('ADM3', 'ADM4')] + [self.admin2.geoname_set.filter(fclass='P')]
            elif self.fcode == 'ADM3':
                s_list = [self.admin3.geoname_set.filter(fcode='ADM4'), self.admin3.geoname_set.filter(fclass='P')]
            elif self.fcode == 'ADM4':
                s_list = [self.admin4.geoname_set.filter(fclass='P')]
            else:
                return Geoname.objects.none()

        except AttributeError:
            return Geoname.objects.none()

        for qs in s_list:
            if qs.count():
                return qs

        return Geoname.objects.none()

    @stored_property
    def children(self):
        cset = self.get_children()
        l = list(cset or [])
        l.sort(cmp=lambda x,y: cmp(x.i18n_name, y.i18n_name))
        return l

    @classmethod
    def biggest(cls, lset):
        codes = [ '', 'CONT', 'PCLI', 'ADM1', 'ADM2', 'ADM3', 'ADM4', 'PPL']
        for c in codes:
            for item in lset:
                if item.fcode == c:
                    return item

        try:
            return lset[0]
        except IndexError:
            return None

    @classmethod
    def globe(cls):
        return cls.objects.get(pk=GLOBE_GEONAME_ID)

    def is_globe(self):
        return self.id == GLOBE_GEONAME_ID

    def contains(self, child):
        if self.is_globe():
            return True
        try:
            if self.fcode == 'CONT':
                return child.country.continent.geoname == self
            if self.fcode in ('PCLI', 'PCLD'):
                return child.country_id == self.country_id
            if self.fcode == 'ADM1':
                return self.admin1_id == child.admin1_id
            if self.fcode == 'ADM2':
                return self.admin2_id == child.admin2_id
            if self.fcode == 'ADM3':
                return self.admin3_id == child.admin3_id
            if self.fcode == 'ADM4':
                return self.admin4_id == child.admin4_id
        except Country.DoesNotExist:
            return False

        return False

    def distance(self, other):
        return Geoname.distance_points(self.latitude, self.longitude, other.latitude, other.longitude)

    @classmethod
    def distance_points(cls, lat1, lon1, lat2, lon2, is_rad=False):
        if not is_rad:
            lat1, lon1, lat2, lon2 = map(lambda x: radians(float(x)), (lat1, lon1, lat2, lon2))
        return 6378.7 * acos(sin(lat1) * sin(lat2) + cos(lat1) * cos(lat2) * cos(lon2 - lon1))

class GeonameAlternateName(models.Model):
    id = models.IntegerField(primary_key=True)
    geoname = models.ForeignKey(Geoname, related_name='altnames', db_index=True)
    language = models.CharField(max_length=7)
    name = models.CharField(max_length=200)
    preferred = models.BooleanField()
    short = models.BooleanField()

    class Meta:
        db_table = 'alternate_name'

    def __unicode__(self):
        return self.alternateName

class Continent(models.Model):
    code = models.CharField(max_length=2, primary_key=True)
    name = models.CharField(max_length=20)
    geoname = models.ForeignKey(Geoname, unique=True)

    class Meta:
        db_table = 'continent'

    def __unicode__(self):
        return self.name

class Country(models.Model):
    iso_alpha2 = models.CharField(max_length=2, primary_key=True)
    iso_alpha3 = models.CharField(max_length=3, unique=True)
    iso_numeric = models.IntegerField(unique=True)
    fips_code = models.CharField(max_length=3)
    name = models.CharField(max_length=200)
    capital = models.CharField(max_length=200)
    area = models.FloatField()
    population = models.IntegerField()
    continent = models.ForeignKey(Continent, db_index=True)
    tld = models.CharField(max_length=4, null=True)
    currency_code = models.CharField(max_length=3)
    currency_name = models.CharField(max_length=16, null=True)
    phone_prefix = models.CharField(max_length=16, null=True)
    postal_code_fmt = models.CharField(max_length=64, null=True)
    postal_code_re = models.CharField(max_length=256, null=True)
    languages = models.CharField(max_length=200)
    geoname = models.ForeignKey(Geoname, related_name='this_country')
    neighbours = models.ManyToManyField('self')

    class Meta:
        db_table = 'country'

    def __unicode__(self):
        return self.name

class Language(models.Model):
    iso_639_3 = models.CharField(max_length=4, primary_key=True)
    iso_639_2 = models.CharField(max_length=50)
    iso_639_1 = models.CharField(max_length=50)
    language_name = models.CharField(max_length=200)

    class Meta:
        db_table = 'iso_language'

class Admin1Code(models.Model):
    country = models.ForeignKey(Country, db_index=True)
    geoname = models.ForeignKey(Geoname, db_index=True)
    code = models.CharField(max_length=5)
    name = models.TextField()
    ascii_name = models.TextField()
    geom = models.GeometryField(null=True, blank=True)
    class Meta:
        db_table = 'admin1_code'

class Admin2Code(models.Model):
    country = models.ForeignKey(Country, db_index=True)
    admin1 = models.ForeignKey(Admin1Code, null=True)
    geoname = models.ForeignKey(Geoname, db_index=True)
    code = models.CharField(max_length=30)
    name = models.TextField()
    ascii_name = models.TextField()
    geom = models.GeometryField(null=True, blank=True)
    class Meta:
        db_table = 'admin2_code'

class Admin3Code(models.Model):
    country = models.ForeignKey(Country, db_index=True)
    admin1 = models.ForeignKey(Admin1Code, null=True, db_index=True)
    admin2 = models.ForeignKey(Admin2Code, null=True, db_index=True)
    geoname = models.ForeignKey(Geoname, db_index=True)
    code = models.CharField(max_length=30)
    name = models.TextField()
    ascii_name = models.TextField()
    geom = models.GeometryField(null=True, blank=True)
    class Meta:
        db_table = 'admin3_code'

class Admin4Code(models.Model):
    country = models.ForeignKey(Country)
    admin1 = models.ForeignKey(Admin1Code, null=True, db_index=True)
    admin2 = models.ForeignKey(Admin2Code, null=True, db_index=True)
    admin3 = models.ForeignKey(Admin3Code, null=True, db_index=True)
    geoname = models.ForeignKey(Geoname, db_index=True)
    code = models.CharField(max_length=30)
    name = models.TextField()
    ascii_name = models.TextField()
    geom = models.GeometryField(null=True, blank=True)
    class Meta:
        db_table = 'admin4_code'

class FeatureCode(models.Model):
    code = models.CharField(max_length=7, primary_key=True)
    fclass = models.CharField(max_length=1)
    name = models.CharField(max_length=200)
    description = models.TextField()

    class Meta:
        db_table = 'feature_code'

class Timezone(models.Model):
    name = models.CharField(max_length=200)
    gmt_offset = models.DecimalField(max_digits=4, decimal_places=2)
    dst_offset = models.DecimalField(max_digits=4, decimal_places=2)

    class Meta:
        db_table = 'time_zone'

class GeonamesUpdate(models.Model):
    updated_date = models.DateField()

    class Meta:
        db_table = 'geonames_update'
