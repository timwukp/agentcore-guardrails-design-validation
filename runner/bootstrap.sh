#!/bin/bash
# EC2 user data for the grx-validation runner. `@@BUCKET@@` and `@@REGION@@` are substituted by
# runner/provision.py, so no identifier is written in this file and it needs no redaction waiver.
#
# This runs once, as root, at first boot. Everything it does is idempotent, because a rerun after
# a failed step is the normal case. It ends by writing /opt/grx/bootstrap.done, which is the
# marker runner/sync.py and runner/run.py wait on — polling for a FILE the bootstrap writes last
# is a condition; polling for "a few minutes" is a guess (feedback_kirocrew_methodology_lessons).
set -uo pipefail
# Scratch on the root VOLUME from the first line onward, not in /tmp. AL2023 mounts /tmp as a
# tmpfs at half of RAM (957 MB on a t3.small), and the two largest things this script does —
# unpacking the 178 MB evidence archive and pip-building wheels — both stage there by default. The
# mkdir comes BEFORE the export because a TMPDIR that does not exist breaks dnf and pip with an
# error that names neither.
mkdir -p /opt/grx/tmp
export TMPDIR=/opt/grx/tmp
exec > >(tee -a /var/log/grx-bootstrap.log) 2>&1
echo "=== grx bootstrap $(date -u +%Y-%m-%dT%H:%M:%SZ)"

BUCKET="@@BUCKET@@"
REGION="@@REGION@@"
HOME_DIR=/opt/grx
REPO="$HOME_DIR/grx-validation"

# --- packages. Python 3.12 is what the measurements were taken on; AL2023 ships 3.11 as
# `python3`, and 3.12 is available as its own package. Both are tried and the version actually
# used is recorded, so a reader can tell which interpreter produced a result rather than assuming.
dnf -y install tar gzip git tmux jq >/dev/null || true
PY=""
for cand in python3.12 python3.11; do
  if dnf -y install "$cand" "$cand-pip" >/dev/null 2>&1 && command -v "$cand" >/dev/null; then
    PY="$cand"; break
  fi
done
[ -z "$PY" ] && PY=python3
echo "interpreter: $PY -> $($PY -V 2>&1)"

install -d -o ec2-user -g ec2-user "$HOME_DIR"
# Re-owned to ec2-user: the mkdir at the top of this file ran as root, and the suite runs as
# ec2-user. This is also what runner/run.py points TMPDIR at — 26 test modules copy the 178 MB
# evidence tree into their pytest tmp_path, so one suite run wrote 954 MB of scratch and the next
# command failed with `[Errno 28] No space left on device` while df on the repo showed 18 GB free.
install -d -o ec2-user -g ec2-user "$HOME_DIR/tmp"
install -d -o ec2-user -g ec2-user "$HOME_DIR/logs"

# --- code. Pulled from S3 rather than cloned: the repo is PRIVATE, and putting a GitHub token on
# an instance that anyone with ssm:StartSession can reach would make the instance a credential
# store. The tarball is produced by runner/sync.py push, which excludes .git, the venvs and
# evidence/ (see that file for why evidence is built on the instance rather than shipped to it).
if aws s3 cp "s3://$BUCKET/code/grx-validation.tar.gz" /opt/grx/tmp/code.tgz --region "$REGION"; then
  install -d -o ec2-user -g ec2-user "$REPO"
  tar -xzf /opt/grx/tmp/code.tgz -C "$REPO" --strip-components=1
  chown -R ec2-user:ec2-user "$REPO"
  echo "code: extracted $(find "$REPO" -name '*.py' | wc -l) python files"
else
  echo "code: no tarball yet — run 'runner/sync.py push' from the laptop, then 'grx-refresh' here"
fi

# --- venv, from the pinned versions the local measurements were made with.
sudo -u ec2-user "$PY" -m venv "$REPO/.venv-oracle" 2>/dev/null || true
if [ -f "$REPO/runner/requirements.txt" ]; then
  sudo -u ec2-user "$REPO/.venv-oracle/bin/python" -m pip install -q --upgrade pip
  sudo -u ec2-user "$REPO/.venv-oracle/bin/python" -m pip install -q \
      -r "$REPO/runner/requirements.txt"
  sudo -u ec2-user "$REPO/.venv-oracle/bin/python" -c \
      'import boto3, numpy, scipy, pytest; print("deps:", boto3.__version__, numpy.__version__,
       scipy.__version__, pytest.__version__)'
fi

# --- two helpers, so a session does not have to remember the paths.
cat > /usr/local/bin/grx-refresh <<EOF
#!/bin/bash
# Re-pull the code tarball and reinstall deps, without re-imaging.
set -euo pipefail
aws s3 cp "s3://$BUCKET/code/grx-validation.tar.gz" /opt/grx/tmp/code.tgz --region "$REGION"
tar -xzf /opt/grx/tmp/code.tgz -C "$REPO" --strip-components=1
"$REPO/.venv-oracle/bin/python" -m pip install -q -r "$REPO/runner/requirements.txt"
echo "refreshed \$(date -u +%FT%TZ)"
EOF

