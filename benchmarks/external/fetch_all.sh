#!/usr/bin/env bash
# Materialise the EXT track: vendor repos + open datasets (DESIGN §25).
#
#   bash benchmarks/external/fetch_all.sh
#
# Reproduces exactly the artefacts pinned in acquisition/<ext_id>.yaml.
# vendor/ and data/ are gitignored; re-run this after a clean checkout.
#
# Environment:
#   HF_ENDPOINT   defaults to https://hf-mirror.com (huggingface.co is blocked
#                 on the build host; the mirror serves the same bytes/sha).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
PY="${PYTHON:-python3}"
if [[ "${1:-}" == "--public-collection" ]]; then
  shift
  cd "$HERE"
  exec "$PY" -m public_collection.collect fetch "$@"
fi
CURL=(curl -sSL --fail --retry 3 --retry-delay 2)

fetch_repo() { # ext_id owner/repo commit
  local eid="$1" slug="$2" sha="$3" dst="$HERE/$1/vendor"
  rm -rf "$dst"; mkdir -p "$dst"
  echo "[vendor] $eid $slug@${sha:0:10}"
  "${CURL[@]}" -o "/tmp/$eid.tgz" "https://codeload.github.com/$slug/tar.gz/$sha"
  tar xzf "/tmp/$eid.tgz" -C "$dst" --strip-components=1
  rm -f "/tmp/$eid.tgz"
}

# Only benchmarks BrachyBot can participate in are materialised (see manifest.yaml).
fetch_repo EXT-1 Luab/ABRA                              688814615dc368a66276798cb864fe9a587d7e6c
fetch_repo EXT-2 openai/simple-evals                    652c89d0ca9df547706735883097e9537d40dc47
fetch_repo EXT-3 AI4LIFE-GROUP/med-safety-bench         dc5d88e4c0100deada5a96f065a302959e6523a7
fetch_repo EXT-4 AQ-MedAI/MedMemoryBench                7227bc105b84a1a9f7a75861eb9e1be3ea502882
fetch_repo EXT-9 xiaowu0162/LongMemEval                  9e0b455f4ef0e2ab8f2e582289761153549043fc
fetch_repo EXT-10 MedHallu/MedHallu                      3c49c8ba80e47720333e508821967167ba048d49
fetch_repo EXT-11 ncbi-nlp/MedCalc-Bench                 20b10f9d66a8c3b0356ae3138533f5ec91666b6a
fetch_repo EXT-12 SamuelSchmidgall/AgentClinic           b6570edefb940857a7c334350656b29f9d984f24
fetch_repo EXT-13 DATEXIS/AMEGA-benchmark                16fd048a15818cc1e6f513647beec2f94f6a5ff7
fetch_repo EXT-14 udiram/MedPhysBench                    bde8dc6d29ad3fb324ea17f1c878f38477b6a868
fetch_repo EXT-15 gersteinlab/MedicalAgentsBench         fcb5292720c28f4168992ee37cda944e452cd098

# ---- EXT-1: generate the easy task tier from the vendored manifest ----
echo "[data] EXT-1 generate easy tasks"
mkdir -p "$HERE/EXT-1/data"
rm -rf "$HERE/EXT-1/data/tasks"
( cd "$HERE/EXT-1/vendor" && "$PY" scripts/generate_tasks.py \
    --difficulties easy medium hard --from-manifest data/studies/study_manifest.json \
    --tasks-dir "$HERE/EXT-1/data/tasks" >/dev/null )
# NOTE: 353 tasks generate offline (easy 249 + hard 104); the medium (SEG) tier
# needs the full TCIA DICOM download (see acquisition/EXT-1.yaml).

# ---- EXT-2: HealthBench jsonl (HF openai/healthbench) ----
echo "[data] EXT-2 HealthBench jsonl"
mkdir -p "$HERE/EXT-2/data"
for f in 2025-05-07-06-14-12_oss_eval.jsonl 2025-05-07-06-14-12_oss_meta_eval.jsonl \
         hard_2025-05-08-21-00-10.jsonl consensus_2025-05-09-20-00-46.jsonl; do
  "${CURL[@]}" -o "$HERE/EXT-2/data/$f" \
    "$HF_ENDPOINT/datasets/openai/healthbench/resolve/main/$f"
done

