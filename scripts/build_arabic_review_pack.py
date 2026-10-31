"""Build/check a deterministic offline MSA/Darja human-review package.

This copies existing exact-version editorial proposals into review worksheets. It
does not import content into Django, approve material, or create audio.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK_ID = "ar-initial-review-20261101"
OUT = ROOT / "content" / "review_packs" / PACK_ID
SOURCES = (
    ("docs/arabic-library-v1.json",
     "737e95b4f21616a235d8e4f2a4bdc5e0eed87210f01ef74e9948dca6de0655a2",
     "ar-msa-pilot", 1, 42, "original_editorial_drafts_not_approved"),
    ("docs/arabic-library-v2.json",
     "95e56145590072134f648dea416848305d9a3803638c062725149a245ad6bf96",
     "ar-dz-pilot", 2, 32, "draft_metadata_rebinding_pending_clinical_linguistic_review"),
)
REVIEW_FIELDS = (
    "linguist_reviewer_code", "linguist_review_date", "region_or_register_confirmed",
    "word_a_meaning_and_variants", "word_b_meaning_and_variants",
    "speech_form_a_ipa_or_transcription", "speech_form_b_ipa_or_transcription",
    "contrast_valid_for_stated_variety", "dialect_variants_not_errors_notes",
    "image_a_recognition_and_ambiguity", "image_b_recognition_and_ambiguity",
    "family_familiarity_evidence_ref", "clinical_reviewer_code", "clinical_review_date",
    "profile_and_target_fit", "task_objective_and_limits_review",
    "adult_audio_asset_a_and_sha256", "adult_audio_asset_b_and_sha256",
    "speaker_permission_evidence_ref", "rights_review_code_and_date",
    "decision", "decision_reason", "exact_cms_fingerprint_after_import",
    "availability_decision_ref", "release_scope",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return digest(text.encode("utf-8"))


def load_candidates():
    legacy = json.loads((ROOT / SOURCES[0][0]).read_text(encoding="utf-8"))
    predecessors = {
        item["series"]: item["version"]
        for item in legacy["activities"] if item.get("variety_code") == "ar-dz-pilot"
    }
    candidates = []
    source_records = {}
    for path, expected_sha, variety, version, count, expected_status in SOURCES:
        source_path = ROOT / path
        raw = source_path.read_bytes()
        actual_sha = digest(raw)
        if actual_sha != expected_sha:
            raise ValueError(f"Source changed; create a new review-pack version: {path}")
        document = json.loads(raw.decode("utf-8"))
        if document.get("status") != expected_status:
            raise ValueError(f"Unexpected source status: {path}")
        items = [a for a in document["activities"] if a.get("variety_code") == variety]
        if len(items) != count or len({a["series"] for a in items}) != count:
            raise ValueError(f"Unexpected count or duplicate series in {path}")
        for item in items:
            if (item.get("version") != version or item.get("state") != "draft"
                    or item.get("is_demo") is not False):
                raise ValueError(f"Unexpected lifecycle state: {item.get('series')}")
            if any(item.get(field) for field in ("audio_a", "audio_b")):
                raise ValueError(f"Audio appeared; review-pack version required: {item['series']}")
            candidates.append((item, path, expected_sha, variety, version))
        source_records[path] = {
            "sha256": actual_sha, "variety": variety, "version": version,
            "status": expected_status, "included_rows": len(items),
        }
    if len(candidates) != 74:
        raise ValueError(f"Expected 74 current-version rows, found {len(candidates)}")
    return candidates, source_records, predecessors


def rows_for_pack(candidates, predecessors):
    candidate_rows = []
    image_uses = Counter()
    recording_sources = defaultdict(list)
    for item, source_file, source_sha, variety, version in candidates:
        metadata = item.get("item_metadata") or {}
        side_a, side_b = metadata.get("a") or {}, metadata.get("b") or {}
        fa, fb = side_a.get("familiarity") or {}, side_b.get("familiarity") or {}
        image_a, image_b = item.get("image_a", ""), item.get("image_b", "")
        for ref in (image_a, image_b):
            if ref:
                image_uses[ref] += 1
        record = {
            "pack_id": PACK_ID, "variety_code": variety,
            "scope_label": ("MSA; confirm actual exposure/register" if variety == "ar-msa-pilot"
                            else "Algerian Darja proposal; local region must be specified"),
            "source_file": source_file, "source_sha256": source_sha,
            "source_record_sha256": canonical_digest(item),
            "series_uuid": item["series"], "version": version,
            "supersedes_version": predecessors.get(item["series"], ""),
            "title": item.get("title", ""), "activity_kind": item.get("kind", ""),
            "requested_target_working_copy": item.get("requested_target", ""),
            "contrast_claim_working_copy": item.get("contrast", ""),
            "word_a": item.get("word_a", ""),
            "meaning_a_working_copy_unapproved": side_a.get("meaning", ""),
            "segments_a_working_copy_unapproved": " ".join(side_a.get("segments", [])),
            "target_occurrences_a_working_copy_unapproved": json.dumps(
                side_a.get("target_occurrences", []), ensure_ascii=False, separators=(",", ":")),
            "image_a_static_reference": image_a, "audio_a_present": bool(item.get("audio_a")),
            "transcription_a_present": bool(item.get("transcription_a")),
            "transcription_a_working_copy_unapproved": item.get("transcription_a", ""),
            "familiarity_a_source_status": fa.get("status", "not supplied"),
            "word_b": item.get("word_b", ""),
            "meaning_b_working_copy_unapproved": side_b.get("meaning", ""),
            "segments_b_working_copy_unapproved": " ".join(side_b.get("segments", [])),
            "target_occurrences_b_working_copy_unapproved": json.dumps(
                side_b.get("target_occurrences", []), ensure_ascii=False, separators=(",", ":")),
            "image_b_static_reference": image_b, "audio_b_present": bool(item.get("audio_b")),
            "transcription_b_present": bool(item.get("transcription_b")),
            "transcription_b_working_copy_unapproved": item.get("transcription_b", ""),
            "familiarity_b_source_status": fb.get("status", "not supplied"),
            "editorial_status_in_source": item.get("state", ""),
            "rights_status_in_source": item.get("rights", "unknown"),
        }
        record.update({field: "" for field in REVIEW_FIELDS})
        candidate_rows.append(record)
        for side, word, meaning in (
            ("a", record["word_a"], record["meaning_a_working_copy_unapproved"]),
            ("b", record["word_b"], record["meaning_b_working_copy_unapproved"]),
        ):
            recording_sources[(variety, word, meaning)].append(f"{item['series']}:{version}:{side}")

    recording_rows = []
    for (variety, word, meaning), source_ids in sorted(recording_sources.items()):
        rid = digest(f"{variety}\0{word}\0{meaning}".encode("utf-8"))[:16]
        recording_rows.append({
            "recording_item_id": f"{variety}-{rid}", "variety_code": variety,
            "regional_scope_required": (
                "Specify local region/community; no country-wide Darja norm is implied."
                if variety == "ar-dz-pilot"
                else "Specify MSA register and the child's real exposure; do not substitute for home Darja."
            ),
            "word_as_written_in_proposal": word,
            "meaning_as_written_in_proposal_unverified": meaning,
            "source_activity_sides": ";".join(sorted(source_ids)),
            "exact_spoken_form_after_reviewer_decision": "", "reviewed_transcription_ipa": "",
            "adult_speaker_code": "", "adult_speaker_competence_evidence_ref": "",
            "adult_recording_permission_ref": "", "rights_or_license_ref": "",
            "recording_path": "", "recording_sha256": "", "recording_date": "",
            "linguistic_reviewer_code_and_date": "", "clinical_reviewer_code_and_date": "",
            "status": "blocked_pending_linguistic_clinical_rights_and_release_review",
        })

    asset_rows = []
    for reference, uses in sorted(image_uses.items()):
        path = ROOT / "static" / reference
        if not path.is_file():
            raise ValueError(f"Missing referenced SVG: {reference}")
        raw = path.read_bytes()
        asset_rows.append({
            "static_reference": reference, "sha256": digest(raw), "size_bytes": len(raw),
            "candidate_side_uses": uses, "visual_review_code_and_date": "",
            "meaning_and_local_familiarity_evidence_ref": "",
            "rights_status_and_evidence_ref": "", "decision": "",
        })

    references = {}
    for item, _path, _sha, _variety, _version in candidates:
        for source in item.get("evidence_sources", []):
            key = (source.get("title", ""), source.get("url", ""), source.get("scope", ""))
            references.setdefault(key, set()).add(item["series"] + ":" + str(item["version"]))
    evidence_rows = []
    for (title, url, scope), activity_ids in sorted(references.items()):
        evidence_rows.append({
            "title_as_supplied_by_source": title, "url_as_supplied_by_source": url,
            "scope_limit_as_supplied_by_source": scope, "candidate_activity_count": len(activity_ids),
            "reviewer_checked_exact_source_and_claim": "",
            "source_claim_scope_accepted_or_corrected": "", "reviewer_code_and_date": "", "notes": "",
        })
    return candidate_rows, recording_rows, asset_rows, evidence_rows


def csv_bytes(rows):
    if not rows:
        raise ValueError("Refusing to generate an empty reviewer worksheet")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def build():
    candidates, sources, predecessors = load_candidates()
    candidate_rows, recordings, assets, evidence = rows_for_pack(candidates, predecessors)
    variety_counts = Counter(row["variety_code"] for row in candidate_rows)
    kind_counts = Counter((row["variety_code"], row["activity_kind"]) for row in candidate_rows)
    if variety_counts != Counter({"ar-msa-pilot": 42, "ar-dz-pilot": 32}):
        raise ValueError(f"Unexpected variety counts: {variety_counts}")
    if sum(row["activity_kind"] == "phonological_contrast" for row in candidate_rows) != 10:
        raise ValueError("Expected ten MSA contrast proposals; inspect and version any change")
    transcription_sides = sum(bool(row["transcription_a_present"]) + bool(row["transcription_b_present"]) for row in candidate_rows)
    if transcription_sides != 20:
        raise ValueError(f"Expected 20 unapproved MSA transcription proposals; found {transcription_sides}")
    if any(row["activity_kind"] == "phonological_contrast" and row["variety_code"] == "ar-dz-pilot"
           for row in candidate_rows):
        raise ValueError("Darja must not inherit an MSA contrast label")
    files = {
        "candidates_for_review.csv": csv_bytes(candidate_rows),
        "recording_queue.csv": csv_bytes(recordings),
        "image_assets_for_review.csv": csv_bytes(assets),
        "evidence_sources_for_review.csv": csv_bytes(evidence),
    }
    readme_path = OUT / "README.md"
    if not readme_path.is_file():
        raise ValueError("Write the reviewer README before generating the manifest")
    files["README.md"] = readme_path.read_bytes()
    manifest = {
        "pack_id": PACK_ID, "prepared_on": "2026-11-01",
        "status": "review_preparation_only_not_approved",
        "purpose": "Prepare existing MSA and Algerian Darja proposals for separately scoped human linguistic, clinical, familiarity, media-rights, and release review.",
        "no_database_import": True, "source_files": sources,
        "current_versions_in_scope": {
            "ar-msa-pilot": {"count": 42, "source_file": "docs/arabic-library-v1.json", "version": 1},
            "ar-dz-pilot": {"count": 32, "source_file": "docs/arabic-library-v2.json",
                            "version": 2, "supersedes_same_series_version": 1},
        },
        "observed_source_facts_not_approvals": {
            "candidate_rows": 74,
            "kind_counts": {f"{variety}:{kind}": count for (variety, kind), count in sorted(kind_counts.items())},
            "phonological_contrast_kind_rows": 10, "phonological_contrast_rows_in_darja": 0,
            "exact_source_audio_references_present": sum(bool(row["audio_a_present"]) + bool(row["audio_b_present"]) for row in candidate_rows),
            "exact_source_transcriptions_present": sum(bool(row["transcription_a_present"]) + bool(row["transcription_b_present"]) for row in candidate_rows),
            "image_assets_referenced": len(assets),
        },
        "files": {name: {"sha256": digest(data), "size_bytes": len(data)}
                  for name, data in sorted(files.items())},
        "limits": [
            "Meanings, contrast labels, segment lists, evidence citations, and image links are unapproved editorial inputs.",
            "Sources support professional/language frameworks or lexical attestations; none validates Nehedrou or its outcomes.",
            "No Darja minimal-pair claim is introduced. Ten MSA contrast entries require individual linguistic and clinical review.",
            "Source JSON hashes are not Django activity fingerprints; re-check exact imported versions in CMS before any decision.",
            "No audio, child observations, approval, rights clearance, availability decision, or family assignment is created.",
        ],
    }
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write", action="store_true", help="write deterministic worksheets and manifest")
    actions.add_argument("--check", action="store_true", help="verify exact source hashes and generated output")
    args = parser.parse_args()
    expected = build()
    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for name, data in expected.items():
            (OUT / name).write_bytes(data)
        print(f"Wrote {len(expected)} files to {OUT}")
        return 0
    mismatches = [name for name, data in expected.items()
                  if not (OUT / name).is_file() or (OUT / name).read_bytes() != data]
    if mismatches:
        print("Review pack mismatch: " + ", ".join(mismatches))
        return 1
    print(f"Verified {len(expected)} files: 74 current-version candidates and exact source hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
