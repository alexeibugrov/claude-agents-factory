-- Proposal revisions: a reply to a delivered proposal with comments asks the writer to edit it.
-- Every version is its own row, linked by revises_id.
ALTER TABLE proposals DROP CONSTRAINT proposals_job_id_prompt_sha_key;
ALTER TABLE proposals ADD COLUMN revises_id bigint REFERENCES proposals(id);
ALTER TABLE proposals ADD COLUMN request_text text;  -- the operator's suggestions (new draft) or comments (revision)

-- The proposal a pending request revises; NULL when it asks for a new draft.
ALTER TABLE offers ADD COLUMN revise_proposal_id bigint REFERENCES proposals(id);
