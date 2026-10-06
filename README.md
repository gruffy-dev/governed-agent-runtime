# MOSAIC

**Make the organisation's best operational expertise available wherever it is
needed.**

MOSAIC is an investment in organisational capacity. It turns specialist
knowledge from a scarce, person-dependent resource into a governed capability
that can be reused across teams, systems, and business services.

For a user, the promise is simple: start with the problem, not with the tool.
Instead of finding the right dashboard, learning a provider query language,
locating a runbook, and waiting for the right specialist, the user can ask for
the outcome they need and receive a consistent, evidence-based response.

For the organisation, this creates a more fundamental shift. Experts can
capture what good investigation looks like once. Platform teams can make
trusted operational evidence available once. That combined value can then be
reused by many teams without multiplying integrations, duplicating guidance,
or making every user an expert in the underlying technology.

MOSAIC is therefore not another support chatbot. It is the beginning of a
shared operational intelligence layer: a place where knowledge, evidence, and
governance come together to help people make better decisions, faster.

The MVP makes that future visible and useful now. Its initial read-only
operational scenarios demonstrate the value with real platform evidence while
establishing a foundation that can expand across technologies, teams, and
business processes.

## Why MOSAIC matters

Operational expertise is enormously valuable, but traditional support models
scale it linearly: more demand requires more specialist time. Knowledge remains
distributed across individuals, runbooks, team conventions, and tools, while
users lose time navigating organisational and technical boundaries before
investigation can begin.

MOSAIC is intended to break that dependency.

| Organisational value | What changes |
| --- | --- |
| **More capacity from existing expertise** | Specialists spend less time repeatedly applying routine knowledge and more time on novel, high-value problems. |
| **Shorter time to understanding** | Users reach relevant evidence without first navigating multiple teams, interfaces, and provider-specific languages. |
| **Consistent quality at scale** | Every team can begin from the same approved investigative baseline, regardless of individual experience or time pressure. |
| **Knowledge that survives organisational change** | Important operational practice becomes an owned, reusable asset rather than remaining in individual memory. |
| **Lower cost of integration** | A platform or evidence source can support many use cases without a bespoke point-to-point assistant integration for each one. |
| **Faster onboarding and self-service** | People can benefit from established expertise while they are still learning the organisation's systems and operating model. |
| **Greater confidence in enterprise AI** | AI adoption can expand within visible operational and governance boundaries instead of relying on unrestricted model behaviour. |
| **Freedom to evolve technology choices** | Operational knowledge remains useful when providers, endpoints, models, or presentation channels change. |

The long-term result is a compounding internal capability. Every approved area
of expertise and every governed integration increases what the organisation
can make available through the same experience. Value grows through reuse,
not through rebuilding the agent for each platform or use case.

## The challenge MOSAIC solves

A general-purpose AI assistant can reason about a problem, but it does not
inherently know:

- which operational procedure is approved;
- which systems a particular user or workspace may access;
- how a business-level request maps to a concrete provider tool;
- which environment the user means;
- how to constrain large or sensitive provider responses; or
- how to distinguish evidence from a plausible-sounding assumption.

MOSAIC introduces governed layers between the language model and operational
systems. The model reasons in terms of approved outcomes while trusted runtime
code controls provider selection, arguments, routing, limits, and execution.

```text
User goal
   ↓
Authorised skill (approved procedure)
   ↓
Semantic capability (required outcome)
   ↓
Validated target and provider binding
   ↓
Bounded read-only MCP request
   ↓
Reduced evidence and a qualified response
```

This separation makes investigations repeatable and reviewable, allows a skill
to survive changes in its underlying provider, and gives the organisation a
safer route to operational AI than exposing raw tools or endpoints directly to
the model.

### What makes MOSAIC different

- **Knowledge is a managed product.** Skills are reviewable, versioned assets,
  not prompt fragments hidden inside application code.
- **Intent is separated from implementation.** Skills request semantic
  capabilities; trusted bindings decide which provider and tool can deliver
  them.
- **Context is governed.** Sessions discover only authorised skills, goals see
  only skill-declared capabilities, and target selection never expands access.
- **Evidence is bounded.** Provider results are constrained and reduced before
  entering the model context.
- **The platform is composable.** Procedural skills, operational providers,
  and output formats can evolve independently around stable contracts.

## Core concepts

The concepts used by MOSAIC fall into three groups: the live interaction,
governed organisational knowledge, and the configuration that connects MOSAIC
to operational systems.

### Interaction and runtime concepts

| Concept | Meaning |
| --- | --- |
| **Request** | A directive submitted by a human user, client application, or upstream AI agent. |
| **Goal** | The unit of work MOSAIC creates from a request. It triggers the controlled sequence needed to satisfy the requested outcome: skill discovery, skill selection, capability discovery, target resolution, evidence collection, and response generation. A clarification reply continues the same goal; a later follow-up starts a new one. |
| **Session** | The continuing interaction context across multiple goals. It retains the authorised skill profile and may retain an active target, but capability outcomes from a completed goal cannot satisfy a later goal. |
| **Evidence** | Bounded information returned by an approved capability and used to support the response. |
| **Response** | The result returned for the goal, including relevant conclusions, uncertainty, and material evidence limitations. |

### Governed knowledge concepts

| Concept | Meaning |
| --- | --- |
| **Skill** | A versioned package of organisational knowledge. `SKILL.md` contains the approved instructions describing how to approach a task or present its result. `mosaic.yaml` contains the governed metadata, including the skill's required and optional capability requirements. Neither file contains provider endpoints or credentials. |
| **Skill profile** | The set of skills a session is authorised to discover and use. A profile contains skills, not targets or provider endpoints. |
| **Capability requirement** | A semantic capability referenced by a skill in `mosaic.yaml`. A required capability must reach a terminal outcome before the goal can complete. An optional capability may be used when it materially helps satisfy the goal. |
| **Capability** | A provider-neutral outcome MOSAIC can obtain, such as `kubernetes.pods.running.count`. |

### Integration configuration concepts

| Concept | Meaning |
| --- | --- |
| **Target** | The stable, user-meaningful identity of a real operational environment or platform instance, such as `openshift/uk-dev`. A target remains stable even when its provider endpoint changes. |
| **Provider** | A configured MCP connection, including its concrete endpoint and exact allowlist of callable tools. |
| **Capability binding** | The governed mapping between a semantic **capability** and a provider type and tool, including argument preparation, result extraction, and safety limits. |
| **Routing** | The governed rule that determines which concrete provider instance can serve a capability for a canonical target. Routing may use a dedicated endpoint for one target or a protected selector on an endpoint shared by several targets. Routing chooses where an already-authorised capability executes; it does not grant additional capabilities. |
| **Integration manifest** | The versioned deployment configuration containing the available targets, providers, capabilities, capability bindings, and routing rules. |

