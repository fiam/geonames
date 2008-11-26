/* this column is added for better performance in proximity searches */
SELECT AddGeometryColumn('geoname', 'gpoint', 4326, 'POINT', 2);
SELECT AddGeometryColumn('geoname', 'gpoint_meters', 32661, 'POINT', 2);
CREATE FUNCTION geoname_points () RETURNS trigger AS $geoname_points$
    BEGIN
        NEW.gpoint = SetSRID(MakePoint(NEW.longitude, NEW.latitude), 4326);
        NEW.gpoint_meters = Transform(NEW.gpoint, 32661);
        RETURN NEW;
    END
$geoname_points$ LANGUAGE plpgsql;

CREATE TRIGGER geoname_points BEFORE INSERT OR UPDATE ON geoname
    FOR EACH ROW EXECUTE PROCEDURE geoname_points();
