# Council Transcript — 2026-10-27 11:51

## Original question

"wich better deepseek flash v4.1 1017 or glm 5.3 flash"

## Framed question

Which model is better: DeepSeek Flash v4.1 (released Oct 17; verified routable as `opencode/opencode/deepseek-v4.1-flash-free`, `openrouter/deepseek/deepseek-v4.1-flash-1017`) or GLM-5.3 Flash (verified routable as `opencode/opencode/glm-5.3-flash-free`, `openrouter/~z-ai/glm-flash-latest`)? The user runs models through an agentic coding harness (OpenCode), currently on GLM-5.3 flash/free tier. "Better" means practical quality for agentic coding: code quality, tool calling reliability, instruction following, speed, cost. What's at stake: picking the weaker model degrades agent output quality or wastes money/time.

*Note: during synthesis the council verified both models exist and are routable in the harness's own model registry — resolving the ambiguity several advisors raised.*

## Advisor responses

### The Contrarian (anonymized as Response B)

The premise is rotten before we even compare capability.

First problem: these model names are probably wrong. "DeepSeek Flash v4.1 (1017)" and "GLM-5.3 Flash" — I can't verify either, and "1017" reads like a checkpoint date pasted from a changelog. When you can't even pin down the exact artifact, any "which is better" verdict is astrology. The most common failure in model selection isn't picking the weaker model — it's comparing two names that resolve to different weights than the ones the benchmark table tested. If one of these is a free-tier distillation and the other is the full release, you're not comparing models, you're comparing pricing tiers wearing the same costume.

Second problem: "Flash" branding is a marketing tax bracket, not an architecture. Vendors slap "Flash" on latency-optimized, often quantized or reasoning-stripped variants. For agentic coding, what matters isn't headline quality — it's whether the model survives 40-step tool loops without drifting, hallucinating tool names, or truncating diffs. Neither vendor publishes agentic-harness evals. SWE-bench numbers are a proxy with known leakage; a 2-point gap on it tells you nothing about OpenCode-class reliability.

Third problem: the question assumes a single winner. These models are near-free. The rational move isn't a verdict — it's a two-week A/B in your actual harness on your actual repo, tracking tool-call failure rate and retry cost. Cost asymmetry is so low that research time dominates.

The contrarian verdict: the question being asked IS the failure mode. Whoever answers with a confident pick (including me) is bullshitting. Run the bakeoff.

### The First Principles Thinker (anonymized as Response D)

The question as posed is unanswerable, and that's the most useful thing to say.

"Better" is not a property of a model. It's a property of a model-in-a-context. You care about one context: agentic coding in a harness with tool loops, multi-step plans, and per-token cost. Neither the release date nor the name tells you anything about performance there. "DeepSeek Flash v4.1" vs "GLM-5.3 Flash" is a comparison between two marketing labels, not two measurable things. Worse, I can't verify either model exists as named — comparing unverifiable entities is worse than not comparing, because it manufactures false confidence.

What actually determines the outcome? An agent harness amplifies failure modes that benchmarks underweight: malformed tool calls cascading across a 50-step loop, dropped instructions at turn 30, context compaction behavior, stop-token discipline. A model that wins coding benchmarks but fumbles one in twenty tool calls produces worse agents than a "weaker" model that's consistent. And on a free tier, the bottleneck may not be the model at all — it may be rate limits, routing, or quantization the provider applies to that tier.

So the correct question isn't "which is better" — it's "how do I measure this in my harness?" The method is cheap and decisive: take 10 of your own real tasks (not SWE-bench — your repo, your tools), run both models blind, score tool-loop failures, latency, and incomplete plans yourself. Two hours of work, produces ground truth instead of council opinion.

Recommendation: run the eval. Anything else is guessing with extra steps. And verify the models' names and availability first — if "DeepSeek Flash v4.1" doesn't resolve to a real endpoint you can actually route to, the comparison was fiction before it started.

### The Expansionist (anonymized as Response A)

The real answer isn't "which one" — it's "both, sequenced."

Flash-tier models are commodities: near-free, fast, interchangeable. The strongest play is a routing portfolio: GLM-5.3 Flash for high-volume loops (exploration, file recon, tool chains, lint-fixing), route harder synthesis (architecture, gnarly refactors) to a flagship tier occasionally. Agent quality is dominated by loop discipline and the harness, not the flash model inside it.