Users add skills to their profile; they do not add or select targets as profile
configuration. For each goal, the relevant loaded skills determine which
capabilities MOSAIC may expose. The capability bindings and provider routing
then determine the compatible target scope. The user identifies the intended
environment only through the conversation, either in the original request or
in response to clarification, and MOSAIC resolves that name to a canonical
target. An existing session target may be reused when it remains compatible.

In short: skills determine what MOSAIC is permitted to investigate. Capability
bindings determine how the evidence can be obtained. Routing determines which
provider serves the environment identified in the conversation. Resolving a
target can never grant capabilities beyond those declared by the loaded,
authorised skills.

```mermaid
flowchart LR
    Caller[Human, application, or AI caller] --> Request
    Request --> Goal
    Session --> Goal
    Profile[Session skill profile] --> Skills
    Goal --> Skills[Selected skills]
    Skills --> Requirements[Required and optional capability requirements]
    Requirements --> Capabilities[Semantic capabilities]
    Goal --> Target[Canonical target]
    Capabilities --> Bindings[Capability bindings]
    Target --> Routing[Target routing]
    Bindings --> Provider[MCP provider]
    Routing --> Provider
    Provider --> Evidence
    Evidence --> Response
```

## How MOSAIC works

### High-level architecture

For each new goal, MOSAIC follows a progressive-disclosure flow:

1. The runtime exposes a bounded summary of the skills authorised for the
   current session.
2. The model selects and loads the complete relevant skill set once.
3. MOSAIC exposes only the semantic capabilities declared by those skills.
4. When required, a user-supplied target name or alias is resolved to a
   configured canonical target.
5. Trusted runtime code chooses the compatible provider, maps semantic inputs
   to concrete tool arguments, and injects protected routing values.
6. The MCP result is checked and reduced according to its configured result
   binding before evidence reaches the model.
7. Required capability outcomes are tracked for the goal. MOSAIC prevents a
   final answer while a required capability remains incomplete.
8. An output skill may constrain the final answer, for example as JSON or as a
   plain-language stakeholder summary.

```mermaid
flowchart LR
    User[User or client] --> ADA[ADA invocation and session boundary]
    ADA --> Agent[MOSAIC agent]

    Profile[Session skill profile] --> Skills[Versioned Git skill catalogue]
    Skills --> Agent

    Agent --> Discovery[Skill-gated capability discovery]
    Snapshot[Validated runtime snapshot] --> Discovery
    Snapshot --> Resolver[Target and provider resolver]

    Discovery --> Resolver
    Resolver --> Gateway[MCP execution gateway]
    Gateway --> MCP[Allowlisted MCP provider]
    MCP --> Systems[Enterprise systems]
    Gateway --> Evidence[Bounded reduced evidence]
    Evidence --> Agent
    Agent --> ADA
```

Provider endpoints, concrete tool names, fixed arguments, credentials, and
provider-specific routing values remain outside the skill text and model
prompt.

### Interaction workflows

MOSAIC separates the continuing conversation from the individual units of work
performed within it. A Goal is not a separate process or conversation: it is
the governed unit of work MOSAIC uses to satisfy one requested outcome.

| Concept | Meaning |
| --- | --- |
| **Session** | The longer-lived ADA conversation. It retains conversation history, the authorised Skill profile and, when one has been established, the active Target. |
| **Invocation** | One execution of the MOSAIC agent, normally triggered by a user message. |
| **Goal** | One complete unit of work, from the initial Request until MOSAIC produces a final Response. A Goal may span multiple Invocations when clarification is required. |
| **Goal state** | The trusted working state MOSAIC retains while completing a Goal, including its phase, selected Skills, declared Capabilities, required outcomes, pinned Target and any clarification question. |

#### How the concepts fit together

```mermaid
flowchart TB
    subgraph Session["ADA Session"]
        direction TB

        Context["Session context<br/>Conversation history<br/>Skill profile<br/>Active Target, when known"]

        subgraph Goal1["Goal 1 — same Goal ID"]
            direction LR
            Invocation1["Invocation 1<br/>Initial Request"]
            Invocation2["Invocation 2<br/>Clarification reply"]
            Invocation1 -->|Goal held for clarification| Invocation2
        end

        subgraph Goal2["Goal 2 — new Goal ID"]
            Invocation3["Invocation 3<br/>Follow-up Request"]
        end

        Context -. available to .-> Invocation1
        Context -. available to .-> Invocation2
        Context -. available to .-> Invocation3

        Invocation2 -->|Goal 1 completed<br/>next Request| Invocation3
    end
```

A Session may contain many Goals. Most Goals complete within one Invocation, but
a Goal can span multiple Invocations when MOSAIC needs additional information
from the user.

Only the active Goal's orchestration state is retained as working state.
Completed Requests and Responses remain available through the Session's
conversation history, but their Capability outcomes cannot satisfy a later
Goal.

#### Goal lifecycle

```mermaid
stateDiagram-v2
    [*] --> Planning: New Request<br/>Create Goal ID

    Planning --> Executing: Skills loaded or<br/>Capability work begins
    Planning --> Awaiting: Clarification required
    Executing --> Awaiting: Clarification required

    Awaiting --> Planning: User replies<br/>Same Goal ID<br/>New Invocation ID

    Planning --> Completed: Final Response<br/>Completion checks pass
    Executing --> Completed: Final Response<br/>Completion checks pass

    Completed --> [*]
```

#### How a Goal starts

A new Goal starts when a Request arrives and the Session has no current Goal,
or its previous Goal has completed.

MOSAIC then:

1. Creates a new Goal ID and associates the current Invocation with it.
2. Resolves the Session's trusted Skill profile.
3. Discovers the authorised Skill metadata available to that profile.
4. Gives the model the Request, relevant conversation context and bounded Skill
   summaries.
5. Allows the model either to answer using general knowledge or to select and
   load the complete relevant Skill batch.
6. Exposes only the Capabilities declared by the loaded Skills.
7. Collects governed Evidence when external information is required.
8. Produces one final Response for the complete Goal.

Skill discovery occurs for every new Goal, even when the model subsequently
determines that no specialised Skill is relevant. This applies the same
governed process consistently without preventing general-knowledge responses.

#### How a Goal is held

A Goal is held when it cannot continue safely without additional information,
such as a namespace, queue name or Target.

MOSAIC records:

- that the Goal is awaiting clarification;
- the clarification question;
- the selected Skills;
- the declared and discovered Capabilities;
- any completed required outcomes; and
- the Goal's pinned Target, if one has been resolved.

The current Invocation then ends and the question is returned to the user.
There is no agent process left running in the background: the Goal is held as
trusted state within the ADA Session.

