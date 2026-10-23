-- The text that follows the trigger in a request reply ("+ <the client's questions>"). It reaches
-- the writer as the operator's additional instructions; NULL for a bare trigger.
ALTER TABLE offers ADD COLUMN request_text text;