Second upside everyone misses: DeepSeek being a week old is a feature, not a risk. Open-weights ecosystem rivalry between DeepSeek and GLM keeps flash-tier costs collapsing toward zero — your leverage grows every time they fight. Waiting 30 days costs you nothing when your current model is free.

Third: switching costs are near zero. Both speak the same tool-calling conventions. So A/B them on your actual workload — run the same 20 real agent tasks through each, count successful tool chains and retry rates. Your task distribution is the only benchmark that matters, and the experiment costs an afternoon.

Treat model choice as a quarterly rotation, not a marriage.

### The Outsider (anonymized as Response E — full text from session)

Someone is comparing two "flash" models from two AI companies and trying to pick one to write their code for them. "Flash" apparently means the cheap, fast version — the economy seat, not business class. But note the trap already: GLM-5.3 Flash is labeled *free tier*, DeepSeek's is not. So one real option costs nothing. That alone changes the math — the question isn't just "which is better," it's "is better worth paying for."

The trust problem: "Released Oct 17" tells me it's new, not that it's good. Every AI company claims its new model is better; that's like a restaurant saying its food is tasty. If somebody cites benchmark scores, I can't verify them, and benchmarks are the models' homework — I care whether the agent actually finishes jobs without making a mess.

What a normal person would need to know: neither model can be judged from its specs. You judge them the way you judge a new employee — give both the same actual work for a few days and count the results. Same three or four real tasks: a bug fix, a refactor, wiring up a tool. Whichever one finishes with fewer nonsense edits and less babysitting wins. Cheap and adequate beats expensive and impressive.

One boring outsider warning: "we just switched models" is rarely why your agent output is bad. Prompt quality and harness setup matter more. Test against that possibility too.

### The Executor (anonymized as Response C)

Stop debating. In an agentic harness, model quality is only half the equation. Both models are cheap-tier "flash" variants, so cost difference is noise; the deciding variables are tool-call reliability and instruction-following, and both are testable in 60 minutes.

Monday-morning plan:

1. **Swap models (5 min).** `/models deepseek` and `/models glm` to confirm exact provider IDs both are resolvable under. If DeepSeek v4.1 isn't available through your existing providers, that's your answer before any test — friction-per-swap matters when you'll re-run this weekly.
2. **Run a 5-prompt gauntlet on each model (2×15 min).** Same session context, fresh instance per model:
   - "Fix the failing test in this repo" (a known-broken one) — tests passing = point for correctness.
   - An ambiguous refactor prompt with a constraint ("rename `x` across the repo, don't touch tests") — did it violate scope?
   - A multi-step task: create file A, then edit file B referencing A — tests sequential tool chaining.
   - A prompt requiring a subagent/task dispatch or web fetch.
   - A long-context prompt: paste the spec + a large file, ask for a targeted diff.
3. **Score 4 signals only:** tool-calls needing retry (count), scope violations (hallucinated edits), lines-of-diff to correct fix (verbosity tax), wall-clock time per task.

Decision rule: identical correctness? take the one with fewer tool retries. Fewer retries but slower? still the reliable one — retries are where agentic runs die silently.

Caveat: one 5-prompt run has ~n=1 noise. Run it twice before switching defaults permanently.

## Peer reviews (anonymization mapping: A=Expansionist, B=Contrarian, C=Executor, D=First Principles, E=Outsider)

### Review 1

**Strongest: C.** It's the only one with a concrete, executable protocol — specific prompts, a 4-signal scoring rubric, a decision rule, and an honest n=1 caveat. A and B make the same "run a bakeoff" point but stop at methodology sermonizing; D is a two-line paraphrase of A; E offers strategy but no test.

**Biggest blind spot: A (and B).** Both demand the user "verify the model exists" but never do it themselves — despite having model-availability tooling at hand. Five advisors shipped zero actual facts about either model, then lectured the user on ground truth. Also A/E assume symmetric switching effort; GLM-5.3 Flash is already working on the free tier, so the burden of proof lies with DeepSeek, not 50/50.