When the user replies, ADA starts a new Invocation. MOSAIC resumes the same
Goal by:

- retaining the existing Goal ID;
- assigning the new Invocation ID;
- retaining the previously loaded Skill batch;
- retaining the Capability and Target state;
- retaining any completed required outcomes; and
- clearing the stored clarification question.

Skill discovery and Skill loading are therefore not repeated for a
clarification reply.

At present, any new message received while a Goal is awaiting clarification is
treated as the answer to that clarification. Reliably detecting that the user
has abandoned the pending Goal and started a different one is planned work.

#### How a Goal ends

The model determines when it has enough information to produce the final
Response, but MOSAIC decides whether the Goal is structurally allowed to end.

Before accepting the Response, MOSAIC confirms that:

- authorised Skill discovery has completed;
- the Goal is not awaiting clarification; and
- every required Capability has reached a terminal outcome.

If the model attempts to respond while a required Capability remains pending,
MOSAIC continues execution internally. The user does not receive the premature
Response.

A terminal outcome does not necessarily mean success. A required Capability
may have:

- succeeded;
- been unavailable;
- produced Evidence that exceeded a governed limit;
- failed;
- timed out; or
- been unavailable because a configured safety limit was reached.

These outcomes allow the Goal to end because no required work remains pending,
but any resulting limitation must be explained in the final Response.

Optional Capabilities may improve the result but do not prevent completion.

For a general-knowledge Goal, Skill discovery still occurs, but no Skill or
Capability execution may be required. The Goal completes when the model
produces its final Response.

MOSAIC therefore enforces **structural completion**: the model decides that the
requested outcome has been addressed, while the runtime ensures that all
required workflow and Evidence obligations have been resolved.

#### What happens after completion

The completed Goal remains recorded as completed until the next Request
arrives. It is not continued or reopened by an ordinary follow-up.

The next Request creates a new Goal with:

- a new Goal ID;
- fresh Skill discovery;
- a new Skill selection;
- new Capability candidates; and
- fresh required-outcome tracking.

Some Session-level context remains available:

- previous conversation and Responses;
- the Session's authorised Skill profile; and
- a compatible active Target, when one has already been established.

Previous Capability outcomes cannot satisfy the new Goal. If the follow-up asks
about the current state of an external system, MOSAIC must gather fresh
Evidence.

Changing the Target also requires new target-bound Evidence. MOSAIC never
carries execution outcomes from a previous Target into the new Goal.

#### Why Goal state is isolated

MOSAIC deliberately separates **conversational continuity** from **operational
trust**.

Conversation history may cross Goal boundaries so that follow-up questions
remain natural. Trusted operational state—such as selected Skills, Capability
candidates and completed Capability outcomes—does not cross those boundaries.

| Decision | Rationale |
| --- | --- |
| A follow-up after completion receives a new Goal ID. | It establishes a clear boundary between the completed outcome and the new Request. This makes execution, Evidence and limitations attributable to the correct unit of work. |
| Skills and Capabilities are selected again for each new Goal. | A follow-up may require a different procedure, output format or system access. Reusing the previous selection could expose irrelevant Capabilities or omit newly relevant Skills. |
| Capability outcomes cannot satisfy a later Goal. | Previous Evidence may be stale, scoped to different inputs or collected for a different question. A successful earlier execution does not prove the current state of an operational system. |
| A clarification reply retains the same Goal. | The requested outcome has not changed; MOSAIC is only obtaining information needed to complete it. Retaining the Goal avoids repeating completed work. |
| The Session Target may be reused, but each Goal pins its own Target. | Reuse makes conversation convenient, while Goal-level pinning prevents Evidence from different environments being combined accidentally. |
| Conversation history remains available. | The model can explain previous findings and understand references such as “that probe” or “the earlier error” without treating the previous investigation as current Evidence. |
| The Skill profile remains Session-scoped. | The profile represents what the Session is authorised to use, while each Goal independently selects the relevant subset. |

This boundary prevents stale Evidence, Target confusion, unrelated Capability
state and previous failures from leaking into a new unit of work.

> Conversation context may cross Goal boundaries; authority, execution state
> and Evidence do not.

#### Example: asking about a completed result

Suppose MOSAIC reports that a deployment has unavailable replicas because its
readiness probe is failing. The user can continue in the same Session and ask:

> What is a readiness probe, and what does that mean for users?

This creates a new Goal, but the previous Response remains available as
conversation context. MOSAIC can explain the unfamiliar term and its likely
impact without repeating the investigation.

If the user instead asks:

> Is the readiness probe still failing?

The new Goal must use the relevant Skills and collect fresh Evidence. The
earlier investigation cannot prove the system's current state.

## Example use cases

### Container-platform investigation

A user can ask MOSAIC to investigate an unhealthy workload, a stalled rollout,
an OpenShift ingress problem, a service-connectivity failure, or a storage
failure. A relevant skill directs the investigation while capabilities obtain
only the necessary pod, controller, event, detail, log, network, or storage
evidence.

Example:

> Investigate why the payments deployment is not ready in namespace
> `payments-prod` on the UK development OpenShift cluster over the last 30
> minutes.

### Bounded workload inventory

MOSAIC can answer focused inventory questions without automatically expanding
them into a full diagnostic exercise.

Example:

> How many running pods are in namespace `order-api`?

The capability can require a namespace, apply a fixed running-state filter,
count the returned collection, and expose only the scope and count to the
model.

### Observability correlation

A time-bounded observability skill can quantify HTTP latency, response classes,
connection errors, resource pressure, or restarts and correlate them with
platform evidence. Provider query languages remain hidden in the capability
binding.

### Governed runbook matching

A database request can be mapped to an approved, versioned runbook through a
governed retrieval provider. The intended use case selects and explains the
runbook; it does not execute the procedure.

### Different outputs from the same evidence

Procedural skills and output skills can be selected together. The same
investigation can produce schema-conformant JSON for automation or a concise
plain-language summary for service owners and executives.

## Configuration overview

MOSAIC configuration is separated by ownership. This distinguishes the
settings required to operate MOSAIC from the knowledge and integrations
contributed by domain teams, the access boundaries established by workspace
administrators, and the choices an individual user will eventually make.

| Configuration area | Owner | Purpose |
| --- | --- | --- |
| **MOSAIC platform configuration** | MOSAIC platform administrators | Connect and operate the MOSAIC runtime, select its approved model, locate its governed configuration sources, and enforce deployment-wide limits. |
| **Operational domain contributions** | Platform and domain teams such as OpenShift, database, observability, and MQ teams | Contribute approved **Skills** and the integration definitions needed to connect their domain knowledge to governed **Capabilities** and **Providers**. |
| **Workspace and access governance** | Tenant, workspace, and access administrators | Determine which approved **Skills** and **Targets** are available to a tenant, workspace, team, or role, and govern Skill profiles, quotas, and access policy. The current MVP implements only a temporary subset of this boundary. |
| **User and Session configuration** | Users | Select from the **Skills** already authorised for them, manage permitted Session preferences, and identify the intended **Target** through conversation. The self-service experience is future work. |