cat > /usr/local/bin/grx-evidence <<EOF
#!/bin/bash
# Pull the evidence archive, which 26 test modules read. Separate from grx-refresh because it is
# 178 MB across 26,620 files and changes only when a live case runs — see runner/sync.py.
set -euo pipefail
aws s3 cp "s3://$BUCKET/code/evidence.tar.gz" /opt/grx/tmp/evidence.tgz --region "$REGION"
tar -xzf /opt/grx/tmp/evidence.tgz -C "$REPO"
echo "evidence: \$(find "$REPO/evidence" -type f | wc -l) files"
EOF

cat > /usr/local/bin/grx-inputs <<EOF
#!/bin/bash
# Lay down the inputs PREREGISTRATION.yaml names OUTSIDE the repo: the document under test and the
# PII source corpus. They cannot travel in the code tarball because they are not in the tree, and
# without them 21 of the offline suite's tests refuse to run and the redaction gate cannot find its
# subject. Uploaded by 'runner/sync.py push-inputs'.
set -euo pipefail
T=/opt/grx/tmp/inputs.tgz
aws s3 cp "s3://$BUCKET/code/inputs.tar.gz" "\$T" --region "$REGION"
# Unpacked to scratch and copied, rather than extracted straight to two roots with tar member
# selection: the archive carries no directory entries, and 'tar --strip-components N <prefix>' on a
# prefix that has no member of its own is a per-implementation question. 'cp -a' is not.
rm -rf /opt/grx/tmp/inputs
install -d /opt/grx/tmp/inputs
tar -xzf "\$T" -C /opt/grx/tmp/inputs --strip-components=1
# 'repo-parent' beside the repo, because the pre-registration names it '../…'.
[ -d /opt/grx/tmp/inputs/repo-parent ] && cp -a /opt/grx/tmp/inputs/repo-parent/. "$HOME_DIR"/
# 'home' into EVERY home that can run the suite. The code resolves '~/…' through Path.home(), so
# where the document has to be depends on who started pytest: SSM commands run as root, an
# interactive session runs as ec2-user. A 74 KB file in both places costs less than a suite whose
# result depends on how it was launched.
if [ -d /opt/grx/tmp/inputs/home ]; then
  for h in /root /home/ec2-user; do
    install -d "\$h"
    cp -a /opt/grx/tmp/inputs/home/. "\$h"/
  done
  chown -R ec2-user:ec2-user /home/ec2-user 2>/dev/null || true
fi
chown -R ec2-user:ec2-user "$HOME_DIR" 2>/dev/null || true
echo "inputs: \$(find /opt/grx/tmp/inputs -type f | wc -l) file(s) installed"
EOF

cat > /usr/local/bin/grx-publish <<EOF
#!/bin/bash
# Push results, the ledger and the evidence tree back to S3. Evidence is uploaded because it is
# the audit archive a claim is looked up in; it stays inside the account, and the laptop is what
# runs the redaction gate before anything reaches GitHub.
set -euo pipefail
cd "$REPO"
STAMP=\$(date -u +%Y%m%dT%H%M%SZ)
aws s3 sync results "s3://$BUCKET/out/\$STAMP/results" --region "$REGION" --only-show-errors
aws s3 cp state.json "s3://$BUCKET/out/\$STAMP/state.json" --region "$REGION"
aws s3 sync evidence "s3://$BUCKET/out/\$STAMP/evidence" --region "$REGION" --only-show-errors
echo "\$STAMP" > /opt/grx/last-publish
echo "published \$STAMP"
EOF
chmod +x /usr/local/bin/grx-refresh /usr/local/bin/grx-evidence /usr/local/bin/grx-inputs \
         /usr/local/bin/grx-publish

# Run once here, so a fresh instance is complete rather than complete-except-for-its-subject. The
# `|| echo` keeps a first boot that predates the upload from failing the whole bootstrap: the code
# tarball is handled the same way above, and the recovery is the same one line.
grx-inputs || echo "inputs: none uploaded yet — run 'runner/sync.py push-inputs', then 'grx-inputs'"

# Appended under a marker, and only once. This script is re-runnable by design
# (`runner/sync.py rebootstrap`), and an unguarded `>>` would stack a duplicate block on every
# rerun — harmless-looking, but a .bashrc with four `cd` lines is how a reader stops trusting it.
if ! grep -q '# --- grx runner env' /home/ec2-user/.bashrc 2>/dev/null; then
  cat >> /home/ec2-user/.bashrc <<EOF
# --- grx runner env
export TMPDIR=/opt/grx/tmp
cd $REPO 2>/dev/null || true
alias grx='$REPO/.venv-oracle/bin/python -u'
export AWS_DEFAULT_REGION=$REGION
EOF
fi

date -u +%Y-%m-%dT%H:%M:%SZ > "$HOME_DIR/bootstrap.done"
echo "=== bootstrap complete"
