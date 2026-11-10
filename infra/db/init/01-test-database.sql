-- Runs once on first start of an empty data volume.
-- Creates the isolated test database (tests refuse any database not named test_*).
CREATE DATABASE test_familybridge OWNER familybridge;
