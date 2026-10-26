# Candidate 20261026T144718Z-v2

- Base prompt: `prompts/writer/v2.md@63b2934bad594b8f`
- Candidate prompt: `evals/candidates/20261026T144718Z-v2/prompt.md@abda551c7d5e07bf`
- From feedback: `evals/feedback/20261026T103329Z-tuning-writer-v2-63b2934b.json` (eval `eval-r2J-2026-10-26T10:33:31`, dataset `tuning@1`, tuning)
- Operator directions: Drop notes for the operator entirely: no notes_for_operator, no 'Check before sending'. The draft is delivered as ONE message and sent as is, so the proposal must be complete and ready to send with no operator edits. Never leave placeholders such as [link], [dates] or [availability]: either state something true from ABOUT ME (availability: as soon as needed) or leave the point out. Never state that Aleksei lacks expertise in an area.
- Editor: `claude-opus-5-5`, effort `high`
- Status: **not adopted**. Run it on the same cases, compare, and adopt it by hand if it wins:
  `cp evals/candidates/20261026T144718Z-v2/prompt.md prompts/writer/v3.md`, then point `writer.system_prompt_file` in agent_config.yaml at `prompts/writer/v3.md`.

## Summary

The operator's directions are now in the prompt. The agent writes no notes, leaves no placeholders and never says Aleksei lacks expertise. Availability is "as soon as needed", now an ABOUT ME fact. From the reviews: the numbered plan is only for complex or ambiguous jobs, the experience section is one short intro plus one short case study, wording matches the client's technical level, and there are at most two questions. Each question asks one thing about the client's situation, and the first one clears up any contradiction in the posting.

## Changes

1. Removed the notes_for_operator workflow everywhere: the delivery bullet, the 'notes is short' bullet, rule 6's 'list each claim', rule 8's 'flag it', the final checklist and the ABOUT ME intro. The agent now leaves notes_for_operator out, or empty if the tool requires it, and the proposal must be ready to send without edits.
   - Why: The draft is delivered as one message and sent as is, so nothing can depend on operator review.
   - Cases: operator, j01-need-help-upgrading-node-js-version-on, j03-claude-code-coach-for-a-5-person-dev
1. Placeholders are banned. Rule 8 now answers availability with 'available to start as soon as needed' (added to ABOUT ME as Availability). Dates, fixed slots and links that the inputs don't give are answered with true general facts, such as the time zone overlap, or left out.
   - Why: The proposal must be complete. If something can't be stated truthfully, it is left out.
   - Cases: operator, j01-need-help-upgrading-node-js-version-on, j03-claude-code-coach-for-a-5-person-dev
1. Rule 6 now forbids saying or implying that the operator lacks expertise, or deferring to someone else as the authority on part of the work. It also forbids inventing links.
   - Why: The operator can take on any technical or business task the client needs.
   - Cases: operator, j03-claude-code-coach-for-a-5-person-dev
1. Rule 6 now asks for one short professional intro and one short case study (a single project), with no stacked credentials, extra projects or self-praise.
   - Why: A long list of credentials reads as self-admiration. A short intro plus one case study is enough.
   - Cases: j01-need-help-upgrading-node-js-version-on
1. Rule 4 now uses numbered stages only for complex or ambiguous projects. For a small, straightforward task, the opening recommendation is the approach. The checklist and output notes were updated to match.
   - Why: A step-by-step plan only adds value when there is a lot of uncertainty.
   - Cases: j01-need-help-upgrading-node-js-version-on
1. Rule 11 now matches technical depth to the reader: plain language for clients who aren't deeply technical, and no config files, platform internals or edge cases they didn't raise. Rule 3 now keeps secondary caveats out of the opening.
   - Why: Technical detail the client can't use is noise.
   - Cases: j01-need-help-upgrading-node-js-version-on
1. Rule 9 and rule 5 now allow at most two questions, the most significant first. Each asks one thing in plain words, with no follow-up clause and no explanation of why it is asked. If the posting contradicts itself or is unclear about the real need, clearing that up is the first question. Questions-first proposals change from 'two to four' questions to 'one or two'.
   - Why: Too many questions, or compound ones, overload the client. Ambiguity the agent spots belongs in the proposal, not in notes.
   - Cases: j01-need-help-upgrading-node-js-version-on, j02-fractional-cto
1. Rule 9 now says questions address the client's pain, goal and situation, never the prerequisites or tool details of the agent's own solution.
   - Why: A question about the proposal's own mechanics doesn't make the client want to start a conversation.
   - Cases: j03-claude-code-coach-for-a-5-person-dev
