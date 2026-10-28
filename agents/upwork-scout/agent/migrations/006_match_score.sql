-- The screener rates every job 0-5 for the offer message instead of deciding suitable or not.
ALTER TABLE screenings ALTER COLUMN suitable DROP NOT NULL;
