-- Upwork's own job count for the search, parsed from the actor's run log. NULL or 0 on a
-- succeeded run means the query matched nothing (alerted in agent/scrape.py).
ALTER TABLE scrape_runs ADD COLUMN upwork_total int;
