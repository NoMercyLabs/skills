# Project type cues

Read the section that matches what Phase 1 turned up. These are starting points for where meaning tends to hide in each ecosystem, not checklists to complete. A project that mixes types (a Unity game with a Node backend) needs both sections and one shared architecture story that spans them.

## Web applications and APIs

**Identify by:** `package.json` with a server framework, `requirements.txt` with Django/FastAPI/Flask, `go.mod` with an HTTP router, `Gemfile` with Rails.

- Route definitions are the table of contents for the whole application. Find where they are registered and you have the surface area.
- Middleware order determines behavior more than most code does, auth, CORS, rate limiting, error handling. Document the chain, not just its members.
- Trace one authenticated request completely. Where does the token come from, who validates it, what happens on failure.
- Database access: ORM models, raw queries, migration history. Look for the difference between the schema in migrations and the models in code.
- Background work: queues, cron, workers. These are usually undocumented and always surprising.
- Client/server split in full-stack projects: which parts render where, and how they exchange data.

For the API reference, prefer generating from an existing OpenAPI or GraphQL schema when one exists, then verify a couple of entries by hand against the code. Where no spec exists, derive the reference from the route handlers and their validation logic.

## Unity and game projects

**Identify by:** `Assets/`, `ProjectSettings/`, `*.unity` scene files, `*.csproj`, `Packages/manifest.json`.

Unity projects resist code-only reading, because much of the structure lives in scenes, prefabs, and the inspector rather than in scripts. Compensate deliberately:

- `ProjectSettings/ProjectVersion.txt` gives the exact editor version, pin it in the docs, since a mismatched editor version is the most common onboarding failure.
- `Packages/manifest.json` lists packages and registries, including custom ones a new developer will need access to.
- Scene files are YAML and readable. The build scene list in `EditorBuildSettings.asset` tells you the intended flow between scenes.
- `MonoBehaviour` lifecycle methods carry the real control flow: `Awake`, `Start`, `Update`, `FixedUpdate`, `OnEnable`. Note what runs per frame, since that is where performance decisions live.
- Serialized fields (`[SerializeField]`, public fields) are configuration set in the inspector, not in code. Their real values live in scene and prefab assets, so document the field's purpose and where it gets set rather than guessing a value.
- `ScriptableObject` assets are frequently the game's actual data layer.
- Input system, physics layers, tags, and the render pipeline in use (Built-in, URP, HDRP) all change how someone must work in the project.
- Third-party assets from the Asset Store: note them and their licensing implications, since they often cannot be redistributed.

Worth documenting explicitly for games and rarely present: how to run the game from the editor, which scene to open first, and what a new developer needs beyond the repo (licenses, asset packs, platform SDKs).

## Libraries and packages

**Identify by:** a manifest with package metadata and a publish configuration, an `index`/`__init__`/`lib` entry point, versioning files, a `CHANGELOG`.

- The public API is the boundary that matters. Find the export surface and treat everything behind it as implementation detail, readers need to know what they may rely on.
- Distinguish public from internal explicitly. Underscore prefixes, `internal` modules, `@internal` annotations, or simply what the entry point re-exports.
- **A symbol can be exported and still be unreachable.** Cross-check the entry point against the manifest's exports map: a type exported from a deep module with no subpath that re-exports it cannot be imported by a consumer, however public it looks in the source. Monorepos with an exports map usually have several, and a documented import line that does not resolve is worse than an undocumented one, because the reader trusts it. The cheap proof is mechanical: collect every import line the docs show, compile them against the real package, and let the compiler answer.
- Every public function needs: signature, parameter meanings, return shape, thrown errors, and a realistic usage example. Type definitions carry much of this, read them.
- The `CHANGELOG` and version history tell you about breaking changes and migration paths, which consumers need more than they need feature descriptions.
- Peer dependencies, supported runtime versions, and build targets (ESM/CJS, Python versions, target frameworks) belong in the docs because they determine whether the library is usable at all.
- Tests are the best available source of intended usage. Where a doc example is needed, adapting a test is safer than inventing one.

## CLI tools

**Identify by:** a `bin` entry, argument parser setup (`argparse`, `click`, `commander`, `cobra`), an executable entry script.

- The command tree is the structure of the documentation. Every command, subcommand, flag, default, and exit code.
- Configuration usually comes from several layers, flags, environment, config file, defaults. Document the precedence order, since it is invisible and always causes confusion.
- Show realistic invocations with real output, not `command --flag <value>` placeholders alone.

## Data pipelines and ML projects

**Identify by:** DAG definitions, notebook directories, `dvc.yaml`, model checkpoints, heavy numeric dependencies.

- Document flow first: sources, transformations, sinks, and the schedule that drives them.
- Data contracts at each stage, what shape goes in, what comes out, matter more than the transformation code itself.
- Distinguish experiments from production paths. Notebooks are usually experiments; something narrower is what actually runs.
- For ML: training versus inference paths, where model artifacts and datasets live, how versions are tracked, and how to reproduce a result.

## Monorepos and mixed projects

**Identify by:** workspace configuration, `packages/` or `apps/` directories, multiple manifests, a build orchestrator (Nx, Turborepo, Bazel, Lerna).

- Map the dependency graph between packages first. It explains the build order and why changes ripple.
- Shared code and its consumers: what is common, who owns it, what breaks when it changes.
- The root README documents the whole and the relationships; per-package READMEs document the parts and link upward. Resist repeating shared setup in every package, it drifts apart immediately.
- Where sub-projects use different languages or ecosystems, apply the relevant section above to each, then write one architecture document that explains how they fit together. That connecting document is usually the thing nobody has written and everyone needs.