### MOSAIC platform configuration

These settings belong to the MOSAIC deployment and should be managed by MOSAIC
platform administrators. They are not contribution fields for external domain
teams and are not user preferences.

#### Required MCP transport setting

> **Required for the current deployment:** set
> `GOOGLE_API_USE_CLIENT_CERTIFICATE=false` before starting MOSAIC.

| Environment variable | Required value | Purpose |
| --- | --- | --- |
| `GOOGLE_API_USE_CLIENT_CERTIFICATE` | `false` | Disables Google ADK's automatic client-certificate mTLS probe for the current MCP endpoints, which do not use client-certificate authentication. |

Google ADK 2.5.0 attempts to configure an mTLS channel whenever it creates an
HTTP MCP session, including for a plain `http://` endpoint. ADA's
`MCPHeaderProvider` also generates a new `x-uuid` for each header-provider
call. Because ADK includes the complete header set in its session identity,
tool discovery and execution may create separate sessions and repeat the mTLS
probe. On slower hosts this added latency can exceed MOSAIC's 30-second MCP
timeout before the actual tool call completes.

The current MCP providers do not require client certificates, so explicitly
disabling this probe is the correct deployment configuration and avoids the
unnecessary delay. This setting is process-wide. If a future deployment needs
client-certificate mTLS for any MCP provider, do not disable it globally;
introduce a provider-scoped transport configuration instead.

#### Approved model access

| Environment variable | Purpose |
| --- | --- |
| `LLM_PROXY_URL` | Base URL of the organisation's AI Access Layer. |
| `LLM_MODEL` | Model selected through that access layer. |
| `AGENT_IDENTIFIER` | Trusted MOSAIC agent identity sent as `x-agent-id`. This is not end-user identity. |

#### Skill catalogue connection

| Environment variable | Purpose |
| --- | --- |
| `MOSAIC_SKILLS_REPOSITORY_URL` | URL of the Git skill catalogue. |
| `MOSAIC_SKILLS_REPOSITORY_REVISION` | Branch, tag, or revision to activate; defaults to `main`. |
| `MOSAIC_SKILLS_REPOSITORY_CACHE_PATH` | Deployment-local bare Git cache. |
| `MOSAIC_SKILLS_REPOSITORY_ACCESS_TOKEN` | Repository Bearer token; required and never stored in the active Skill catalogue or Git cache. |
| `MOSAIC_SKILLS_SYNCHRONIZATION_TIMEOUT_SECONDS` | Maximum controlled synchronisation time. |

Platform administrators also configure the active **Integration manifest** and
deployment-wide safety limits. The existing environment-variable names retain
`SNAPSHOT` because they are part of the current implementation contract; the
user-facing concept is the Integration manifest.

| Environment variable | Purpose |
| --- | --- |
| `MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_PATH` | Absolute path of the active Integration manifest. |
| `MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_MAXIMUM_BYTES` | Maximum accepted Integration manifest size in bytes. It defaults to `2000000` bytes and may be set to a positive value up to the current implementation-enforced maximum of `10000000` bytes. |
| `MOSAIC_CAPABILITY_RESULT_MAXIMUM_RESPONSE_CHARACTERS` | Deployment-wide ceiling for one encoded Provider response. |
| `MOSAIC_CAPABILITY_RESULT_MAXIMUM_COLLECTION_ITEMS` | Deployment-wide ceiling for one selected Evidence collection. |
| `MOSAIC_CAPABILITIES_MAXIMUM_CANDIDATE_COUNT` | Maximum number of skill-declared Capabilities exposed for one Goal. |
| `MOSAIC_CAPABILITIES_MAXIMUM_METADATA_CHARACTERS` | Maximum serialized Capability metadata exposed for one Goal. |
| `MOSAIC_SKILLS_MAXIMUM_ENABLED_SKILL_COUNT` | Maximum number of Skills authorised by one Skill profile. |
| `MOSAIC_SKILLS_MAXIMUM_DISCOVERY_METADATA_CHARACTERS` | Maximum Skill metadata exposed during discovery. |
| `MOSAIC_SKILLS_MAXIMUM_LOADED_SKILL_COUNT` | Maximum Skills loaded for one Goal. |
| `MOSAIC_SKILLS_MAXIMUM_LOADED_SKILL_CHARACTERS` | Maximum complete Skill content loaded for one Goal. |

### Operational domain contributions

External platform and domain teams contribute two related types of governed
content:

| Contribution | What it contains | Current MVP publication route |
| --- | --- | --- |
| **Skill package** | `SKILL.md` contains the approved instructions. `mosaic.yaml` contains Skill metadata and its required and optional Capability requirements. | Published as a versioned package in the Git Skill catalogue. |
| **Integration definition** | The team's Targets, Providers, Capabilities, Capability bindings, Routing, and Evidence limits. Credentials and access tokens are never contribution content. | Incorporated into the deployment's versioned JSON Integration manifest and activated by MOSAIC platform administrators. |

Skill packages use the hierarchy
`skills/<domain>/<function>/<skill-name>`. MOSAIC validates the complete Git
revision before making its Skills available for progressive disclosure.

The MVP uses one deployment-managed JSON Integration manifest. This is an
interim publication format, not the intended long-term contribution,
authoring, review, or governance interface. Future tooling is expected to let
teams submit and validate independently owned contributions before MOSAIC
composes and publishes an immutable Integration manifest.

### Workspace and access governance

This boundary will determine which approved Skills, Targets, and platform
resources are available within a tenant or workspace and how that access is
assigned to teams, roles, and users. It is expected to govern Skill profiles,
Target visibility, quotas, and access policy through the future identity,
tenancy, RBAC, and frontend services.

#### Temporary MVP configuration

The MVP defines Skill profiles through deployment environment variables. The
current demonstration configuration follows this pattern; the Skill list is
shortened here for readability:

```text
MOSAIC_SKILLS_PROFILES={"mvp-demo":["inspect-container-platform-workloads","investigate-workload-degradation"]}
MOSAIC_SKILLS_DEFAULT_PROFILE_ID=mvp-demo
MOSAIC_SKILLS_SESSION_PROFILE_ASSIGNMENTS={}
```

