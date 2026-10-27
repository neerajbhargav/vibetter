# Records docs/demo.gif: one real `vibetter ask` run against ky v2.2.0 with a local model.
# Needs vhs, git, `uv sync` in this repo, and Ollama serving qwen2.5-coder:7b.
# Run from the repo root: vhs docs/demo.tape
# Nothing is cut or edited: the recording waits in real time for the model, and the last
# line of output is the wall time of the command. The model's answer differs between runs.

Output docs/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1280
Set Height 900
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms
Set WaitTimeout 120s

Hide
Type `export PATH="$PWD/.venv/bin:$PATH" PS1='$ ' TIMEFORMAT=$'\nwall time: %1Rs' VIBETTER_PROVIDER=ollama VIBETTER_MODEL=qwen2.5-coder:7b VIBETTER_TRACE=0`
Enter
Type `D="${TMPDIR:-/tmp}/vibetter-demo-ky"; test -d "$D" || git clone -q --depth 1 --branch v2.2.0 https://github.com/sindresorhus/ky "$D"; cd "$D" && echo rea""dy`
Enter
Wait+Screen /ready/
Type "clear"
Enter
Sleep 300ms
Show

Type "# ky v2.2.0, answered by qwen2.5-coder:7b running in local Ollama"
Enter
Sleep 600ms
Type `time vibetter ask "How does ky tell a network error from other errors?" --file source/utils/is-network-error.ts`
Sleep 800ms
Enter
Wait+Screen /wall time/
Sleep 10s