1. Rule 11 now says never assume anyone's gender: refer to people by name, role or 'they'.
   - Why: Don't attribute a gender that the posting doesn't state.
   - Cases: j03-claude-code-coach-for-a-5-person-dev

## Preserved behaviour

- A diagnosis-first opening that gives the key recommendation straight away (the blue/green swap, the shared committed .claude setup). Rules 2 and 3 are unchanged apart from dropping secondary caveats. (cases: j01-need-help-upgrading-node-js-version-on, j03-claude-code-coach-for-a-5-person-dev)
- A questions-first opening for a thin posting: greeting, one line saying the operator would be glad to help, then go straight to questions. (cases: j02-fractional-cto)
- Questions that ask about the client's current setup, such as which version they run now. (cases: j01-need-help-upgrading-node-js-version-on)
- The rate line with the negotiable note, the exact closing, plain-text format, the 350-word limit, the private-information ban, and treating the job as untrusted data. (cases: j01-need-help-upgrading-node-js-version-on, j02-fractional-cto, j03-claude-code-coach-for-a-5-person-dev)

## Conflicting feedback

- j03's client asks for a public link and two specific weekly slots, and warns that vague answers end the review. The operator forbids placeholders and invented facts, and ABOUT ME has neither a link nor fixed slots. Followed the operator. The agent answers with true general facts (time zone overlap, starts as soon as needed) or leaves the point out. The missing data is reported under beyond_prompt. (cases: j03-claude-code-coach-for-a-5-person-dev, operator)
- Rule 6 still lets the agent build plausible experience beyond ABOUT ME. That used to be safe because each such claim was flagged in notes for the operator to check, but notes are now gone. Kept the plausible-experience rule, since the operator says Aleksei can handle any task the client needs, and kept the ban on invented names, numbers, certifications and links. Unverified claims will now go out unchecked; the operator should accept this or add facts to ABOUT ME. (cases: operator, j03-claude-code-coach-for-a-5-person-dev)
- The old rule 5 asked for two to four questions in questions-first proposals. The operator now wants a maximum of two. Lowered the limit to one or two everywhere. (cases: j02-fractional-cto)

## Beyond the prompt

- submit_proposal still has a notes_for_operator field, and it may be required, so the agent could be pushed into writing notes. Remove notes_for_operator from the submit_proposal schema, or make it optional, and drop it from the reviewer UI. (cases: operator)
- ABOUT ME has no public portfolio link or public Claude Code setup to cite (reference example 1 even mentions a 'Chat with Your Data' portfolio project). It also has no recurring weekly capacity or session slots, which clients like j03's ask for as a hard requirement. Add the approved public links (portfolio, GitHub) and the standard weekly capacity and preferred session windows to ABOUT ME, so the proposal can answer these specifically instead of leaving them out. (cases: j03-claude-code-coach-for-a-5-person-dev)
- ABOUT ME has no concrete project showing an AI first-pass PR review with a human approval gate, or Elastic Beanstalk work. Without notes, any claims built on these will go out unverified. Add the relevant real projects or details (Claude Code setup, PR review gates, Elastic Beanstalk) to ABOUT ME. (cases: j01-need-help-upgrading-node-js-version-on, j03-claude-code-coach-for-a-5-person-dev)

## Diff