| Environment variable | Meaning in the current configuration |
| --- | --- |
| `MOSAIC_SKILLS_PROFILES` | Defines a profile named `mvp-demo`. Its array is the complete allowlist of globally unique Skill names available through that profile. Every listed Skill must exist in the active Skill catalogue. |
| `MOSAIC_SKILLS_DEFAULT_PROFILE_ID` | Selects `mvp-demo` when an ADA Session has no explicit profile assignment. |
| `MOSAIC_SKILLS_SESSION_PROFILE_ASSIGNMENTS` | Provides optional overrides from existing ADA Session IDs to profile IDs. `{}` means that the current configuration has no Session-specific overrides. It does not create ADA Sessions or Session IDs. |

The resulting behaviour is:

1. A client or the ADA development UI establishes an ADA Session ID.
2. ADA exposes that existing ID to MOSAIC as part of the invocation context.
3. MOSAIC looks for the ID in `MOSAIC_SKILLS_SESSION_PROFILE_ASSIGNMENTS`.
4. The current `{}` value contains no match, so MOSAIC uses the `mvp-demo`
   fallback named by `MOSAIC_SKILLS_DEFAULT_PROFILE_ID`.
5. MOSAIC looks up `mvp-demo` in `MOSAIC_SKILLS_PROFILES` and authorises the
   Skills in its array for that Session.

Consequently, every Session in the current demonstration receives the same
`mvp-demo` Skill profile. The profile controls which Skills the Session may
discover and load; it does not automatically load or execute every listed
Skill.

This is a temporary MVP mechanism tightly coupled to runtime deployment. It is
managed by platform administrators rather than individual users, and it is not
a replacement for authenticated identity, user or tenant ownership,
resource-level authorisation, or a durable Skill profile service. A future
trusted frontend and backend will establish and validate Session ownership and
resolve Skill access from identity, workspace membership, and RBAC. Session IDs
will be opaque routing references rather than proof of identity or permission.
Changes to the temporary environment configuration require a MOSAIC runtime
restart.

The MVP does not yet provide workspace-scoped Target visibility. Compatible
Targets are derived from the Capabilities declared by loaded Skills and the
available Capability bindings and Routing in the Integration manifest.

### User and Session configuration

The intended user-facing configuration is the **Skill profile**: a selection
of Skills drawn from those already authorised through Workspace and access
governance. A user may add or remove permitted Skills without configuring the
underlying integrations.

Users do not configure Providers, Capability bindings, or Routing. They
identify the intended Target through the conversation, either in the original
Request or in response to clarification, and MOSAIC may reuse a compatible
Target within the same Session.

The MVP does not yet provide this self-service experience. Skill profiles and
Session assignments currently remain platform-managed through the temporary
environment-variable configuration described above.

## The capability runtime snapshot

Set `MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_PATH` to the absolute path of the JSON
file to load. The complete file is validated at startup and rejected if it is
missing, malformed, internally inconsistent, or references an unapproved
provider/tool combination. The file is also rejected when it exceeds
`MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_MAXIMUM_BYTES`. This limit defaults to
`2000000` bytes (2 MB, approximately 1.91 MiB) and may be configured to a
positive value no greater than the current implementation-enforced maximum of
`10000000` bytes (10 MB, approximately 9.54 MiB). This upper bound is a MOSAIC
application guardrail rather than an absolute filesystem or JSON limitation;
changing it requires a code change. The size check occurs before MOSAIC reads
and parses the JSON file.

The current document structure is:

```json
{
  "schema_version": 3,
  "snapshot_id": "my-platform-2026-09-24",
  "targets": [],
  "providers": [],
  "capabilities": []
}
```

An end-to-end target-independent example is available at
[`config/capability-runtime-snapshot.example.json`](config/capability-runtime-snapshot.example.json).

### 1. Identify the snapshot

`schema_version` must currently be `3`. `snapshot_id` is a deployment-owned
immutable identifier used to distinguish published configurations.

### 2. Define targets

A target is a user-facing identity for a deployed platform instance:

```json
{
  "id": "openshift/uk-dev",
  "display_name": "UK development OpenShift",
  "aliases": ["uk-dev", "cluster1"]
}
```

Target IDs use `vertical/target`. IDs are globally unique; aliases are
case-insensitively unique within a vertical. The same alias may exist in
different verticals, in which case capability context must disambiguate it or
MOSAIC asks the user to clarify.

There is no implicit default target. MOSAIC retains one resolved target for a
session, and each goal pins the target it used.

### 3. Configure providers

Each provider declares an MCP endpoint, its functional provider type, its exact
tool allowlist, and one routing mode:

| Routing mode | Use when | Required routing fields |
| --- | --- | --- |
| `target_independent` | The provider does not depend on a platform target. | `mode` only |
| `endpoint_per_target` | One endpoint serves exactly one canonical target. | `target_id` |
| `shared_endpoint` | One endpoint serves several targets using a protected selector argument. | `target_argument_name`, `target_bindings` |

Endpoint-per-target example:

```json
{
  "provider_name": "kubernetes-uk-dev",
  "provider_type": "kubernetes",
  "transport": "streamable_http",
  "header_strategy": "ada_request_context",
  "base_url": "https://kubernetes-uk-dev.example.com/mcp",
  "allowed_tool_names": ["resources_list", "resources_get", "pods_log"],
  "routing": {
    "mode": "endpoint_per_target",
    "target_id": "openshift/uk-dev"
  }
}
```

Shared-endpoint example:

```json
{
  "provider_name": "shared-observability",
  "provider_type": "observability",
  "transport": "streamable_http",
  "header_strategy": "ada_request_context",
  "base_url": "https://observability.example.com/mcp",
  "allowed_tool_names": ["query_range"],
  "routing": {
    "mode": "shared_endpoint",
    "target_argument_name": "cluster",
    "target_bindings": [
      {
        "target_id": "openshift/uk-dev",
        "argument_value": "example-cluster-a"
      }
    ]
  }
}
```

The protected target value is injected by trusted code. A skill, user, or
model cannot set or override it.

### 4. Define semantic capabilities

A capability describes an outcome rather than an MCP implementation. Its
provider binding connects that outcome to an allowlisted tool while keeping
the semantic name stable:

```json
{
  "name": "inventory.objects.count",
  "description": "Count objects within one explicitly supplied scope.",
  "provider_bindings": [
    {
      "provider_type": "inventory",
      "tool_name": "objects_list",
      "priority": 100,
      "read_only": true,
      "argument_bindings": [
        {
          "tool_argument_name": "scope",
          "source": "semantic",
          "semantic_argument_names": ["scope"],
          "required": true
        }
      ],
      "result_binding": {
        "content_source": "text_content",
        "content_media_type": "application/json",
        "content_block_index": 0,
        "json_pointer": "/items",
        "operation": "count",
        "output_field": "object_count",
        "evidence_tool_argument_names": ["scope"],
        "maximum_response_characters": 500000,
        "maximum_collection_items": 2000
      }
    }
  ]
}
```

