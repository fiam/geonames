ALTER TABLE geoname ALTER COLUMN gpoint_meters SET NOT NULL;
CREATE INDEX geoname_gpoint_meters ON geoname USING GIST ("gpoint_meters" GIST_GEOMETRY_OPS);
