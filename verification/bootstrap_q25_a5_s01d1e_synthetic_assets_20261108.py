from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/q25_a5_s01d1e/p5_source_inputs.zip"
FIXTURE_SHA256 = "e4e2e90cf93aec2d34a7641a111e73bf1fe290bd7c8e406eb894c212c8297025"

SOURCE_INPUTS = {
    "20261008_options_daily.json": (
        "data/historical/krx_raw/20261008_options_daily.json",
        "e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9",
    ),
    "20261008_futures_daily.json": (
        "data/historical/krx_raw/20261008_futures_daily.json",
        "16cc2a913f7e7b02dfb5a82c859ff01e7ed028e005de76751047e3644af8d9ec",
    ),
    "2026.json": (
        "data/calendar/krx/2026.json",
        "5f4d04c3ab688180d9a10286513e5b4203cb4fe53ef13900df6e9599373a791e",
    ),
    "2027.json": (
        "data/calendar/krx/2027.json",
        "8109de96c59765476c4e4d91fda6ab0f3d44d1d2f25cfd4be56bd021848e771b",
    ),
    "2028.json": (
        "data/calendar/krx/2028.json",
        "9cdc1b50123fc64d69320126d492072a834ab4c6ad37583a1f6a652c85d10d30",
    ),
}

EXPECTED_INVENTORIES = {
    "q25_s05_3_s7_concurrent": "0823c2106d8d80c5014b78cfd14383bd54de07bb87e3c3b0e7dd72c353b27695",
    "q25_strategy7_8": "a68dc1af48aca37e0fedd85b7091971e2b506cd48fa0395f541270f287dceed0",
    "q25_strategy7_8_v2": "860150c6903857c25934ee62dd875d0cdf9fd70f1b5e8aea75c42056771739c3",
}

EXPECTED_PAYLOAD_INVENTORIES = {
    "p5": "95de3da749ef9e905e14e354395ff5dc7c11d130ecf7e7a83af8335413d116e8",
    "s8_normal": "f6d94b85d57b8b60119bca76c9f5bd10dd3809d2fa5d58598ed9d1b1de819d58",
    "s8_high_vol": "b94b8d565e1ab3632414d2951bee8b0b4f8017179d41a695c8e8ee7c93fd347b",
}

EXPECTED_CANONICAL_MANIFESTS = {
    "p5": "fe0de97f8cf4f0682757979ad1b49433340998d9fe88bc82768cd181b12641fe",
    "s8_normal": "5d9a9e1a245f93bee002abd213492aba7806df1d004af4f2b16bc2d136cc037d",
    "s8_high_vol": "1dad168eed339c8b0e4a9c33b88a2e8d469baa66913b2822c8ab7593a7df4a4a",
}

PROTECTED_PROFILES = (
    "config/validation_only/q25_strategy7_8_risk_profiles.v1.json",
    "config/validation_only/q25_s05_1_s7_v2/risk_profile.json",
    "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json",
    "config/validation_only/q25_s8_v3/normal/risk_profile.json",
    "config/validation_only/q25_s8_v3/high_vol/risk_profile.json",
    "config/validation_only/q25_s8_v3/expiry_settlement_profile_v1.json",
)

OUTPUT_DIRS = (
    "data/derived_scenario/p5_run_20261026_trend_up_seed20261026",
    "data/derived_scenario/q25_strategy7_8",
    "data/derived_scenario/q25_strategy7_8_v2",
    "data/derived_scenario/q25_s05_3_s7_concurrent",
    "data/derived_scenario/q25_s8_v3/strategy8_monthly/normal",
    "data/derived_scenario/q25_s8_v3/strategy8_monthly/high_vol",
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_module(relative_path: str, module_name: str) -> Any:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def inventory(path: Path) -> dict[str, Any]:
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if not files:
        raise RuntimeError(f"EMPTY_ASSET_DIRECTORY:{path}")
    lines = [
        f"{item.relative_to(path).as_posix()}|{item.stat().st_size}|{sha256_file(item)}"
        for item in files
    ]
    aggregate = sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "files": len(files),
        "bytes": sum(item.stat().st_size for item in files),
        "inventory_sha256": aggregate,
    }