Capability names are lowercase dotted identifiers. Skills refer only to these
names.

Lower priority numbers are preferred. The current runtime rejects ambiguous
provider/type/tool/target combinations rather than choosing one by file order.
Mutating bindings are disabled by default.

### 5. Bind arguments

Argument bindings translate semantic inputs into concrete provider arguments.
Three sources are supported:

| Source | Behaviour | Typical use |
| --- | --- | --- |
| `semantic` | Copies one validated runtime input. | Namespace, pod name, or time window. |
| `fixed` | Supplies a non-overridable configured value. | API version, resource kind, safe tail limit, or read-only mode. |
| `template` | Builds one provider value from explicitly declared semantic inputs. | A governed query or resource identifier. |

Semantic argument example:

```json
{
  "tool_argument_name": "namespace",
  "source": "semantic",
  "semantic_argument_names": ["namespace"],
  "semantic_argument_patterns": {
    "namespace": "^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$"
  },
  "required": true
}
```

Fixed argument example:

```json
{
  "tool_argument_name": "kind",
  "source": "fixed",
  "fixed_value": "Pod"
}
```

Template fields must exactly match the declared semantic argument names. Keep
templates governed and narrow; do not use them to create an unrestricted query
language for the model.

### 6. Bind and bound results

Every live capability binding requires a result binding. It identifies the
authoritative MCP result field, decodes it, selects a value with an RFC 6901
JSON Pointer, and performs one limited operation.

Current operations are:

- `count` — return the number of items in the selected collection;
- `select` — return the selected bounded value without provider-specific
  interpretation.

Example:

```json
{
  "content_source": "text_content",
  "content_media_type": "application/json",
  "content_block_index": 0,
  "json_pointer": "/items",
  "operation": "count",
  "output_field": "object_count",
  "evidence_tool_argument_names": ["scope"],
  "maximum_response_characters": 500000,
  "maximum_collection_items": 2000
}
```

`content_source` may be `structured_content` or `text_content`. Text may be
JSON, YAML, or plain text. Structured content does not declare a media type or
block index. Plain text cannot use a JSON Pointer.

The response and collection limits are safety boundaries, not truncation
instructions. Evidence exceeding a configured limit fails explicitly rather
than being silently shortened.

Deployment-wide ceilings can further restrict snapshot declarations:

- `MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_MAXIMUM_BYTES`
- `MOSAIC_CAPABILITY_RESULT_MAXIMUM_RESPONSE_CHARACTERS`
- `MOSAIC_CAPABILITY_RESULT_MAXIMUM_COLLECTION_ITEMS`
- `MOSAIC_CAPABILITIES_MAXIMUM_CANDIDATE_COUNT`
- `MOSAIC_CAPABILITIES_MAXIMUM_METADATA_CHARACTERS`

## Recommended configuration workflow

1. **Start with the user outcome.** Define the operational question the
   capability must answer, independently of any provider.
2. **Inspect the real MCP contract.** Capture the exact endpoint, tool name,
   input schema, authentication expectations, response envelope, and bounded
   sample responses.
3. **Define targets and ownership.** Use stable canonical identities rather
   than endpoint names or user aliases.
4. **Create the provider allowlist.** Include only tools required by approved
   capabilities.
5. **Map arguments.** Separate user/model-supplied semantic inputs from fixed
   policy and protected routing values.
6. **Design bounded result handling.** Prefer provider-side filtering,
   pagination, aggregation, time windows, or limits before MOSAIC reduction.
7. **Connect skills by semantic name.** Add required and optional capability
   names to the relevant skill's `mosaic.yaml`.
8. **Validate the complete candidate.** Do not activate fragments of an
   invalid snapshot.
9. **Test against the real provider.** Generated or inferred bindings remain
   unverified until exercised against the target MCP server.
10. **Publish an immutable snapshot.** Change `snapshot_id` when publishing a
    new validated configuration.

Never place credentials or access tokens in the runtime snapshot. Provider
authentication is supplied through the approved runtime header strategy.

## Using AI to seed a platform integration

MOSAIC does not need to begin each platform integration with an author defining
one outcome and one binding at a time. A frontier model with repository access
can inspect an MCP server's source code, registered tools, input schemas, tests,
documentation, and representative responses. It can combine that evidence with
the MOSAIC configuration contracts and its broader understanding of a
well-known platform to propose a useful initial set of operational outcomes.

The result is a **candidate platform seed**: a coherent starting point that a
platform team validates and improves, not configuration that an LLM publishes
directly into a live MOSAIC deployment.

### The pattern demonstrated by the MVP

The initial Kubernetes and observability integration was produced using this
approach. Analysis of the Kubernetes and observability MCP implementations was
used to identify common read-only investigations and the smallest useful tool
combinations needed to support them. The resulting seed currently includes two
Providers, 53 provider-neutral Capabilities, and 11 container-platform and
OpenShift Skills.

Those Skills cover common areas such as workload inspection, rollout failure,
service connectivity, storage failure, ingress, capacity, platform health, and
time-bounded observability signals. The generated artifacts preserve MOSAIC's
separation of responsibilities:

| Generated artifact | Purpose |
| --- | --- |
| `SKILL.md` | Describes when a Skill applies, the inspection or investigation it performs, the evidence standards it follows, and its safety constraints without exposing provider-specific tools. |
| `mosaic.yaml` | Declares the Skill's required and optional Capability requirements. |
| Integration manifest JSON | Defines the Targets, Providers, Capabilities, Capability bindings, Routing, argument mappings, result extraction rules, and safety limits needed to execute those Skills. |
| Generation and validation report | Records the inspected source revision, excluded or unsafe tools, unresolved deployment facts, assumptions, test evidence, and items requiring platform-owner approval. This report is not part of the runtime JSON. |

The model can therefore propose many related outcomes in one pass while the
runtime configuration remains outcome-oriented. It should not create one Skill
or Capability for every MCP tool or expose the MCP server directly to the
model.

MOSAIC loads one complete Integration manifest JSON at startup. A
platform-specific manifest contribution may be generated separately for review,
but it is not an additional runtime input. Before activation, merge its
Targets, Providers, and Capabilities into the deployment's single complete
snapshot, assign a new `snapshot_id`, and validate the whole document
atomically.

### Choose outcomes before tools

A useful seed normally begins with two predominant themes. They are starting
points rather than an exhaustive taxonomy:

| Theme | Purpose | Typical scope |
| --- | --- | --- |
| Resource and state inspection | Obtain current state or selected configuration for a known entity. | One explicitly selected Target and, where applicable, one exact resource name. |
| Investigation | Combine several bounded observations to explain a reported symptom or answer an operational question. | The smallest set of related entities and evidence required to test supported explanations. |

