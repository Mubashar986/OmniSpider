# Generic Project Agent Instructions

For every non-trivial implementation effort, the agent should use the following **five-stage lifecycle** before and during code modifications.

These instructions are intentionally **project-agnostic**. Agents must adapt examples, commands, diagrams, and quality checks to the current repository's actual language, framework, package manager, test runner, operating system, and available tools.

---

## Core Working Mode

1. **Learn first, code second.** The user prefers step-by-step understanding before implementation.
2. **Plan before decomposing, decompose before designing, design before coding.** Broad ideas should start at Stage 0.
3. **Use the codebase as the source of truth.** Do not assume framework, file paths, commands, or architecture.
4. **No code before approval when using Stage 3.** The implementation plan must end with an explicit STOP gate.
5. **User-run commands by default.** For learning workflows, provide copy-pasteable commands and let the user execute them unless they explicitly ask the agent to run them.
6. **Adapt to the stack.** Examples must match the project. For example:
   - React/Vite: use `npm`, `pnpm`, or `yarn` commands found in the repo.
   - Python/FastAPI: use `pytest`, `uvicorn`, `alembic`, or project scripts found in the repo.
   - Rust: use `cargo` only if the repo is actually Rust.
   - Docker: use `docker compose` only if compose files exist.

---

## Stage 0: Roadmap & WBS Planning

Use the `roadmap-wbs-planner` skill.

Use this stage when the user has a broad idea, wants brainstorming, needs feature decomposition, or asks what to build next.

Create a planning document that includes:

1. **Discovery:** Clarify product goals, learning goals, technical direction, constraints, and scope.
2. **Codebase Snapshot:** Inspect the current repository enough to avoid guessing.
3. **Brainstormed Options:** Offer multiple possible implementation/feature directions.
4. **Scope Decision:** Separate Must Have, Should Have, Could Have, and Won't Have Yet.
5. **Roadmap:** Define milestones and epics.
6. **WBS:** Break work into lowest-useful leaf tasks, ideally 30-90 minutes each.
7. **Task Cards:** Each task should include goal, concept learned, dependencies, estimate, acceptance criteria, verification idea, and next lifecycle skill.
8. **First Task Recommendation:** Recommend exactly one task to start next.

No implementation code should be written in this stage.

After Stage 0, the selected leaf task should move into Stage 1.

---

## Stage 1: Understanding Artifact

Use the `concept-to-code-bridge` skill.

Create a detailed conceptual document that explains:

1. **Why & What:** Why the task exists, what concept it uses, and how it works in plain language.
2. **Visuals:** Include Mermaid diagrams and, if an image-generation tool is available, architecture/data-flow images.
3. **Stack Context:** Explain the concept using the current project's actual language and framework.
4. **Alternatives:** Compare at least five practical approaches.
5. **Rationale:** Explain why the selected approach is production-friendly and what breaks if the project skips it.

No code should be written in this stage.

---

## Stage 2: Design Artifact

Use the `codebase-design` skill.

Create a codebase-specific design document that includes:

1. **Current State:** How the relevant files/modules work today.
2. **Proposed State:** How they should connect after the change.
3. **Impact Analysis:** Files, symbols, routes, components, tests, and configs affected.
4. **Regression Analysis:** Risks scored as high/medium/low with mitigations.
5. **Quality Metrics:** Stack-specific quality checks such as type safety, error handling, accessibility, API stability, coupling, security, and performance.
6. **Rollback Plan:** Clear steps to undo the change safely.

No code should be written in this stage.

---

## Stage 3: Implementation Plan Artifact & Approval

Use the `implementation-planning` skill.

Create a reviewable implementation plan that includes:

1. **Change Summary:** Files created/modified/deleted, approximate lines changed, dependencies, risk, and time estimate.
2. **Dependency Check:** Identify package/config changes before code changes.
3. **Execution Order:** List file edits in dependency order.
4. **Diff Previews:** Show proposed edits in `diff` format with nearby context.
5. **Verification Commands:** Provide copy-pasteable commands adapted to the project.
6. **Rollback Commands:** Provide safe rollback instructions.
7. **Explicit STOP:** Wait for user approval before modifying workspace files.

The agent must stop after this stage unless the user explicitly approves implementation.

---

## Stage 4: Testing & Completion Artifact

Use the `testing-verification` skill.

Create a rigorous testing protocol that includes:

1. **Pre-Test Checklist:** Ensure the environment is in a known-good state.
2. **Edge Case Matrix:** Define task-relevant unit, integration, error, security, accessibility, performance, or regression tests.
3. **Commands:** Provide exact commands the user can run.
4. **Expected Outputs:** Explain what pass/fail looks like.
5. **Result Analysis:** When the user shares results, identify root causes and update the plan if needed.
6. **Completion Report:** Summarize tests run, pass/fail status, files changed, and remaining risks.

---

## Optional Deep Learning Skill

Use the `cs-domain-learning` skill when the user wants deeper computer science fundamentals behind a task.

This can be used after Stage 0 for a whole roadmap, or alongside Stage 1 for one leaf task.

---

## Artifact Location and Naming

Unless the user asks otherwise, save lifecycle documents under:

```text
.agents/artifacts/<task-name>/
```

Use names like:

```text
roadmap_wbs.md
task_1_1_understanding.md
task_1_1_design.md
task_1_1_implementation_plan.md
task_1_1_testing.md
task_1_1_cs_concepts.md
```

If the repository does not have `.agents/artifacts/`, create it before writing artifacts.
