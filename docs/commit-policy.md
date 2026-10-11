<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Per-file maintainer commits

The maintainer's selected workflow uses one changed file per commit and a distinct,
professional message explaining that file's change. A delivered patch is not itself
a commit. Review and apply it before creating history in the actual Git checkout.

`evals/batch6-commits.json` contains the reviewed file/message plan for Batch 6.
Subsequent batches should provide an equivalent plan. Inspect the diff for each file,
then use an explicit path rather than staging the whole repository:

```bash
git diff -- path/to/file
git add -- path/to/file
git commit --only -m "docs: explain the accepted-record scope of time-series diagnostics" -- path/to/file
```

Use the applicable planned message, not the example verbatim for every file. `--only`
limits that commit to its path and leaves unrelated staged work outside the commit.
New files must first be added. Do not use `git add .`, automatic force pushes or commit
amendment to collect unrelated changes. Renames/deletions need an explicit reviewed
plan because a rename has two paths and is not a literal one-path commit.

A batch can contain dependencies between files. Intermediate per-file commits may
therefore fail validation until the batch is complete. Run the full validation on
its final HEAD before pushing the sequence; record that tested HEAD in release evidence.
A historical commit touching one file is not automatically a releasable artifact.

Messages use a clear verb and concrete outcome: `docs`, `fix`, `feat`, `test`, `build`
or `chore` may identify the purpose. Avoid generic messages such as “update file”,
“changes”, “final fix” or praise about quality. A one-file commit should still explain
why the change matters when its reason is not evident from the subject.

No installer creates commits, publishes the repository or changes its visibility.