Other benign outcomes, such as bounded discovery, relationship tracing, or
configuration comparison, may also belong in the seed when the provider can
support them safely. A seed should not include an outcome merely because a
provider exposes a corresponding tool. Each Skill must be useful to a user,
and each Capability must have a clear semantic result independent of the
provider that implements it.

### Recommended seeding process

```mermaid
flowchart TD
    Source[MCP repository at a pinned revision] --> Analyse[AI-assisted contract and platform analysis]
    Guidance[Platform documentation, runbooks and common tasks] --> Analyse
    Contracts[MOSAIC schemas and existing catalogue] --> Analyse
    Deployment[Targets, endpoints and policy constraints] --> Analyse
    Analyse --> Seed[Candidate platform seed]
    Seed --> Skills[SKILL.md and mosaic.yaml packages]
    Seed --> Manifest[Integration manifest contribution]
    Seed --> Report[Assumptions and unresolved inputs]
    Skills --> Validate[Schema, reference and safety validation]
    Manifest --> Validate
    Report --> Review[Platform-owner review]
    Validate --> Test[Sandbox MCP tests and representative responses]
    Test --> Review
    Review --> Publish[Approved immutable publication]
```

1. **Provide and pin the authoritative MCP repository.** This is the first
   mandatory input to any seed. Before proposing Skills, Capabilities, or
   bindings, the model must inspect the MCP server's implementation to establish
   its registered tools, input contracts, result shapes, errors, limits, and
   security behaviour. Give the model access to an exact repository commit or
   release, including tool registration code, schemas, tests, fixtures, and
   documentation. Record both the repository and revision so the analysis can
   be reproduced and reviewed when the MCP server changes. If the source is not
   available, generation should stop rather than infer a provider contract.
2. **Supply MOSAIC's contracts.** Provide the current Integration manifest and
   Skill-package schemas, representative approved packages, and the existing
   Capability catalogue. The model should reuse an existing Capability when it
   describes the same semantic outcome rather than create a provider-specific
   duplicate.
3. **Add operational context.** Supply platform documentation, runbooks,
   common support questions, known failure modes, and the permitted safety
   boundary. Use that material to identify useful resource and state
   inspections, common investigations, and any other genuinely useful benign
   outcomes. This prevents the seed from becoming a mechanical copy of the MCP
   tool list.
4. **Provide deployment facts.** Supply canonical Targets, endpoint topology,
   provider types, target aliases, and routing constraints. Credentials must
   never be included. A reviewable example may use clearly identified
   placeholders when deployment values are not yet known. Those values must be
   reported as unresolved, and the result must not be described as
   activation-ready.
5. **Define the safety boundary.** Classify every considered provider operation
   as observational, active probing, mutating, or sensitive. Exclude anything
   outside the approved boundary. When an MCP tool accepts a general command,
   query, or script, never expose that input directly as a Capability. Bind
   only reviewed fixed operations or narrowly templated operations whose
   caller-supplied values are validated as data. Protect Target selectors in
   Routing, require exact resource scope where practical, and exclude
   wildcards when they could create broad or unbounded access.
6. **Generate the candidate seed.** Ask the model to identify common tasks,
   create globally unique Skills, declare their Capability requirements, and
   generate the corresponding Capabilities and bindings. Start with the
   smallest useful read-only surface.
7. **Validate mechanically.** Validate file structure, schemas, names,
   references, tool allowlists, argument sources, Routing, JSON Pointers,
   response limits, and uniqueness before attempting execution. Test accepted
   semantic values as well as wildcards, separators, newlines, and command or
   query injection attempts wherever templates are used.
8. **Test against the MCP server.** Exercise representative normal, empty,
   error, and oversized responses in a safe environment. Confirm that each
   result binding extracts the intended Evidence and that the proposed Skills
   can complete their stated outcomes. Treat provider documentation and source
   disagreements as findings: the registered implementation is authoritative
   for tool names and runtime contracts, while documentation remains important
   evidence of intended behaviour.
9. **Review and publish.** The owning platform team confirms operational
   usefulness, permissions, terminology, safety, and omissions before the
   Skill packages and Integration manifest are versioned and published.

### Constraining broad provider tools

Some MCP servers expose a broad command, query, or script interface rather than
one narrowly scoped tool per operation. Such a tool can still support a benign
seed, but the provider tool itself must never become a general Capability.

For each approved outcome, the Integration manifest should instead bind the
broad tool to either:

- a complete fixed read-only operation; or
- a reviewed read-only template containing only narrowly validated semantic
  values, such as an exact resource name.

The model must not be able to select the command verb, supply the complete
command or query, override a protected Target selector, append additional
syntax, or replace exact scope with a wildcard. Validation patterns should use
the smallest safe character set and length supported by the initial platform
scope. Broader valid names can be added later through a reviewed configuration
change.

This is defence in depth rather than a substitute for provider security. The
MCP service identity should still receive only the platform permissions needed
for the approved operations. Active probes, mutations, sensitive-data access,
and broad unbounded reads remain excluded unless a later policy explicitly
governs them.

When deployment facts are missing, the generator may produce a clearly named
example manifest with placeholder endpoints, Targets, and protected routing
values. The separate generation report must list every placeholder and the
candidate must remain unpublished until the owning team supplies and validates
the real values.

### Where this approach works best

| Platform type | Expected seeding quality |
| --- | --- |
| Widely used vendor or open-source platform | Strong starting point. Public platform conventions and operational knowledge can complement direct inspection of the authoritative MCP source. Repository code and supplied schemas still take precedence over model memory. |
| Internally developed platform with good runbooks and tests | Useful when the model receives the source, domain terminology, common support tasks, failure modes, and representative responses. More owner input and review will normally be required. |
| Internally developed platform with little documentation | The model can inventory tools but cannot reliably infer organisational intent or the most valuable investigations. Begin by capturing runbooks and expected outcomes with domain experts. |

### Starter prompt

The following prompt can be adapted for a coding model with access to the MCP
repository and a workspace containing the MOSAIC schemas and examples:

