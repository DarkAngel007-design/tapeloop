# Why not a framework

tapeloop is deliberately not an agent framework. No chains, no retriever abstractions,
no prompt-template DSL. If it can be a plain function, it stays a plain function.

## What that buys

**Two dependencies.** `openai` and `python-dotenv`. That is a stated feature, enforced
in review, and it is why `pip install tapeloop` pulls 16 packages rather than 90.

**Nothing to learn that is not the problem.** A tool is a function with type hints. A
run is a loop. The concepts you have to hold are the ones the domain actually has —
steps, tools, effects, tapes — not a vocabulary invented to organise them.

**Readable failure.** When something goes wrong you read a tape with `jq`, or read
`m0/loop.py`, which is the whole runtime in twelve lines with the abstractions removed.
There is no framework internals layer between you and the behaviour.

## What tapeloop *is* opinionated about

It is not unopinionated — it just spends its opinions somewhere else:

- **The tape format is a contract.** Versioned, and a breaking change needs a migration.
- **Tools must declare effects.** Not optional, and undeclared means the dangerous one.
- **A stop reason you do not recognise is `OTHER`,** never a finished turn.
- **Errors are data.** A tool that raises kills a run; one that returns a message lets
  the model recover.
- **Determinism is enforced by a lint rule,** not by asking nicely.

Those are constraints on *how the runtime behaves*, not on how you structure your code.

## What it deliberately does not do

- **Not a hosted service.** You run it. The viewer is a local file.
- **Not a prompt-management product.** Prompts live in git.
- **Not a provider zoo.** Only adapters exercised by the conformance suite ship.
- **Not a RAG stack.** Grep and a filesystem get you a long way, and the agent can call
  whatever retriever you already have as a tool.

## The trade

You write more of the glue. In exchange, when something breaks at 2am, everything
between your prompt and the model is one small readable package plus a recording of
exactly what happened.

That trade is only worth it because of the recording. Without a tape, a thin runtime is
just less help; with one, it is less to be wrong about.
