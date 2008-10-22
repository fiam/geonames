# This file is part of Django-Geonames
# Copyright (c) 2008, Alberto Garcia Hierro
# See LICENSE file for details

from math import sin, cos, acos, radians

from django.core.cache import cache
#from django.contrib.gis.db import models
from django.db import connection, models
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext, get_language
from django.conf import settings


from decorators import full_cached_property, cached_property, stored_property, cache_set

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

class GeonameGISHelper(object):
    def near_point(self, latitude, longitude, kms, order):
        raise NotImplementedError

    def aprox_tz(self, latitude, longitude):
        cursor = connection.cursor()
        flat = float(latitude)
        flng = float(longitude)
        for diff in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1):
            minlat = flat - diff * 10
            maxlat = flat + diff * 10
            minlng = flng - diff
            maxlng = flng + diff
            tz = self.box_tz(cursor, minlat, maxlat, minlng, maxlng)
            if tz:
                return tz

        return None

    def box_tz(self, cursor, minlat, maxlat, minlng, maxlng):
        raise NotImplementedError

class PgSQLGeonameGISHelper(GeonameGISHelper):
    def box(self, minlat, maxlat, minlng, maxlng):
        return 'SetSRID(MakeBox2D(MakePoint(%s, %s), MakePoint(%s, %s)), 4326)' % \
            (minlng, minlat, maxlng, maxlat)

    def near_point(self, latitude, longitude, kms, order):
        cursor = connection.cursor()
        point = 'Transform(SetSRID(MakePoint(%s, %s), 4326), 32661)' % (longitude, latitude)
        ord = ''
        if order:
            ord = 'ORDER BY distance(%s, gpoint_meters)' % point
        cursor.execute('SELECT %(fields)s, distance(%(point)s, gpoint_meters) ' \
                'FROM geoname WHERE fcode NOT IN (%(excluded)s) AND ' \
                'ST_DWithin(%(point)s, gpoint_meters, %(meters)s)' \
                '%(order)s' %  \
            {   
                'fields': Geoname.select_fields(),
                'point': point,
                'excluded': "'PCLI', 'PCL', 'PCLD', 'CONT'",
                'meters': kms * 1000,
                'order': ord,
            }
        )

        return [(Geoname(*row[:-1]), row[-1]) for row in cursor.fetchall()]

    def box_tz(self, cursor, minlat, maxlat, minlng, maxlng):
        print('SELECT timezone_id FROM geoname WHERE ST_Within(gpoint, %(box)s) ' \
            'AND timezone_id IS NOT NULL LIMIT 1' % \
            {
                'box': self.box(minlat, maxlat, minlng, maxlng),
            }
        )
        cursor.execute('SELECT timezone_id FROM geoname WHERE ST_Within(gpoint, %(box)s) ' \
            'AND timezone_id IS NOT NULL LIMIT 1' % \
            {
                'box': self.box(minlat, maxlat, minlng, maxlng),
            }
        )
        row = cursor.fetchone()
        if row:
            return Timezone.objects.get(pk=row[0])

        return None

GIS_HELPERS = {
    'postgresql_psycopg2': PgSQLGeonameGISHelper,
    'postgresql': PgSQLGeonameGISHelper,
}

try:
    GISHelper = GIS_HELPERS[settings.DATABASE_ENGINE]()
except KeyError:
    print 'Sorry, your database backend is not supported by the Geonames application'

class Geoname(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=200, db_index=True)
    ascii_name = models.CharField(max_length=200)
    latitude = models.DecimalField(max_digits=20, decimal_places=17)
    longitude = models.DecimalField(max_digits=20, decimal_places=17)
    #gpoint = models.PointField()
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