```text
Create a candidate MOSAIC platform seed for <platform name>.

Authoritative inputs:
- MCP repository: <path or URL>
- MCP revision: <exact commit or release>
- MOSAIC Integration manifest schema and current approved manifest: <paths>
- MOSAIC Skill-package schema and approved examples: <paths>
- Platform documentation and runbooks: <paths or URLs>
- Representative MCP responses or test fixtures: <paths>
- Canonical Targets, provider endpoints, and Routing constraints: <details>
- Approved safety boundary: <for example, read-only investigation only>

Inspect the MCP implementation rather than relying on tool names alone. Locate
the registered tools, exact input schemas, result envelopes, error behaviour,
pagination or size controls, authentication assumptions, tests, and examples.
Record the exact source revision and every authoritative source used. Record
disagreements between documentation and the registered implementation; use the
implementation as the authority for actual tool names and runtime contracts.

Identify a coherent starter set of common operational outcomes supported by the
available tools. Use resource and state inspection plus investigation as the
two predominant themes, while including other useful benign outcomes where
the evidence supports them. Do not treat this as an exhaustive taxonomy and do
not create one Skill or Capability per tool. Begin with user and operator
outcomes, reuse existing provider-neutral Capabilities where their semantics
match, and propose new Capabilities only when necessary.

Generate:
1. An Integration manifest candidate using schema_version 3, containing only
   verified Targets, Providers, Capabilities, Capability bindings, Routing,
   argument mappings, result extraction rules, and bounded safety limits.
2. A package for each proposed Skill containing SKILL.md and mosaic.yaml.
   Each package must use a globally unique Skill name, SKILL.md must remain
   provider-independent, and mosaic.yaml must declare complete required and
   optional Capability requirements.
3. A generation report describing the common tasks selected, tools considered,
   tools excluded, read or mutation classification, Capability reuse decisions,
   source provenance, documentation discrepancies, assumptions, placeholders,
   and unresolved inputs.
4. A validation report covering schemas, cross-references, tool allowlists,
   argument bindings, Routing, result extraction, limits, and any sandbox tests.

Rules:
- Treat the pinned repository and supplied contracts as authoritative; never
  substitute model memory for conflicting source evidence.
- Do not invent endpoints, Targets, tools, arguments, response fields, JSON
  Pointers, authentication behaviour, limits, or provider guarantees.
- Do not include credentials or secrets.
- Prefer the smallest useful read-only tool surface.
- Classify considered operations as observational, active probing, mutating,
  or sensitive, and include only operations within the approved boundary.
- Never expose a general command, query, or script input as a Capability.
  Use reviewed fixed operations or narrowly templated read-only operations.
- Treat every caller-supplied template value as data: validate its type,
  length, and smallest safe character set; reject wildcards, separators,
  newlines, and syntax injection unless explicitly required and governed.
- Make scope arguments mandatory when omission could broaden access.
- Keep provider tool names and provider-specific instructions out of SKILL.md.
- Put policy-controlled values in fixed bindings and protected shared-endpoint
  target selectors in Routing.
- Declare explicit response-character and collection-item limits. Never rely on
  silent truncation.
- If an authoritative deployment fact is missing, use a clearly marked
  placeholder only in an example candidate, put it in the separate generation
  report, and do not describe the artifact as activation-ready.
- Do not modify or publish an existing approved catalogue. Write the candidate
  files to a separate review directory.

Before completing, verify that every Skill requirement resolves to a defined
Capability, every Capability binding uses an allowlisted Provider tool, every
Target resolves unambiguously through Routing, and every result binding has
been checked against a representative response. For every templated binding,
also demonstrate that valid values are accepted and wildcard or injection
attempts are rejected.
```

AI-assisted generation accelerates discovery and authoring; it does not replace
schema validation, live contract testing, security review, or approval by the
team responsible for the platform.

## Validation and failure behaviour

MOSAIC validates configuration before use and fails closed when it cannot
establish an unambiguous approved path. Among other checks, it rejects:

- unsupported schema versions and unknown fields;
- duplicate targets, providers, capabilities, tools, or bindings;
- malformed target IDs, aliases, capability names, and argument names;
- routing references to unknown targets;
- capability bindings without an allowlisted provider tool;
- multiple provider endpoints that could serve the same capability and target;
- attempts to populate a protected shared-endpoint target argument through an
  ordinary capability binding;
- live bindings without bounded result handling; and
- configured result limits above the deployment-wide ceilings.

Provider availability can still change after startup. Invocation failures are
returned as safe bounded outcomes; MOSAIC does not query a registry before
every call.

## Security and platform limitations

The current MVP has deliberate boundaries:

- Operations are read-only by default. Mutating workflows and approval gates
  are not yet implemented.
- ADA supplies REST, SSE, WebSocket, session, event, state, artifact, memory,
  and development UI interfaces. MOSAIC does not implement a parallel API
  transport.
- Caller-supplied user, session, application, and header values are not proof
  of identity. Authentication must occur at a trusted boundary ahead of ADA.
- The current MCP header path transports identity-related values but is not an
  end-to-end OAuth delegation or authorization solution.
- Resource-level RBAC remains the responsibility of each MCP server and its
  backend.
- The present development Kubernetes integration uses a configured kubeconfig
  identity and is not multi-tenant.
- Durable multi-instance operation requires shared PostgreSQL-backed ADA
  session storage.
- Reliable concurrent updates to one session require an external distributed
  lock or version/compare-and-set mechanism.
- Only one active target per session is supported in the MVP. Multi-target
  comparison and explicit same-target failover are future work.
- Raw provider results and large evidence collections are not retained in ADA
  session state. Providers must offer a safely bounded interactive scope.
- Runtime snapshots are loaded at startup. Atomic hot reload without restart
  is not yet implemented.
- The current JSON file is a runtime publication format. A governed catalogue
  authoring, validation, composition, and visualisation interface remains to be
  built.

## Roadmap

Near-term MVP work includes:

- completing live validation of the expanded container-platform and
  observability bindings;
- safely handling oversized Kubernetes event evidence;
- guaranteeing visible disclosure of incomplete or failed required evidence;
- connecting and validating MQ and database-runbook providers;
- evaluating compound skill selection and output contracts; and
- demonstrating simultaneous sessions with different authorised skill
  profiles.

Longer-term platform work includes:

- OAuth/OIDC authentication, trusted identity, tenant membership, and session
  ownership;
- durable session lifecycle, quotas, retention, compaction, and distributed
  concurrency controls;
- usage attribution, audit records, rate limits, and billing integration;
- a governed capability catalogue with independently owned contributions;
- a visual interface for building, validating, reviewing, and publishing
  target/provider/capability/skill bindings;
- atomic distribution and hot reload of immutable runtime snapshots;
- scalable progressive evidence, pagination, refinement, and optional governed
  evidence artifacts;
- explicit multi-target queries and same-target provider failover; and
- deterministic workflows and authenticated human approval gates for
  high-risk or mutating operations.

## Local verification

The local unit suite can be run from the repository root with:

```bash
PYTHONPATH=app ./.venv/bin/python -m unittest discover -s app/mosaic/tests
```

Live ADA and MCP verification is separate from the local deterministic test
suite and requires the target deployment configuration and providers.
