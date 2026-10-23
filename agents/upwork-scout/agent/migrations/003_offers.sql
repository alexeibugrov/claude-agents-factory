-- Offer → reply → proposal flow: every job past the prefilters is posted to the Telegram group
-- as one message (an offer); a reply to it with a trigger word asks the writer for a proposal.
-- New pipeline statuses: offered | requested (then drafting | drafted | delivered as before).

-- One row per posted offer. The message id is what a reply points at.
CREATE TABLE offers (
  job_id             text PRIMARY KEY REFERENCES jobs(job_id),
  chat_id            text NOT NULL,
  message_id         bigint NOT NULL,
  posted_at          timestamptz NOT NULL DEFAULT now(),
  requested_by       bigint,          -- Telegram user id of the latest trigger reply
  request_message_id bigint,          -- that reply; the proposal is sent as a reply to it
  requested_at       timestamptz,
  UNIQUE (chat_id, message_id)
);

-- The last group message the poller has read, per chat. Polling from here misses nothing
-- across a disconnect, restart or deploy.
CREATE TABLE telegram_cursor (
  chat_id         text PRIMARY KEY,
  last_message_id bigint NOT NULL,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Screening is optional now, so a proposal may have no screening behind it.
ALTER TABLE proposals ALTER COLUMN screening_id DROP NOT NULL;
