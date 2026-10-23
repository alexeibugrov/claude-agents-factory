# Search tuning: raw measurement log (2026-10-23)

Every Upwork UI read (logged in, Chrome) and Apify run from the session, in order. Counts are Upwork's "jobs found". F = location Europe, Northern America, Western Asia, Australia and New Zealand + t=0,1 + amount=1000-. Times before 13:50 are estimates and run up to 40 minutes fast.
| time | id | query | filters | count | hourly | fixed |
|---|---|---|---|---|---|---|
| ~14:00 | T1 | "ai agent" | - | 1281 | 865 | 416 |
| | A | "ai agents" | - | 1101 | 753 | 348 |
| | B | "ai agent" OR "ai agents" | - | 1788 | 1234 | 554 |
| | C | "ai agent" AND NOT "ai agents" | - | 687 (= 1281-594, exact) | 481 | 206 |
| | D | "ai agent" "ai agents" (implicit) | - | 595 (= AND) | 384 | 211 |
| 12:43 | E | ("ai agent" OR "ai agents") AND NOT (n8n OR zapier) | - | 1319 | 921 | 398 |
| | G | ("ai agent" OR "ai agents") AND (n8n OR zapier) | - | 1135 (!! expected <= 469: E+G=2454 > B=1788) | 706 | 429 |
| | S1 | saved "ai infra" (8 quoted phrases, no OR) | - | 0 | | |
| 12:46 | H | n8n OR zapier | - | 1411 | | |
| | I | ("ai agent" OR "ai agents") AND n8n | - | 738 (!! > 469) | | |
| | J | "ai agent" AND (n8n OR zapier) | - | 1246 (!! ~ all of "ai agent") | | |
| 12:50 | K1 | "ai agent" AND ("langchain" OR "langgraph") | - | 945 (!! impossible) | | |
| | K2 | "ai agent" AND NOT ("langchain" OR "langgraph") | - | 1144 (overlap 137 plausible) | | |
| | K4 | "ai agent" AND "langchain" | - | 116 | | |
| 12:53 | L1 | "ai agent" AND NOT "langchain" | - | 1165 (= 1281-116 exact) | | |
| | L2 | ("ai agent" AND "langchain") OR ("ai agent" AND "langgraph") | - | 945 (!! same wrong number as K1) | | |
| | L3 | "ai agent" | - | 1281 | | |
| 12:55 | M1 | "ai agent" AND "langgraph" | - | 77 (10/10 tiles contain langgraph) | | |
| | M2 | "langgraph" | - | 121 | | |
| 12:58 | P4 | "ai agent" "ai agents" AND NOT ("langchain" OR "langgraph") | - | 501 | | |
| 13:01 | P1 | "ai agent" AND "langchain" AND "langgraph" | - | 56 (= 116+77-137 predicted from K2: exact) | | |
| | P2 | ("ai agent" OR "ai agents") AND NOT ("langchain" OR "langgraph") | - | 1617 | | |
| 13:02 | P3 | "ai agents" AND NOT ("langchain" OR "langgraph") | - | 974 (P2 = 1144+974-501 = 1617: exact) | | |

