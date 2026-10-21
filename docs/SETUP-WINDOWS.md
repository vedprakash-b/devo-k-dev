# Setting up on Windows (WSL2)

Do these once, in order. Each step ends with a check; don't move on until it passes.
Commands in **PowerShell** blocks run in Windows; everything else runs in the **Ubuntu** terminal.

## 0. Before you start

- Read your internship agreement's clause on personal projects and intellectual property.
  Build Devo-K-Dev on personal time and your own hardware, with a personal GitHub account,
  and never use employer code, data or credentials.
- You need about 15 GB of free disk and, ideally, 16 GB of RAM (8 GB works with fewer
  parallel agents later).

## 1. Install WSL2 with Ubuntu

Open **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart when asked. Ubuntu opens and asks for a Linux username and password (it can differ
from your Windows login). Then, in PowerShell:

```powershell
wsl --update
wsl -l -v
```

**Check:** `Ubuntu-24.04` is listed with `VERSION 2`.

Optional but recommended: cap WSL's memory so Windows stays responsive. Create
`C:\Users\<you>\.wslconfig` with:

```ini
[wsl2]
memory=8GB
processors=4
```

then run `wsl --shutdown` in PowerShell and reopen Ubuntu. Use about half your RAM.

## 2. Install Docker Desktop

1. Download and install Docker Desktop for Windows from docker.com.
2. Settings → General: **Use the WSL 2 based engine** is on.
3. Settings → Resources → WSL integration: turn on **Ubuntu-24.04**. Apply and restart.

In **Ubuntu**:

```bash
docker run --rm hello-world
docker compose version
```

**Check:** "Hello from Docker!" and a Compose version of 2.20 or newer.

## 3. Install the Linux tools

```bash
sudo apt update && sudo apt install -y git make curl unzip build-essential gh
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL -l
uv --version
```

**Check:** `uv --version` prints a version.

## 4. Connect Git and GitHub

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"     # the email on your personal GitHub
git config --global init.defaultBranch main
gh auth login        # GitHub.com → SSH → generate a new key → login with a browser
```

**Check:** `gh auth status` says you are logged in.

## 5. Unpack the repo inside Linux

Keep the code in the Linux file system (`~/code`), not under `/mnt/c`: file access from Linux
to Windows drives is many times slower and breaks file watching.

```bash
mkdir -p ~/code && cd ~/code
unzip /mnt/c/Users/<your-windows-user>/Downloads/devo-k-dev-m0.zip
cd devo-k-dev
git init
```

## 6. Run M0

```bash
make setup          # installs Python 3.12, creates .venv and uv.lock, installs git hooks, creates .env
make up             # pulls and starts Temporal, PostgreSQL + pgvector, Redis (first run downloads ~600 MB)
make doctor         # every required check: ok (provider keys: warn is expected)
make smoke          # prints "Namaste, Ved! ..." and a Temporal UI link
make check          # ruff, ruff format, mypy strict, pytest
make test-integration
```

Open <http://127.0.0.1:8233> in Windows to see the smoke workflow's history.

If anything fails, copy the full command output into the next chat with the resume block.

## 7. Publish to GitHub through a pull request

```bash
gh repo create devo-k-dev --public --description "An AI engineering team on durable execution"
git commit --allow-empty -m "chore: initial commit"
git remote add origin git@github.com:<your-github-user>/devo-k-dev.git
git push -u origin main

git switch -c m0-setup
git add -A
git commit -m "feat: M0 project setup: local stack, doctor, smoke workflow, CI"
git push -u origin m0-setup
gh pr create --fill --base main
gh pr checks --watch
```

**Check:** all four CI jobs are green. Then merge: `gh pr merge --squash --delete-branch`.

Finally, protect `main` on GitHub: Settings → Branches → Add rule for `main` → require a pull
request and require the four CI status checks to pass.

## 8. Editor

```bash
code .
```

VS Code opens connected to WSL and offers the recommended extensions from
`.vscode/extensions.json`. Select the interpreter at `.venv/bin/python`.
