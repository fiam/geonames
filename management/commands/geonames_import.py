import os
import sys
from optparse import OptionParser
from warnings import filterwarnings
from getpass import getpass
from datetime import date
from django.conf import settings
from django.core.management.base import BaseCommand

FILES = [
    'http://download.geonames.org/export/dump/allCountries.zip',
    'http://download.geonames.org/export/dump/alternateNames.zip',
    'http://download.geonames.org/export/dump/admin1CodesASCII.txt',
    'http://download.geonames.org/export/dump/admin2Codes.txt',
    'http://download.geonames.org/export/dump/featureCodes.txt',
    'http://download.geonames.org/export/dump/timeZones.txt',
    'http://download.geonames.org/export/dump/countryInfo.txt',
]

CONTINENT_CODES = [
    ('AF', 'Africa' , 6255146),
    ('AS', 'Asia', 6255147),
    ('EU', 'Europe', 6255148),
    ('NA', 'North America', 6255149),
    ('OC', 'Oceania', 6255151),
    ('SA', 'South America', 6255150),
    ('AN', 'Antarctica', 6255152),
]

class GeonamesImporter(object):
    def __init__(self, host=None, user=None, password=None, db=None, tmpdir='tmp'):
        self.user = user
        self.password = password
        self.db = db
        self.host = host
        self.conn = None
        self.tmpdir = tmpdir
        self.curdir = os.getcwd()
        self.time_zones = {}
        self.admin1_codes = {}
        self.admin2_codes = {}
        self.admin3_codes = {}
        self.admin4_codes = {}
    
    def pre_import(self):
        pass

    def post_import(self):
        pass

    def begin(self):
        pass

    def commit(self):
        pass

    def last_row_id(self, table=None, pk=None):
        raise NotImplementedError('This is a generic importer, use one of the subclasses')

    def get_db_conn(self):
        raise NotImplementedError('This is a generic importer, use one of the subclasses')

    def set_import_date(self):
        raise NotImplementedError('This is a generic importer, use one of the subclasses')

    def fetch(self):
        try:
            os.mkdir(self.tmpdir)
            os.chdir(self.tmpdir)
        except OSError:
            os.chdir(self.tmpdir)
            print 'Temporary directory exists, using already downloaded data'
            return

        for f in FILES:
            if os.system('wget %s' % f) != 0:
                print 'Error fetching %s' % os.path.basename(f)
                sys.exit(1)

        for f in ('allCountries.zip', 'alternateNames.zip'):
            if os.system('unzip %s' % f) != 0:
                print 'Error unzipping %s' % f
                sys.exit(1)

    def cleanup(self):
        os.chdir(self.curdir)
        for f in os.listdir(self.tmpdir):
            os.unlink('%s/%s' % (self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def handle_exception(self, e, line=None):
        print e
        sys.exit(1)

    def table_count(self, table):
        self.cursor.execute('SELECT COUNT(*) FROM %s' % table)
        return self.cursor.fetchone()[0]

    def import_fcodes(self):
        print 'Importing feature codes'
        fd = open('featureCodes.txt')
        line = fd.readline()[:-1]
        while line:
            codes, name, desc = line.split('\t')
            try:
                fclass, code = codes.split('.')
            except ValueError:
                line = fd.readline()[:-1]
                continue
            try:
                self.cursor.execute('INSERT INTO feature_code (code, fclass, name, description) VALUES (%s, %s, %s, %s)', (code, fclass, name, desc))
            except Exception, e:
                self.handle_exception(e, line)

            line = fd.readline()[:-1]
        fd.close()
        print '%d feature codes imported' % self.table_count('feature_code')

    def import_language_codes(self):
        print 'Importing language codes'
        fd = open('iso-languagecodes.txt')
        fd.readline()
        line = fd.readline()[:-1]
        while line:
            fields = line.split('\t')
            try:
                self.cursor.execute('INSERT INTO iso_language (iso_639_3, iso_639_2, iso_639_1, language_name) VALUES (%s, %s, %s, %s)', fields)
            except Exception, e:
                self.handle_exception(e)

            line = fd.readline()[:-1]
        fd.close()
        print '%d language codes imported' % self.table_count('iso_language')

    def import_alternate_names(self):
        print 'Importing alternate names (this is going to take a while)'
        fd = open('alternateNames.txt')
        line = fd.readline()[:-1]
        while line:
            id, geoname_id, lang, name, preferred, short = line.split('\t')
            if preferred in ('', '0'):
                preferred = 'FALSE'
            else:
                preferred = 'TRUE' 
            if short in ('', '0'):
                short = 'FALSE'
            else:
                short = 'TRUE'
            try:
                self.cursor.execute('INSERT INTO alternate_name (id, geoname_id, language, name, preferred, short) VALUES (%s, %s, %s, %s, %s, %s)', (id, geoname_id, lang, name, preferred, short))
            except Exception, e:
                self.handle_exception(e, line)
            line = fd.readline()[:-1]
        fd.close()
        print '%d alternate names imported' % self.table_count('alternate_name')

    def import_time_zones(self):
        print 'Importing time zones'
        fd = open('timeZones.txt')
        fd.readline()
        line = fd.readline()[:-1]
        while line:
            name, gmt, dst = line.split('\t')
            try:
                self.cursor.execute('INSERT INTO time_zone (name, gmt_offset, dst_offset) VALUES (%s, %s, %s)', (name, gmt, dst))
            except Exception, e:
                self.handle_exception(e, line)

            self.time_zones[name] = self.last_row_id('time_zone', 'id') 
            line = fd.readline()[:-1]
        fd.close()
        print '%d time zones imported' % self.table_count('time_zone')

    def import_continent_codes(self):
        for continent in CONTINENT_CODES:
            try:
                self.cursor.execute('INSERT INTO continent (code, name, geoname_id) VALUES (%s, %s, %s)', continent)
            except Exception, e:
                self.handle_exception(e)
        print '%d continent codes imported' % self.table_count('continent')

    def import_countries(self):
        print 'Importing countries'
        fd = open('countryInfo.txt')
        fd.readline()
        line = fd.readline()[:-1]
        while line:
            if line[0] == '#' or line.startswith('ISO') or line.startswith('CS'):
                line = fd.readline()[:-1]
                continue
            fields = line.split('\t')
            #if len(fields) == 18:
            #    fields.append('')
            fields[6] = fields[6].replace(',', '')
            fields[7] = fields[7].replace(',', '')
            if fields[6] == '':
                fields[6] = 0
            try:
                self.cursor.execute('INSERT INTO country (iso_alpha2, iso_alpha3, iso_numeric, fips_code, name, capital, area, population, continent_id, tld, currency_code, currency_name, phone_prefix, postal_code_fmt, postal_code_re, languages, geoname_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', fields[:17])
            except Exception, e:
                self.handle_exception(e, line)
            line = fd.readline()[:-1]
        fd.close()
        print '%d countries imported' % self.table_count('country')

    def import_first_level_adm(self):
        print 'Importing first level administrative divisions'
        fd = open('admin1CodesASCII.txt')
        line = fd.readline()[:-1]
        while line:
            country_and_code, name, ascii_name, geoname_id = line.split('\t')
            country_id, code = country_and_code.split('.')
            try:
                self.cursor.execute('INSERT INTO admin1_code (country_id, geoname_id, code, name, ascii_name) VALUES (%s, %s, %s, %s, %s)', (country_id, geoname_id, code, name, ascii_name))
            except Exception, e:
                self.handle_exception(e, line)

            self.admin1_codes.setdefault(country_id, {})
            self.admin1_codes[country_id][code] = self.last_row_id('admin1_code', 'id')
            line = fd.readline()[:-1]
        fd.close()
        print '%d first level administrative divisions imported' % self.table_count('admin1_code')

    def import_second_level_adm(self):
        print 'Importing second level administrative divisions'
        fd = open('admin2Codes.txt')
        line = fd.readline()[:-1]
        while line:
            codes, name, ascii_name, geoname_id = line.split('\t')
            country_id, adm1, code = codes.split('.', 2)
            try:
                admin1 = self.admin1_codes[country_id][adm1]
            except KeyError:
                admin1 = None
            try:
                self.cursor.execute('INSERT INTO admin2_code (country_id, admin1_id, geoname_id, code, name, ascii_name) VALUES (%s, %s, %s, %s, %s, %s)', (country_id, admin1, geoname_id, code, name, ascii_name))
            except Exception, e:
                self.handle_exception(e, line)

            self.admin2_codes.setdefault(country_id, {})
            self.admin2_codes[country_id].setdefault(adm1, {})
            self.admin2_codes[country_id][adm1][code] = self.last_row_id('admin2_code', 'id') 
            line = fd.readline()[:-1]
        fd.close()
        print '%d second level administrative divisions imported' % self.table_count('admin2_code')

    def import_third_level_adm(self):
        print 'Importing third level administrative divisions'
        fd = open('allCountries.txt')
        line = fd.readline()[:-1]
        while line:
            fields = line.split('\t')
            fcode = fields[7]
            if fcode != 'ADM3':
                line = fd.readline()[:-1]
                continue
            geoname_id = fields[0]
            name = fields[1]
            ascii_name = fields[2]
            country_id = fields[8]
            admin1 = fields[10]
            admin2 = fields[11]
            admin3 = fields[12]
            admin1_id, admin2_id = [None] * 2
            if admin1:
                try:
                    admin1_id = self.admin1_codes[country_id][admin1]
                except KeyError:
                    pass
                if admin2:
                    try:
                        admin2_id = self.admin2_codes[country_id][admin1][admin2]
                    except KeyError:
                        pass
            try:
                self.cursor.execute('INSERT INTO admin3_code (country_id, admin1_id, admin2_id, geoname_id, code, name, ascii_name) VALUES (%s, %s, %s, %s, %s, %s, %s)', (country_id, admin1_id, admin2_id, geoname_id, admin3, name, ascii_name))
            except Exception, e:
                self.handle_exception(e, line)

            self.admin3_codes.setdefault(country_id, {})
            self.admin3_codes[country_id].setdefault(admin1, {})
            self.admin3_codes[country_id][admin1].setdefault(admin2, {})
            self.admin3_codes[country_id][admin1][admin2][admin3] = self.last_row_id('admin3_code', 'id')

            line = fd.readline()[:-1]

        fd.close()
        print '%d third level administrative divisions imported' % self.table_count('admin3_code')

    def import_fourth_level_adm(self):
        print 'Importing fourth level administrative divisions'
        fd = open('allCountries.txt')
        line = fd.readline()[:-1]
        while line:
            fields = line.split('\t')
            fcode = fields[7]
            if fcode != 'ADM4':
                line = fd.readline()[:-1]
                continue
            geoname_id = fields[0]
            name = fields[1]
            ascii_name = fields[2]
            country_id = fields[8]
            admin1 = fields[10]
            admin2 = fields[11]
            admin3 = fields[12]
            admin4 = fields[13]
            admin1_id, admin2_id, admin3_id = [None] * 3
            if admin1:
                try:
                    admin1_id = self.admin1_codes[country_id][admin1]
                except KeyError:
                    pass
                if admin2:
                    try:
                        admin2_id = self.admin2_codes[country_id][admin1][admin2]
                    except KeyError:
                        pass
                    if admin3:
                        try:
                            admin3_id = self.admin3_codes[country_id][admin1][admin2][admin3]
                        except KeyError:
                            pass
            try:
                self.cursor.execute('INSERT INTO admin4_code (country_id, admin1_id, admin2_id, admin3_id, geoname_id, code, name, ascii_name) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (country_id, admin1_id, admin2_id, admin3_id, geoname_id, admin4, name, ascii_name))
            except Exception, e:
                self.handle_exception(e, line)

            self.admin4_codes.setdefault(country_id, {})
            self.admin4_codes[country_id].setdefault(admin1, {})
            self.admin4_codes[country_id][admin1].setdefault(admin2, {})
            self.admin4_codes[country_id][admin1][admin2].setdefault(admin3, {})
            self.admin4_codes[country_id][admin1][admin2][admin3][admin4] = self.last_row_id('admin4_code', 'id')

            line = fd.readline()[:-1]

        fd.close()
        print '%d fourth level administrative divisions imported' % self.table_count('admin4_code')


    def import_geonames(self):
        print 'Importing geonames (this is going to take a while)'
        fd = open('allCountries.txt')
        line = fd.readline()[:-1]
        while line:
            fields = line.split('\t')
            id, name, ascii_name = fields[:3]
            latitude, longitude, fclass, fcode, country_id, cc2 = fields[4:10]
            population, elevation, gtopo30 = fields[14:17]
            moddate = fields[18]
            if elevation == '':
                elevation = 0
            try:
                timezone_id = self.time_zones[fields[17]]
            except KeyError:
                timezone_id = None
            #XXX
            admin1 = fields[10]
            admin2 = fields[11]
            admin3 = fields[12]
            admin4 = fields[13]
            admin1_id, admin2_id, admin3_id, admin4_id = [None] * 4

            if admin1:
                try:
                    admin1_id = self.admin1_codes[country_id][admin1]
                except KeyError:
                    pass

            if admin2:
                try:
                    admin2_id = self.admin2_codes[country_id][admin1][admin2]
                except KeyError:
                    pass

            if admin3:
                try:
                    admin3_id = self.admin3_codes[country_id][admin1][admin2][admin3]
                except KeyError:
                    pass

            if admin4:
                try:
                    admin4_id = self.admin4_codes[country_id][admin1][admin2][admin3][admin4]
                except KeyError:
                    pass
            try:
                self.cursor.execute('INSERT INTO geoname (id, name, ascii_name, latitude, longitude, fclass, fcode, country_id, cc2, admin1_id, admin2_id, admin3_id, admin4_id, population, elevation, gtopo30, timezone_id, moddate) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', (id, name, ascii_name, latitude, longitude, fclass, fcode, country_id, cc2, admin1_id, admin2_id, admin3_id, admin4_id, population, elevation, gtopo30, timezone_id, moddate))
            except Exception, e:
                self.handle_exception(e, line)

            line = fd.readline()[:-1]
        fd.close()

        print '%d geonames imported' % self.table_count('geoname')

    def import_all(self):
        self.pre_import()
        self.begin()
        self.import_fcodes()
        self.commit()
        self.begin()
        self.import_language_codes()
        self.commit()
        self.begin()
        self.import_alternate_names()
        self.commit()
        self.begin()
        self.import_time_zones()
        self.commit()
        self.begin()
        self.import_continent_codes()
        self.commit()
        self.begin()
        self.import_countries()
        self.commit()
        self.begin()
        self.import_first_level_adm()
        self.commit()
        self.begin()
        self.import_second_level_adm()
        self.commit()
        self.begin()
        self.import_third_level_adm()
        self.commit()
        self.begin()
        self.import_fourth_level_adm()
        self.commit()
        self.begin()
        self.import_geonames()
        self.commit()
        self.post_import()

class PsycoPg2Importer(GeonamesImporter):
    def table_count(self, table):
        return 0

    def pre_import(self):
        self.end_stmts = []
        import re
        from django.core.management.color import no_style
        from django.core.management.sql import sql_all
        from django.db import models
        sys.path.append('../')
        sys.path.append('../../')

        alter_re = re.compile('^ALTER TABLE "(\w+)" ADD CONSTRAINT (\w+).*', re.I)
        alter_action = 'ALTER TABLE "\g<1>" DROP CONSTRAINT "\g<2>"'
        index_re = re.compile('^CREATE INDEX "(\w+)".*', re.I)
        index_action = 'DROP INDEX "\g<1>"'
        table_re = re.compile('^CREATE TABLE "(\w+)".*', re.I)
        references_re = re.compile('"(\w+)".*?REFERENCES "(\w+)" \("(\w+)"\) DEFERRABLE INITIALLY DEFERRED')
        references_action = 'ALTER TABLE "%(table)s" DROP CONSTRAINT "%(table)s_%(field)s_fkey"'
        references_stmt = 'ALTER TABLE "%(table)s" ADD CONSTRAINT "%(table)s_%(field)s_fkey" FOREIGN KEY ("%(field)s") ' \
                'REFERENCES "%(reftable)s" ("%(reffield)s") DEFERRABLE INITIALLY DEFERRED'
        sql = sql_all(models.get_app('geonames'), no_style())
        for stmt in sql:
            if alter_re.search(stmt):
                self.cursor.execute(alter_re.sub(alter_action, stmt))
                self.end_stmts.append(stmt)
            elif index_re.search(stmt):
                self.cursor.execute(index_re.sub(index_action, stmt))
                self.end_stmts.append(stmt)
            elif table_re.search(stmt): 
                table = table_re.search(stmt).group(1)
                for m in  references_re.findall(stmt):
                    self.cursor.execute(references_action % \
                        { 
                            'table': table,
                            'field': m[0],
                            'reftable': m[1],
                            'reffield': m[2],
                        })
                    self.end_stmts.append(references_stmt % \
                        {
                            'table': table,
                            'field': m[0],
                            'reftable': m[1],
                            'reffield': m[2],
                        })
                        
        self.cursor.execute('COMMIT')

    def post_import(self):
        print 'Enabling constraings and generating indexes (be patient, this is the last step)'
        self.insert_dummy_records()
        for stmt in self.end_stmts:
            self.cursor.execute(stmt)
            self.commit()

    def insert_dummy_records(self):
        self.cursor.execute("UPDATE geoname SET country_id='' WHERE country_id IN (' ', '  ')")
        self.cursor.execute("INSERT INTO country VALUES ('', '', -1, '', 'No country', 'No capital', 0, 0, '', '', '', '', '', '', '', '', 6295630)")
        self.cursor.execute("INSERT INTO continent VALUES('', 'No continent', 6295630)")

    def begin(self):
        self.cursor.execute('BEGIN')

    def commit(self):
        self.cursor.execute('COMMIT')

    def get_db_conn(self):
        import psycopg2
        conn_params = 'dbname=%s ' % self.db
        if self.host:
            conn_params += 'host=%s ' % self.host
        if self.user:
            conn_params += 'user=%s ' % self.user
        if self.password:
            conn_params += 'password=%s' % self.password

        self.conn = psycopg2.connect(conn_params)
        self.cursor = self.conn.cursor()
    
    def last_row_id(self, table=None, pk=None):
        self.cursor.execute("SELECT CURRVAL('\"%s_%s_seq\"')" % (table, pk))
        return self.cursor.fetchone()[0]
    
    def set_import_date(self):
        self.cursor.execute('INSERT INTO geonames_update (updated_date) VALUES ( CURRENT_DATE AT TIME ZONE \'UTC\')')

IMPORTERS = {
    'postgresql_psycopg2': PsycoPg2Importer,
}

def main(options):
    options = {'tmpdir':'geonames_temp'} #TODO: Make this a proper option
    try:
        importer = IMPORTERS[settings.DATABASE_ENGINE]
    except KeyError:
        print 'Sorry, database engine "%s" is not supported' % \
                settings.DATABASE_ENGINE
        sys.exit(1)

    imp = importer(host=settings.DATABASE_HOST,
        user=settings.DATABASE_USER,
        password=settings.DATABASE_PASSWORD,
        db=settings.DATABASE_NAME,
        tmpdir=options['tmpdir'])

    imp.fetch()
    imp.get_db_conn()
    imp.import_all()
    imp.set_import_date()
    imp.cleanup()

class Command(BaseCommand):
    help = "Geonames import command."

    def handle(self, *args, **options):
        main(options)