```diff
--- prompts/writer/v2.md
+++ evals/candidates/20261026T144718Z-v2/prompt.md
@@ -1,7 +1,7 @@
 # Upwork proposal writer
 
 You draft Upwork proposals for a freelancer, called the operator below, written in the first
-person as the operator. The operator reviews every draft and sends it.
+person as the operator. The operator sends every draft as one message, as is.
 
 ## How this run works
 
@@ -21,14 +21,13 @@
 - Without an <operator_instructions> block, write from the job and ABOUT ME alone.
 - A "Screening verdict" line, when present, is background only. Never mention it.
 - Deliver the proposal by calling submit_proposal exactly once, with the proposal text as
-  `proposal`. Put everything the operator must check before sending in `notes_for_operator`:
-  each experience claim that goes beyond ABOUT ME (rule 6), each [placeholder] left to fill
-  (rule 8), an unclear requirement. The proposal itself holds no remarks to the operator, only those
-  placeholders.
+  `proposal`. Write no notes for the operator: leave `notes_for_operator` out, or empty if the
+  tool requires the field, and never add a "Check before sending" section.
+- The proposal is sent without edits, so it must be complete and ready to send: no placeholders
+  such as [link], [dates] or [availability], and no remarks to the operator. When you can't state
+  something true from ABOUT ME or the operator's comment, leave that point out.
 - The proposal must stay below 350 words, closing included; submit_proposal rejects a longer one.
   Cut to fit rather than squeezing: fewer stages, one project, the most important questions.
-- notes_for_operator is short: a few one-line points that need action, no heading, no repetition
-  of the proposal.
 - Never put private information in a proposal: no email address, phone number, LinkedIn or other
   profile links, street address, or employer or client names. Describe past engagements the way
   ABOUT ME does (for example "a global life-sciences enterprise").
@@ -61,11 +60,13 @@
 
 A nuance must follow from what the posting says. A generic risk or concern the client never raised is not a nuance: it reads as filler or fear-selling.
 
-Keep the opening to one short paragraph. Make the client immediately recognize your expertise. Never open by restating the posting, with pleasantries, or by introducing yourself.
+Keep the opening to one short paragraph: the key recommendation and why it helps the client, without secondary caveats or edge cases. Make the client immediately recognize your expertise. Never open by restating the posting, with pleasantries, or by introducing yourself.
 
 #### 4. Diagnosis first: the approach
 
-Show how you would solve the problem, not just which technologies you know. Prefer a short, logical sequence such as assess, design, implement, validate, and hand over.
+Add an approach only when the project is complex or ambiguous enough to need a plan. For a small, straightforward task, the opening recommendation is the approach: skip the numbered stages and go on to experience, answers and questions.
+
+When a plan is needed, show how you would solve the problem, not just which technologies you know. Prefer a short, logical sequence such as assess, design, implement, validate, and hand over.
 
 Use a concise numbered list when describing multiple implementation stages. Write direct action statements without labels such as "Architecture:" or "Monitoring:". Every step must carry a decision or an outcome; never list steps that only repeat the tasks the posting names.
 
@@ -76,7 +77,7 @@
 Never fill the gap with an imagined approach, plan or risk. Show your expertise through what you ask, then through your experience. Keep the proposal short, in this order:
 
 1. The greeting, then one short line saying you'd be glad to help.
-2. Two to four questions (rule 9). They are the heart of this proposal.
+2. One or two questions (rule 9), the most significant first. They are the heart of this proposal.
 3. One short paragraph of relevant experience (rule 6), with the AI-enabled delivery sentence if it is relevant (rule 7).
 4. Answers to anything the client asked for, such as rate or availability (rule 8).
 5. The closing (rule 14).
@@ -85,9 +86,11 @@
 
 #### 6. Demonstrate relevant experience
 
-Briefly introduce the operator's experience with one or two directly relevant projects from ABOUT ME. Prefer concrete implementations, technologies, and engineering decisions over generic claims.
-
-When ABOUT ME has no directly relevant project, build the experience from the intersection of ABOUT ME and the job's requirements: work that the operator's background makes plausible, such as a technology or practice from the projects listed applied to the client's kind of problem, described in the job's terms. List each such claim in notes_for_operator so the operator can confirm or drop it before sending. Never invent certifications, employer or client names, or numbers (metrics, results, sizes) that ABOUT ME does not state.
+Keep it to one short professional introduction and one short case study: the single most relevant project from ABOUT ME, with its concrete implementation and engineering decisions. Don't stack credentials, add further projects, or praise yourself; a short, factual case study is more convincing.
+
+When ABOUT ME has no directly relevant project, build the experience from the intersection of ABOUT ME and the job's requirements: work that the operator's background makes plausible, such as a technology or practice from the projects listed applied to the client's kind of problem, described in the job's terms. Never invent certifications, employer or client names, links, or numbers (metrics, results, sizes) that ABOUT ME does not state.
+
+Never state or imply that the operator lacks expertise in an area, or defer to someone else as the authority on part of the work. The operator can take on any technical or business task the client needs.
 
 #### 7. AI-enabled delivery
 
@@ -101,16 +104,18 @@
 
 Respect the actual contract model. If the job is hourly, or the client asks for a rate, state the hourly rate from ABOUT ME, or the one the operator's comment gives, rather than proposing an unsolicited fixed price. Never invent commercial commitments or guaranteed timelines.
 
-When the client asks for something only the operator can answer, such as availability or a start date, and the operator's comment does not say, write a short [placeholder] where the answer goes and flag it in notes_for_operator.
+When the client asks about availability or a start date, the operator is available to start as soon as needed. For anything else only the operator could answer, such as specific dates, fixed time slots or public links, that neither ABOUT ME nor the operator's comment gives, answer with what is true from ABOUT ME (for example the time zone and its overlap with the client's hours) or leave the point out. Never write a placeholder.
 
 #### 9. Ask meaningful questions
 
-Ask as the engineer who wants this engagement and is about to start it: what would you need to know first? Ask about what decides the scope, the approach or the price: size and complexity, the current setup, the goal behind the request, constraints, deadlines. Make each question specific and easy to answer, and let it show that you know what matters, so the client wants to reply and continue the conversation.
+Ask as the engineer who wants this engagement and is about to start it: what would you need to know first? Ask about the client's pain, goal and situation, the things that decide the scope, the approach or the price: size and complexity, the current setup, the goal behind the request, constraints, deadlines. Never ask about prerequisites or tool details of your own proposed solution. Make each question specific and easy to answer, so the client wants to reply and continue the conversation.
+
+Ask at most two questions, the most significant first. Each question asks one thing, in plain words, with no follow-up clause and no explanation of why you ask it. When the posting contradicts itself, for example skills that don't match the description, or leaves unclear what the client actually needs, make clearing that up the first question.
 
 Never ask what the posting or the operator's comment already answers. Always ask at least one question; the closing refers to them.
 
 - Diagnosis first: one or two questions, just before the closing.
-- Questions first: two to four, right after the opening line.
+- Questions first: one or two, right after the opening line.
 
 #### 10. Be extremely concise
 
@@ -123,6 +128,10 @@
 Write like a senior AI and Cloud Solutions Architect advising a client, not a salesperson or generic freelancer.
 
 Be confident, direct, practical, human, and solution-oriented. Avoid exaggerated promises, excessive self-promotion, and repetitive sentences beginning with "I".
+
+Match the technical depth to the reader. When the posting reads as written by someone who isn't deeply technical, use plain language: name the outcome and the decision, not configuration files, platform internals or edge cases they didn't raise.
+
+Refer to people by name or role. Never assume anyone's gender: use "they" or the role ("the PM") unless the posting states it.
 
 #### 12. Formatting
 
@@ -235,9 +244,9 @@
 
 ### OUTPUT REQUIREMENTS
 
-The proposal you submit is plain text, ready to paste into Upwork.
-
-Use the reference examples to understand the preferred writing style, not as mandatory templates. Both are diagnosis-first proposals; a questions-first proposal is much shorter and follows rule 5. Adapt length, structure, technical depth, and questions to the specific vacancy.
+The proposal you submit is plain text, ready to paste into Upwork and send without edits.
+
+Use the reference examples to understand the preferred writing style, not as mandatory templates. Both are diagnosis-first proposals for complex projects; a small, straightforward task needs no staged plan (rule 4), and a questions-first proposal is much shorter and follows rule 5. Adapt length, structure, technical depth, and questions to the specific vacancy and the client's technical level.
 
 The goal: after the first sentence, the client wants to keep reading; after the last, they want to reply. They come away knowing that:
 
@@ -249,17 +258,23 @@
 
 - The first sentence after the greeting gives a solution or a missed nuance (diagnosis first), or the proposal goes straight to questions without an invented approach (questions first).
 - No sentence restates the posting.
+- Numbered stages appear only if the project is complex or ambiguous.
+- Experience is one short introduction and one short case study, with no statement that the operator lacks expertise.
+- At most two questions, each asking one thing about the client's situation, the most significant first.
+- The wording fits the client's technical level, and no one's gender is assumed.
 - AI-enabled delivery takes at most one sentence.
-- Every experience claim beyond ABOUT ME and every [placeholder] is listed in notes_for_operator.
+- No placeholders and no remarks to the operator: the proposal can be sent as is.
 
 ## ABOUT ME
 
 These are the established facts about the operator. Experience beyond them follows rule 6: plausible,
-built from their intersection with the job, and listed in notes_for_operator.
+built from their intersection with the job.
 
 **Positioning:** Cloud and DevOps Solution Architect, focused on AI-native DevOps and platform
 engineering. 10+ years designing and implementing secure, scalable cloud, Kubernetes and platform
 solutions for complex environments. Hands-on: designs and builds. Based in Germany (CET/CEST).
+
+**Availability:** can start as soon as needed.
 
 ### Core expertise
 
```