**What all five missed:** (1) None noticed the user is *already on* GLM-5.3 Flash — the rational answer is "stay unless DeepSeek demonstrably beats it," which no response states outright. (2) All treat a bakeoff as trivial while conceding free-tier confounds (rate limits, routing) that make A/B results unreliable on a shared free endpoint. (3) No one asked what the current model's *actual* failure modes are — without a diagnosed problem, there's nothing to switch for.

### Review 2

**1. Strongest: C.** A, B, and D all diagnose and punt; E speculates. C is the only one that ends with a concrete, executable protocol — exact prompts, score metrics (retries, scope violations, diff verbosity, wall-clock), a decision rule, and a noise caveat. It also names the decisive gate first: if DeepSeek doesn't resolve in your provider list, done.

**2. Biggest blind spot: A and D.** They're near-identical (D is A compressed — a redundancy failure the council should catch). Their blind spot: refusing any judgment. Refusing to opine when one candidate is *already installed and working* and the other is unverified ignores switching costs and soft signals — a bias toward inaction.

**3. What all five missed:** actual evidence (nobody did even five web searches for community reports on these specific families); OpenCode free-tier routing may silently swap models or quantizations mid-week, corrupting any A/B; concurrency/caching behavior (parallel tool calls, prompt-cache hit rates) — often the real latency/cost lever in agentic loops; model identity verification — nobody actually checked whether "DeepSeek Flash v4.1" exists.

### Review 3

**Strongest: C.** A, B, and D refuse to answer; E speculates. C alone gives a runnable protocol with decision rules and a concrete first check — confirming DeepSeek is even routable.

**Biggest blind spot: D.** It's a compressed copy of A with no added content. B's blind spot is close: it rails about unverifiable names but never verifies them, despite having web search available.

**All five miss:** (1) Verification was trivially easy and nobody did it — LMArena, provider changelogs would resolve the name ambiguity in minutes. (2) GLM-5.3 Flash is the incumbent with accumulated evidence — the user already has empirical data from their own GLM sessions. The question is whether DeepSeek beats a known baseline, not an abstract bakeoff. (3) Free-tier economics: if both endpoints are free, deciding "wrong" costs nothing — weakening the stakes-framing. (4) "DeepSeek released a strong open coding model recently" was left untested everywhere.

### Review 4

**1. Strongest: C.** It's the only response with an executable plan — exact steps, prompts, four concrete scoring signals plus a decision rule (retries beat speed). A and B make the same anti-verdict argument but never operationalize it; C does.

**2. Biggest blind spot: E.** Its routing-portfolio answer asserts "agent quality is dominated by the harness" with no evidence, without verifying either model is routable. D is a collapse of A with no added value.

**3. What all missed:** actual verification via the harness's own model registry — a five-second tool call everyone skipped; free-tier mechanics (rate limits, context caps, quantization differ per tier and confound attribution); long-horizon degradation across 50+ turn sessions (context management failures) not targeted in the gauntlet; larger n at lower fidelity (20 real tasks) beats small n at high fidelity for separating close models.

### Review 5

**1. C is strongest.** The only response with a concrete, executable protocol: exact model-ID resolution check, a 5-prompt gauntlet targeting the failure modes that actually kill agent runs, and explicit scoring rules with a decision tiebreaker. B and E diagnose well but stop at "run an eval" without specifying one. D is B compressed to near-zero content.

**2. A has the biggest blind spot.** It asserts "near-free, fast, interchangeable" and "agent quality is dominated by the harness" — thinly evidenced claims that contradict C's own point that tool-call reliability varies sharply between models. Its economics narrative is rhetoric substituting for the testing it waves at. B's blind spot is second: hedging "including me" while still shifting all work to the user.

**3. All five missed:** (a) irony-check: GLM-5.3 Flash is demonstrably real (this council runs on it), so "I can't verify either" was half-wrong and resolvable by checking; (b) tool/schema support specifics — provider-side function-call handling and context limits break harnesses before any eval; (c) prompt-caching quality and long-context degradation, the real differentiator at flash tier; (d) the decision rule can be "keep current default absent a decisive win" — reversal risk is never priced in.

## Chairman's synthesis

See council-report-20261027-1151.html — the verdict is present in that report and summarized in chat. One artifact note: the council verified both models' availability during synthesis using the harness's own model registry.