def canonical_manifest_hash(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(canonical.encode("utf-8"))


def payload_inventory(path: Path) -> dict[str, Any]:
    files = sorted(
        item for item in path.rglob("*")
        if item.is_file() and item.name not in {"manifest.json", "manifest.json.sha256"}
    )
    if not files:
        raise RuntimeError(f"EMPTY_PAYLOAD_DIRECTORY:{path}")
    lines = [
        f"{item.relative_to(path).as_posix()}|{item.stat().st_size}|{sha256_file(item)}"
        for item in files
    ]
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "files": len(files),
        "bytes": sum(item.stat().st_size for item in files),
        "payload_inventory_sha256": sha256_bytes(("\n".join(lines) + "\n").encode("utf-8")),
    }


def snapshot_profiles() -> dict[str, str]:
    result = {}
    for relative in PROTECTED_PROFILES:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"PROTECTED_PROFILE_MISSING:{relative}")
        result[relative] = sha256_file(path)
    return result


def install_source_fixtures() -> dict[str, Any]:
    if not FIXTURE.is_file() or sha256_file(FIXTURE) != FIXTURE_SHA256:
        raise RuntimeError("P5_SOURCE_FIXTURE_ARCHIVE_HASH_MISMATCH")
    installed = {}
    with zipfile.ZipFile(FIXTURE, "r") as archive:
        names = set(archive.namelist())
        if names != set(SOURCE_INPUTS):
            raise RuntimeError(f"P5_SOURCE_FIXTURE_MEMBERS_MISMATCH:{sorted(names)}")
        for name, (relative, expected_sha) in SOURCE_INPUTS.items():
            raw = archive.read(name)
            actual_sha = sha256_bytes(raw)
            if actual_sha != expected_sha:
                raise RuntimeError(f"P5_SOURCE_FIXTURE_MEMBER_HASH_MISMATCH:{name}")
            destination = ROOT / relative
            if destination.exists():
                if sha256_file(destination) != expected_sha:
                    raise RuntimeError(f"REFUSE_TO_OVERWRITE_SOURCE_INPUT:{relative}")
                status = "REUSED_IDENTICAL"
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
                status = "INSTALLED_FROM_TEST_FIXTURE"
            installed[relative] = {
                "bytes": len(raw),
                "sha256": actual_sha,
                "status": status,
            }
    return installed


