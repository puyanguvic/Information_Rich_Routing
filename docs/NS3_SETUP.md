# ns-3 Setup

The simulation artifact is validated against ns-3 `3-dev` at the following
commit:

```text
80ffa6e66e9c59d7e80c324576daaf574ba3481b
```

The local development checkout used this commit:

```text
VERSION: 3-dev
commit date: 2026-05-05
subject: core: Add move constructor and move assignment operator to Ptr class
```

The same information is recorded in `ns3/NS3_VERSION`.

## Option A: Install ns-3 under `$HOME`

Use this path if the machine does not already have ns-3.

```bash
cd ~
git clone https://github.com/nsnam/ns-3-dev-git.git ns-3-dev-git
cd ~/ns-3-dev-git
git checkout 80ffa6e66e9c59d7e80c324576daaf574ba3481b
```

If the GitHub mirror is unavailable, the GitLab source can be used instead:

```bash
cd ~
git clone https://gitlab.com/nsnam/ns-3-dev.git ns-3-dev-git
cd ~/ns-3-dev-git
git checkout 80ffa6e66e9c59d7e80c324576daaf574ba3481b
```

Then link this artifact's ns-3 module into the checkout:

```bash
ln -s ~/Information_Rich_Routing/ns3/contrib/information-routing \
  ~/ns-3-dev-git/contrib/information-routing
```

Adjust the left-hand path if the artifact repository was cloned somewhere else.

## Option B: Use an existing ns-3 checkout

Set `NS3_ROOT` to the checkout and move it to the validated commit:

```bash
export NS3_ROOT=/path/to/ns-3-dev-git
git -C "$NS3_ROOT" fetch --all --tags
git -C "$NS3_ROOT" checkout 80ffa6e66e9c59d7e80c324576daaf574ba3481b

ln -s /path/to/Information_Rich_Routing/ns3/contrib/information-routing \
  "$NS3_ROOT/contrib/information-routing"
```

If a previous `contrib/information-routing` directory exists, move it aside
first rather than overwriting it.

## Build

From the ns-3 root:

```bash
cd ~/ns-3-dev-git
./ns3 configure --enable-examples --enable-tests
./ns3 build information-routing
```

The ns-3 release notes for `3-dev` list the expected minimum toolchain as
Python 3.10, CMake 3.20, and a modern C++ compiler. Use g++ 11.1 or newer, or a
recent clang toolchain.

## Smoke Test

Run one bounded smoke test before launching the full paper matrix:

```bash
cd ~/ns-3-dev-git
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_quick.json \
  --ns3-root ~/ns-3-dev-git \
  --output-dir ~/ns-3-dev-git/results/information-routing/smoke
```

Analyze the smoke output:

```bash
python3 contrib/information-routing/utils/analyze_wan_sweep.py \
  --input-dir ~/ns-3-dev-git/results/information-routing/smoke \
  --output-dir ~/ns-3-dev-git/results/information-routing/smoke-analysis
```

## Full Matrix Entry Point

The paper sweep launcher is:

```bash
cd ~/ns-3-dev-git
CONFIGS="exp1 exp2 exp4 exp5 exp6 exp7 exp8 exp11" \
  RUN_ID=eval-v5-main \
  OUT_ROOT=~/ns-3-dev-git/results/information-routing/eval-v5-main \
  MAX_PARALLEL=24 \
  TIMEOUT_SEC=1200 \
  bash contrib/information-routing/utils/run_eval_v5_parallel.sh
```

Supplementary batches can be launched by changing `CONFIGS`, for example
`CONFIGS="exp3 exp9 exp10 exp12"`. The heatmap-fill config is stored as
`wan_sweep_eval_design_v5b_heatmap_fill.json` and can be launched directly with
`run_wan_sweep.py` if needed.