Syntax verdict: OR-of-phrases exact; space = AND; AND chains exact; AND NOT exact with OR-groups on both sides;
any positive AND mixed with OR (K1, L2, G, I, J) returns an inflated wrong count -> never use it.
| 13:08 | N30 | 30 never-matching phrases OR "ai agent" (31 operands, 580 chars) | - | 1281 (no truncation) | | |
| 13:10 | N100 | 100 never-matching phrases OR "ai agent" (101 operands, 1910 chars) | - | 1281 (no truncation; UI has no practical limit) | | |
| 13:12 | LOC4 | "ai agent" | location=Europe,Northern America,Western Asia,Australia and New Zealand | 1037 (all 4 chips accepted) | | |
| 13:14 | R1 | "ai agent" | LOC4, t=0 | 716 hourly; newest 50 span 2 days: 23 no-rate, 25 below $70, 2 reach $70 | | |
| 13:15 | R2 | "ai agent" | LOC4, t=0, hourly_rate=70- | 55; 0 of the 23 no-rate jobs present -> filter drops all no-rate hourly; keeps $35-$70 (max-based) | | |
| 13:17 | R3 | "ai agent" | LOC4, t=1, amount=1000- | 76 | | 76 |
| | R5 | "ai agent" | LOC4, t=0,1, amount=1000- | 792 = 716 + 76 exact -> amount applies to fixed only | 716 | 76 |
| 13:12 | G1 | draft G1 (21 terms) | F = LOC4, t=0,1, amount=1000- | 2014 (H 1844, F 170); newest 50 span ~24h -> ~50/day; classes F2 H70:5 HNR:16 HLOW:27; noise: sales/support/booking "agents", assistants | | |
| 13:16 | m-agentic | "agentic" AND NOT (rest of G1) | F | 518; 0/10 relevant (china agent, sales agent, support agent): single quoted word is stemmed -> "agentic" = "agent" | | |
| 13:17 | m-ai-assistant | "ai assistant" AND NOT (rest of G1) | F | 100; ~2/10 relevant (VAs, translators) | | |
| 13:20 | m-agentic-phrases | ("agentic ai"/"agentic workflow(s)"/"agentic system(s)"/"agentic automation") AND NOT ("ai agent" OR "ai agents") | F | 67; ~7/10 relevant -> adopt | | |
| 13:21 | m-low | (multi-agent, multi agent, autonomous agent(s), agent(s) sdk, crewai, autogen, langgraph, model context protocol) AND NOT core | F | 31; ~8/10 relevant -> adopt | | |
| 13:24 | m-langchain | "langchain" AND NOT base | F | 16; ~6/10 -> adopt | | |
| 13:25 | m-mcp | "mcp" AND NOT base | F | 80; ~3/10 (Google Ads, Workday, Meta buyer = certification MCP) -> drop, use "mcp server(s)" | | |
| 13:27 | m-voice | ("voice agent" OR "voice agents") AND NOT base | F | 64; ~6/10 ("AI Voice Agent" is not matched by "ai agent") -> adopt | | |
| 13:28 | m-agentdev | ("agent development" OR "agent developer") AND NOT base | F | 31; ~7/10 -> adopt | | |
| 13:40 | m-assist+mcpserver | ("ai assistants" OR "mcp server" OR "mcp servers") AND NOT base | F | 71; 0/10 (influencer, GEO, cold callers) -> drop "ai assistants" | | |
| 13:41 | m-voiceai | ("voice ai" OR "ai voice" OR "conversational ai") AND NOT base | F | 356; 0/10 (AI video ads, voice-over) -> drop | | |
| 13:43 | m-chatbot | ("chatbot" OR "chatbots" OR "ai chatbot") AND NOT base | F | 251; ~0-1/10 -> drop | | |
| 13:45 | G2 | draft G2 (36 terms) | F | 3429 (H 3089, F 340); newest 50 span ~13h -> ~90/day; classes F4 H70:6 HNR:12 HLOW:28; noise: SEO, EA/VA, marketing | | |
| 13:50 | m-claude | "claude" AND NOT (G1 base + rest of G2, 59 terms) | F | 0 (!!) | | |
| 13:52 | claude | "claude" | F | 1743 | | |
| | claude-G1 | "claude" AND NOT (G1 base 24) | F | 1341 | | |
| 13:54 | claude-fill | "claude" AND NOT (59 never-matching phrases) | F | 1743 -> NOT-group size is fine; some G2 term breaks it | | |
| 13:57 | bisect-A | "claude" AND NOT (G2 rest[:18]) | F | 1250 | | |
| | bisect-B | "claude" AND NOT (G2 rest[18:]) | F | 1458 | | |
| 14:00 | U60 | G1 base + G2 (60 real terms, OR only, 1121 chars) | F | 0 (!!) -> silent complexity limit between 36 and 60 real terms | | |
| 14:03 | U48 | first 48 of U60 | F | 3712 (works) | | |
| 14:05 | U54 | first 54 of U60 | F | 0 (fails) -> limit between 49 and 53 terms | | |
| 14:07 | U53 | first 53 of U60 (100 words) | F | 0 (fails) | | |
| 14:09 | U50 | first 50 of U60 (94 words) | F | 0 (fails) | | |
| 14:11 | S58 | 58 real single-word terms (58 words) | F | 16196 (works) -> limit counts words, not terms | | |
| 14:13 | U49 | first 49 of U60 (93 words) | F | 0 (fails). U48 = 90 words works. LIMIT ~90 words of real terms per query; over it Upwork silently returns 0 | | |
| 14:16 | m2-claude | "claude" AND NOT (G2 rest) | F | 1111; ~1/10 relevant (SEO, Shopify, VA mention Claude as a tool) | | |
| 14:17 | m2-llm | (llm/llms/large language model(s)) AND NOT (G2 rest) | F | 346; ~3/10 (SEO "LLM visibility" noise) -> keep | | |
| 14:20 | m2-genai | (generative ai/genai/gen ai) AND NOT (G2 rest) | F | 292; ~1/10 (AI image/video gen) -> drop | | |
| 14:21 | m2-rag | "rag" AND NOT (G2 rest) | F | 10; ~5/10 -> keep | | |
| 14:24 | m2-integration | (ai integration/implementation/adoption/transformation) AND NOT (G2 rest) | F | 195; ~5/10 -> keep | | |
| 14:25 | m2-consult | (ai consultant/ai consulting) AND NOT (G2 rest) | F | 56; 0/10 (cold callers for AI consultancies) -> drop | | |
| 14:28 | m2-advisor | (fractional cto/technical advisor/architecture review/production readiness) AND NOT (G2 rest) | F | 96; ~4/10 -> keep | | |
| 14:29 | m2-evals | (evals/guardrails/llm evaluation/prompt injection) AND NOT (G2 rest) | F | 53; ~0-1/10 -> drop evals, guardrails | | |
(log times above 13:36 were estimates and run ~40 min fast; real UTC from here on)
| 13:50 | APIFY U48 | first 48 of U60 via actor (run r72J8V0F7ECClI4Gk) | F | upwork_total 3775 (UI 3712 ~13:30) -> actor parses long queries like the UI | | |
| 13:51 | APIFY U49 | first 49 of U60 via actor (run dPzPqFzebxvXJgQ7w) | F | 0 items, no total in log, status SUCCEEDED -> silent failure on the actor too | | |
| 13:53 | Q1 | "claude" AND NOT (claude phrases + G2v2 rest) | F | 886; ~1/30 relevant -> drop bare "claude" (add "claude-based") | | |
| 13:53 | Q2 | (claude code/api/ai/expert/developer/agent(s)) AND NOT (G2v2 rest) | F | 298; ~4-5/10; EA/PA noise via "claude ai" -> keep phrases, drop "claude ai" | | |
| 13:53 | G3 | draft G3 (28 terms) | F | 971 (H 880, F 91); newest 50 span ~1.5 days -> ~35/day; F5 H70:2 HNR:13 HLOW:30; many full-stack jobs that mention CI/CD | | |
| 13:56 | m3-cicd | (ci/cd, cicd, github actions, gitlab ci) AND NOT (G3 rest) | F | 148; ~2/10 (full-stack devs listing CI/CD) -> drop ci/cd, cicd; keep github actions, gitlab ci | | |
| 13:56 | m3-titles | (solutions architect, cloud engineer, cloud infrastructure) AND NOT (G3 rest) | F | 92; ~5/10 -> keep | | |
| 13:56 | m3-short | (helm, eks, gke, aks, k8s, sre) AND NOT (G3 rest) | F | 20; 0/10 (sales, sourcer, bookkeeper) -> drop | | |
| 13:56 | m3-cloud | (aws, azure, gcp, google cloud, docker) AND NOT G3 | F | 680; ~5/10 (GCP/BigQuery architects, Databricks, self-hosted AI) -> adopt | | |
| 13:58 | RA1 | (workflow automation, internal assistant, ai automation) AND NOT G1 | F | 529; ~4/10 relevant (AI automation builds, Claude integration) -> real gap | | |
| 13:58 | RA2 | (cursor, codex, ai platform, genai infrastructure, ai developer, fde, openai api) AND NOT G2 | F | 329; ~3/10 relevant (AI developer builds) -> real gap | | |
| 13:59 | RA3 | (amazon web services, containerization, microservices, cost optimization, cloud cost, systems architect) AND NOT G3 | F | 54; ~2/10 -> not added | | |
| 13:59 | RA4 | (code review, cto) AND NOT G2 | F | 124; ~2/10 (DevOps one is in G3) -> not added | | |
| 13:58 | RA5 | (openai, chatgpt, gpt) AND NOT G2 | F | 1434; ~0-1/10 -> not added | | |
| 13:59 | RA6 | "n8n" AND NOT G1 | F | 267; ~3/10 (AI automation engineers) -> candidate for optional G4 | | |
| 14:01 | G4 | (ai automation(s), ai developer(s), workflow automation(s), n8n, openai api, codex) | F | 1591; newest 50 span ~20h -> ~60/day; ~45% relevant-looking; heavy overlap with G1 -> merge into S1 | | |
| 14:08 | CA-mixed | user's saved "cloud architect": (5 role phrases) AND (aws OR azure OR gcp) | - | 483 | | |
| 14:08 | CA-roles | 5 role phrases alone | - | 1022 | | |
| 14:09 | CA-not | (5 role phrases) AND NOT (aws OR azure OR gcp) | - | 539 = 1022-483 exact -> this mixed query IS correct; mixing is unreliable (K1/L2 wrong), not always wrong | | |
| 14:10 | S1-tier1 | S1 + contractor_tier=1 | F | 52 of 2305 (2%); ~1/10 relevant -> tier filter not worth it | | |
| 14:10 | US-only | job 2113616209249805419 page (logged in) | - | "Only freelancers located in the U.S. may apply." -> actor-only jobs are client-restricted posts hidden from a DE freelancer | | |
| 14:11 | APIFY narrow | "permit processing" / "supabase reviewer", no filters | - | both found (actor can see them) | | |
| 14:12 | APIFY narrow+F | same + LOC4/t/amount | F | permit: SERP 2, post-fetch kept 0; supabase: search returned 0 | | |
| 14:13 | actor log | parsed filters | - | location expanded to 31 named European countries + region names; amount -> budget "1000-" | | |
| 14:15 | job pages | permit = NLD client, hourly no rate; supabase = DEU client, fixed $1,500 | - | both countries are in the actor list | | |
| 14:16 | APIFY isolate | supabase + t/amount only -> found; + LOC4 only -> 0; + location=Germany -> 0 | - | the logged-out location filter loses some jobs; clientCountryCode is present in records | | |
| 14:18 | S1-noloc | S1 without location | t=0,1, amount=1000- | 2878 (+25%); newest 50 in 12h (~100/day); 10/50 outside regions (IN, PH, SG, KE, HK); tiles show both "USA"/"United States", "NLD"/"Netherlands" | | |
| 14:19 | S2-noloc | S2 without location | t=0,1, amount=1000- | 2558 (+22%); newest 50 in 12h | | |
| 14:20 | S3-noloc | S3 without location | t=0,1, amount=1000- | 2107 (+33%); 44/50 under 24h | | |
| 14:22 | APIFY codes | supabase + location=DEU / Germany,DEU | - | 0 / 0 -> country codes do not fix the actor's location filter | | |
| 14:23 | volume | walk-back publishTimes (with location) | - | S1 102/24h peak 8/30min; S2 96 peak 9; S3 83 peak 9; union 201, overlap 80 | | |
| 14:19 | PARITY current | agent's configured URL | tier 2,3, hourly 40-, Americas+Europe | UI 787 vs actor 815 (run Up33F6pZZRK6ek3ui); top-10: 8 shared; UI-only "AI Chatbot Developer - Instagram DM" (client "FRA" code format); actor-only "Urgent: Full-Stack Developer" (US-only pattern) | | |
| 14:20 | PARITY saved ai assistant | query only, no filters | - | UI 2346 vs actor 2482 (run XzqnASUxm1RgoHZSg); top-10 identical incl. the "FRA" job (no location filter -> no loss) | | |
| 14:20 | PARITY saved cloud architect | query only, no filters | - | UI 483 vs actor 526 (run LJteIXY0dzp3osNCw); top-10: 9 shared + actor-only "Fractional Information Security Officer" | | |
| 14:21 | CONFIRM S1 | final, no location | t=0,1, amount=1000- | UI 2878 vs actor 3093 (run ZBV9NEpcCatVHJ9i9); top-10: 9 shared + actor-only US-restricted "Urgent" | | |
| 14:22 | CONFIRM S2 | final, no location | t=0,1, amount=1000- | UI 2558 vs actor 2743 (run O41iwSateUcmBPa3s); top-10: 9 shared + same actor-only | | |
| 14:22 | CONFIRM S3 | final, no location | t=0,1, amount=1000- | UI 2107 vs actor 2301 (run WBvjptkRBXLyuPWI5); top-10: 7 shared + 3 actor-only (US-only attorney etc.) | | |