def verify_dataset(folder: Path, dataset_name: str, expected_rows: int | None = None) -> dict[str, Any]:
    manifest_path = folder / "manifest.json"
    dataset_path = folder / dataset_name
    if not manifest_path.is_file() or not dataset_path.is_file():
        raise RuntimeError(f"DATASET_OR_MANIFEST_MISSING:{folder}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha = sha256_file(dataset_path)
    expected_sha = manifest.get("dataset_sha256") or manifest.get("output_sha256")
    if actual_sha != expected_sha:
        raise RuntimeError(f"DATASET_HASH_MISMATCH:{dataset_path}")
    rows = sum(1 for line in dataset_path.open("r", encoding="utf-8") if line.strip())
    manifest_rows = manifest.get("rows", manifest.get("event_rows", manifest.get("events")))
    if expected_rows is not None and rows != expected_rows:
        raise RuntimeError(f"DATASET_ROW_COUNT_MISMATCH:{dataset_path}:{rows}")
    if manifest_rows is not None and rows != manifest_rows:
        raise RuntimeError(f"MANIFEST_ROW_COUNT_MISMATCH:{dataset_path}:{rows}:{manifest_rows}")
    if manifest.get("validation_only") is not True:
        raise RuntimeError(f"DATASET_NOT_VALIDATION_ONLY:{dataset_path}")
    if manifest.get("runtime_eligible", False) is not False:
        raise RuntimeError(f"DATASET_RUNTIME_ELIGIBLE_FLAG_INVALID:{dataset_path}")
    return {
        "dataset": dataset_path.relative_to(ROOT).as_posix(),
        "manifest": manifest_path.relative_to(ROOT).as_posix(),
        "rows": rows,
        "dataset_sha256": actual_sha,
        "manifest_sha256": sha256_file(manifest_path),
        "provenance": manifest.get("provenance", manifest.get("source_type")),
        "validation_only": manifest.get("validation_only"),
        "runtime_eligible": manifest.get("runtime_eligible", False),
    }


def main() -> None:
    sys.path.insert(0, str(ROOT))
    for relative in OUTPUT_DIRS:
        if (ROOT / relative).exists():
            raise RuntimeError(f"REFUSE_TO_OVERWRITE_EXISTING_DATASET:{relative}")

    profiles_before = snapshot_profiles()
    source_inputs = install_source_fixtures()

    report_dir = ROOT / "reports/synth"
    report_dir.mkdir(parents=True, exist_ok=True)
    generated_profiles: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="q25_s01d1e_profile_stage_", dir=report_dir) as temp:
        stage = Path(temp)

        # P5: the source fixture is installed at the exact paths declared by its manifest.
        from scripts.generate_synthetic_3m_p5 import generate_p5
        from scripts.validate_synthetic_3m_p5 import validate_dataset

        p5_dir = ROOT / OUTPUT_DIRS[0]
        p5_result = generate_p5(ROOT, p5_dir, "trend_up", 20261026)
        p5_manifest_sha = sha256_file(p5_dir / "manifest.json")
        (p5_dir / "manifest.json.sha256").write_text(
            f"{p5_manifest_sha}  manifest.json\n", encoding="ascii"
        )
        p5_validation = validate_dataset(ROOT, p5_dir)
        if p5_validation.get("status") != "PASS_WITH_LIMITATION":
            raise RuntimeError(f"P5_VALIDATION_NOT_ACCEPTED:{p5_validation}")

        # V1 generator: redirect its profile output away from tracked config.
        v1 = load_module(
            "verification/generate_q25_strategy7_8_synthetic_datasets_20261103.py",
            "q25_s01d1e_s7_s8_v1_generator",
        )
        v1.PROFILE = stage / "q25_strategy7_8_risk_profiles.v1.generated.json"
        v1.main()
        generated_profiles["q25_strategy7_8_v1"] = {
            "generated_sha256": sha256_file(v1.PROFILE),
            "tracked_sha256_before": profiles_before["config/validation_only/q25_strategy7_8_risk_profiles.v1.json"],
            "semantic_match": json.loads(v1.PROFILE.read_text(encoding="utf-8"))
            == json.loads((ROOT / "config/validation_only/q25_strategy7_8_risk_profiles.v1.json").read_text(encoding="utf-8")),
            "tracked_profile_modified": False,
        }

        # V2 generator writes only ignored data/derived_scenario outputs.
        v2 = load_module(
            "verification/generate_q25_strategy7_8_synthetic_datasets_v2_20261103.py",
            "q25_s01d1e_s7_s8_v2_generator",
        )
        v2.main()

        # S05_3 builder: preserve the tracked risk profile and report by redirecting both.
        s05 = load_module(
            "verification/build_q25_s05_3_s7_concurrent_dataset_20261107.py",
            "q25_s01d1e_s05_3_builder",
        )
        s05.OUT_PROFILE_DIR = stage / "s05_3_profile"
        s05.OUT_PROFILE = s05.OUT_PROFILE_DIR / "risk_profile.json"
        s05.REPORT = stage / "s05_3_report.json"
        s05.main()
        generated_profiles["q25_s05_3_s7_concurrent"] = {
            "generated_sha256": sha256_file(s05.OUT_PROFILE),
            "tracked_sha256_before": profiles_before["config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json"],
            "semantic_match": json.loads(s05.OUT_PROFILE.read_text(encoding="utf-8"))
            == json.loads((ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json").read_text(encoding="utf-8")),
            "tracked_profile_modified": False,
        }

        # S8 V3 builder: redirect only profile output; keep dataset/manifest at expected paths.
        s8 = load_module(
            "verification/generate_q25_s8_scenario_v3_20261104.py",
            "q25_s01d1e_s8_v3_generator",
        )
        s8.RISK_BASE = stage / "s8_profiles"
        s8.build_scenario("HIGH_VOL")
        s8.build_scenario("NORMAL")
        generated_profiles["q25_s8_v3"] = {
            "normal_generated_sha256": sha256_file(s8.RISK_BASE / "normal/risk_profile.json"),
            "high_vol_generated_sha256": sha256_file(s8.RISK_BASE / "high_vol/risk_profile.json"),
            "normal_tracked_sha256_before": profiles_before["config/validation_only/q25_s8_v3/normal/risk_profile.json"],
            "high_vol_tracked_sha256_before": profiles_before["config/validation_only/q25_s8_v3/high_vol/risk_profile.json"],
            "normal_semantic_match": json.loads((s8.RISK_BASE / "normal/risk_profile.json").read_text(encoding="utf-8"))
            == json.loads((ROOT / "config/validation_only/q25_s8_v3/normal/risk_profile.json").read_text(encoding="utf-8")),
            "high_vol_semantic_match": json.loads((s8.RISK_BASE / "high_vol/risk_profile.json").read_text(encoding="utf-8"))
            == json.loads((ROOT / "config/validation_only/q25_s8_v3/high_vol/risk_profile.json").read_text(encoding="utf-8")),
            "tracked_profiles_modified": False,
        }

    assets = []
    assets.append(verify_dataset(
        ROOT / "data/derived_scenario/q25_strategy7_8/strategy7_weekly",
        "20261103.jsonl", 20,
    ))
    assets.append(verify_dataset(
        ROOT / "data/derived_scenario/q25_strategy7_8/strategy8_monthly",
        "20261103.jsonl", 20,
    ))
    assets.append(verify_dataset(
        ROOT / "data/derived_scenario/q25_strategy7_8_v2/strategy7_weekly",
        "20261103.jsonl", 216,
    ))
    assets.append(verify_dataset(
        ROOT / "data/derived_scenario/q25_strategy7_8_v2/strategy8_monthly",
        "20261103.jsonl", 432,
    ))
    assets.append(verify_dataset(
        ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent",
        "20261103.jsonl", 216,
    ))
    assets.append(verify_dataset(
        ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly/normal",
        "20261104.jsonl", 216,
    ))
    assets.append(verify_dataset(
        ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly/high_vol",
        "20261104.jsonl", 216,
    ))

    p5_dir = ROOT / OUTPUT_DIRS[0]
    p5_manifest_path = p5_dir / "manifest.json"
    p5_sidecar = (p5_dir / "manifest.json.sha256").read_text(encoding="ascii").split()[0]
    if p5_sidecar != sha256_file(p5_manifest_path):
        raise RuntimeError("P5_MANIFEST_SIDECAR_HASH_MISMATCH")
    p5_payload = payload_inventory(p5_dir)
    p5_canonical_manifest = canonical_manifest_hash(p5_manifest_path)
    if p5_payload["payload_inventory_sha256"] != EXPECTED_PAYLOAD_INVENTORIES["p5"]:
        raise RuntimeError(f"P5_ORIGINAL_PAYLOAD_MISMATCH:{p5_payload['payload_inventory_sha256']}")
    if p5_canonical_manifest != EXPECTED_CANONICAL_MANIFESTS["p5"]:
        raise RuntimeError(f"P5_CANONICAL_MANIFEST_MISMATCH:{p5_canonical_manifest}")
    p5_payload["canonical_manifest_sha256"] = p5_canonical_manifest
    p5_payload["manifest_sha256"] = sha256_file(p5_manifest_path)
    p5_payload["manifest_output_files_checked"] = len(p5_result.get("output_files", []))
    p5_payload["validator"] = p5_validation
    assets.append(p5_payload)

    inventory_results = {}
    for name, relative in {
        "q25_strategy7_8": "data/derived_scenario/q25_strategy7_8",
        "q25_strategy7_8_v2": "data/derived_scenario/q25_strategy7_8_v2",
        "q25_s05_3_s7_concurrent": "data/derived_scenario/q25_s05_3_s7_concurrent",
    }.items():
        result = inventory(ROOT / relative)
        result["expected_original_inventory_sha256"] = EXPECTED_INVENTORIES[name]
        result["matches_original_inventory"] = result["inventory_sha256"] == EXPECTED_INVENTORIES[name]
        if not result["matches_original_inventory"]:
            raise RuntimeError(f"ORIGINAL_ASSET_INVENTORY_MISMATCH:{name}:{result['inventory_sha256']}")
        inventory_results[name] = result

    for name, relative in {
        "s8_normal": "data/derived_scenario/q25_s8_v3/strategy8_monthly/normal",
        "s8_high_vol": "data/derived_scenario/q25_s8_v3/strategy8_monthly/high_vol",
    }.items():
        result = payload_inventory(ROOT / relative)
        manifest_path = ROOT / relative / "manifest.json"
        canonical_sha = canonical_manifest_hash(manifest_path)
        result["expected_payload_inventory_sha256"] = EXPECTED_PAYLOAD_INVENTORIES[name]
        result["canonical_manifest_sha256"] = canonical_sha
        result["expected_canonical_manifest_sha256"] = EXPECTED_CANONICAL_MANIFESTS[name]
        result["manifest_sha256"] = sha256_file(manifest_path)
        result["matches_original_payload"] = result["payload_inventory_sha256"] == EXPECTED_PAYLOAD_INVENTORIES[name]
        result["matches_original_manifest_semantics"] = canonical_sha == EXPECTED_CANONICAL_MANIFESTS[name]
        if not result["matches_original_payload"] or not result["matches_original_manifest_semantics"]:
            raise RuntimeError(f"S8_ORIGINAL_ASSET_MISMATCH:{name}:{result}")
        inventory_results[name] = result

    profiles_after = snapshot_profiles()
    if profiles_after != profiles_before:
        raise RuntimeError("TRACKED_VALIDATION_PROFILE_CHANGED_DURING_BOOTSTRAP")

    report = {
        "report_id": "Q25_A5_S01D1E_SYNTHETIC_ASSET_BOOTSTRAP_20261108",
        "verdict": "ASSETS_RESTORED_AND_SHA_VERIFIED",
        "validation_only": True,
        "production_runtime_eligible": False,
        "source_fixture_archive": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "bytes": FIXTURE.stat().st_size,
            "sha256": sha256_file(FIXTURE),
        },
        "source_inputs": source_inputs,
        "assets": assets,
        "inventory_results": inventory_results,
        "generated_profiles_staged_not_published": generated_profiles,
        "protected_profile_hashes_before": profiles_before,
        "protected_profile_hashes_after": profiles_after,
        "kis_api_called": False,
        "live_api_called": False,
        "real_account_or_orders_used": False,
        "original_data_modified": False,
        "tracked_profile_modified": False,
    }
    report_path = report_dir / "Q25_A5_S01D1E_SYNTHETIC_ASSET_BOOTSTRAP_20261108.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_sha = sha256_file(report_path)
    report_path.with_suffix(report_path.suffix + ".sha256").write_text(
        f"{report_sha}  {report_path.name}\n", encoding="ascii"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
