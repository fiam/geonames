ALTER TABLE geoname ALTER COLUMN gpoint SET NOT NULL;
ALTER TABLE geoname ALTER COLUMN gpoint_meters SET NOT NULL;
CREATE INDEX geoname_gpoint ON geoname USING GIST ("gpoint" GIST_GEOMETRY_OPS);
CREATE INDEX geoname_gpoint_meters ON geoname USING GIST ("gpoint_meters" GIST_GEOMETRY_OPS);