#    objects = models.GeoManager()

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

    @cached_property
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

    @full_cached_property
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

    @full_cached_property
    def children(self):
        cset = self.get_children()
        l = list(cset or [])
        l.sort(cmp=lambda x,y: cmp(x.i18n_name, y.i18n_name))
        return l

    @property
    def reluri(self):
        if not self.is_globe():
            return 'location/%d/' % self.id
        return ''

    @property
    def link(self):
        return mark_safe('<a href="/%s">%s</a>' % (self.reluri, self.i18n_name))

    @staticmethod
    def biggest(lset):
        codes = [ '', 'CONT', 'PCLI', 'ADM1', 'ADM2', 'ADM3', 'ADM4', 'PPL']
        for c in codes:
            for item in lset:
                if item.fcode == c:
                    return item

        try:
            return lset[0]
        except IndexError:
            return None

    @staticmethod
    def globe():
        return Geoname.objects.get(pk=GLOBE_GEONAME_ID)

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

    @staticmethod
    def query(q, index, max_count=10):
        def location_results_order(x, y):
            codes = { '': 0, 'CONT': 1, 'PCLI': 2, 'ADM1': 3, 'ADM2': 4, 'ADM3': 5, 'ADM4': 6, 'PPL': 7 }
            return cmp(codes.get(x.fcode, 20), codes.get(y.fcode, 20)) or cmp(x.population, y.population)

        terms = q.split()
        if len(terms) == 1:
            set = Geoname.name_search.query(q).on_index(index)
            result_set = list(set)
            result_set.sort(cmp=location_results_order)
            return result_set[:max_count]

        result_set = Geoname.name_search.query(q).on_index(index)
        if result_set.count() > 0:
            result_set = list(result_set)
            #result_set.sort(cmp=location_results_order)
            result_set.sort(cmp=lambda x,y: cmp(len(x.name), len(y.name)))
            return result_set[:max_count]

        result_set = list(result_set)
        sets = []
        for term in terms:
            sets.append(Geoname.name_search.query(term).on_index(index)[0:100])

        set = {}
        biggest = [Geoname.biggest(rset) for rset in sets]
        r = range(0, len(terms))
        for i in r:
            for item in sets[i]:
                for j in [j for j in r if j != i]:
                    if biggest[j] and biggest[j].contains(item):
                        set[item.id] = item
        result_set += set.values()
        result_set.sort(cmp=location_results_order)
        return result_set[:max_count]

    def distance(self, other):
        return Geoname.distance_points(self.latitude, self.longitude, other.latitude, other.longitude)

    def near(self, kms=20, order=True):
        try:
            return Geoname.near_point(self.latitude, self.longitude, kms, order)[1:]
        except IndexError:
            return Geoname.objects.none()

    @staticmethod
    def select_fields():
        return 'id, name, ascii_name, latitude, longitude, fclass, fcode,' \
                ' country_id, cc2, admin1_id, admin2_id, admin3_id, ' \
                ' admin4_id, population, elevation, gtopo30, timezone_id, moddate'

    @staticmethod
    def distance_points(lat1, lon1, lat2, lon2, is_rad=False):
        if not is_rad:
            lat1, lon1, lat2, lon2 = map(lambda x: radians(float(x)), (lat1, lon1, lat2, lon2))
        return 6378.7 * acos(sin(lat1) * sin(lat2) + cos(lat1) * cos(lat2) * cos(lon2 - lon1))

    @staticmethod
    def near_point(latitude, longitude, kms=20, order=True):
        return GISHelper.near_point(latitude, longitude, kms, order)

    @staticmethod
    def aprox_tz(latitude, longitude):
        return GISHelper.aprox_tz(latitude, longitude)

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

    class Meta:
        db_table = 'admin1_code'

class Admin2Code(models.Model):
    country = models.ForeignKey(Country, db_index=True)
    admin1 = models.ForeignKey(Admin1Code, null=True)
    geoname = models.ForeignKey(Geoname, db_index=True)
    code = models.CharField(max_length=30)
    name = models.TextField()
    ascii_name = models.TextField()

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