# ---- EXT-3: dataset ships in-repo ----
echo "[data] EXT-3 datasets (in-repo)"
rm -rf "$HERE/EXT-3/data"; mkdir -p "$HERE/EXT-3/data"
cp -r "$HERE/EXT-3/vendor/datasets" "$HERE/EXT-3/data/datasets"

# ---- EXT-4: MedMemoryBench parquet (HF Cyan27/MedMemoryBench, zh smoke subset) ----
echo "[data] EXT-4 MedMemoryBench full zh+en parquet"
mkdir -p "$HERE/EXT-4/data/zh" "$HERE/EXT-4/data/en"
for lang in zh en; do
  for f in personas dialogues dialogues_with_noise queries events trap_events clinical_reports; do
    "${CURL[@]}" -o "$HERE/EXT-4/data/$lang/$f.parquet" \
      "$HF_ENDPOINT/datasets/Cyan27/MedMemoryBench/resolve/main/data/$lang/$f.parquet"
  done
done
"${CURL[@]}" -o "$HERE/EXT-4/data/zh/noise_sessions.parquet" \
  "$HF_ENDPOINT/datasets/Cyan27/MedMemoryBench/resolve/main/data/zh/noise_sessions.parquet"

# ---- EXT-9: LongMemEval (HF longmemeval-cleaned) ----
echo "[data] EXT-9 LongMemEval"
mkdir -p "$HERE/EXT-9/data"
for f in longmemeval_oracle.json longmemeval_s_cleaned.json; do
  "${CURL[@]}" -o "$HERE/EXT-9/data/$f" \
    "$HF_ENDPOINT/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/$f"
done

# ---- EXT-10: MedHallu parquet ----
echo "[data] EXT-10 MedHallu parquet"
mkdir -p "$HERE/EXT-10/data"
"${CURL[@]}" -o "$HERE/EXT-10/data/train_labeled.parquet" \
  "$HF_ENDPOINT/datasets/UTAustin-AIHealth/MedHallu/resolve/main/pqa_labeled/train-00000-of-00001.parquet"
"${CURL[@]}" -o "$HERE/EXT-10/data/train_artificial.parquet" \
  "$HF_ENDPOINT/datasets/UTAustin-AIHealth/MedHallu/resolve/main/pqa_artificial/train-00000-of-00001.parquet"

# ---- EXT-11: MedCalc-Bench test csv ----
echo "[data] EXT-11 MedCalc-Bench"
mkdir -p "$HERE/EXT-11/data"
"${CURL[@]}" -o "$HERE/EXT-11/data/test_data_11_18_final.csv" \
  "$HF_ENDPOINT/datasets/ncbi/MedCalc-Bench/resolve/main/test_data_11_18_final.csv"

# ---- EXT-12: AgentClinic in-repo jsonl ----
echo "[data] EXT-12 AgentClinic (in-repo)"
rm -rf "$HERE/EXT-12/data"; mkdir -p "$HERE/EXT-12/data"
cp "$HERE/EXT-12/vendor/agentclinic_medqa.jsonl" "$HERE/EXT-12/vendor/agentclinic_medqa_extended.jsonl" \
   "$HERE/EXT-12/data/"

# ---- EXT-13: AMEGA in-repo csv ----
echo "[data] EXT-13 AMEGA (in-repo)"
rm -rf "$HERE/EXT-13/data"; mkdir -p "$HERE/EXT-13/data"
cp "$HERE/EXT-13/vendor/data/"{cases,questions,sections,criteria}.csv "$HERE/EXT-13/data/"

# ---- EXT-14: MedPhysBench in-repo public tasks ----
echo "[data] EXT-14 MedPhysBench (in-repo tasks)"
rm -rf "$HERE/EXT-14/data"; mkdir -p "$HERE/EXT-14/data/tasks"
cp -r "$HERE/EXT-14/vendor/tasks/public" "$HERE/EXT-14/data/tasks/public"

# ---- EXT-15: MedicalAgentsBench test parquet ----
echo "[data] EXT-15 MedicalAgentsBench parquet"
mkdir -p "$HERE/EXT-15/data"
for D in MedQA MedMCQA MedBullets MMLU-Pro MedExQA AfrimedQA MedXpertQA-R MedXpertQA-U PubMedQA; do
  "${CURL[@]}" -o "$HERE/EXT-15/data/$D.parquet" \
    "$HF_ENDPOINT/datasets/super-dainiu/MedicalAgentsBench/resolve/main/$D/test-00000-of-00001.parquet"
done

echo "done. now run: $PY $HERE/e0_smoke.py"
