"""KRX Data Marketplace downloaded derivative instrument master reader."""
from __future__ import annotations
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
from contracts.futures_contract_master import KisFuturesContractIdentity
from contracts.futures_contract_spec import FuturesProductType, KRXFuturesContractSpecSource
from core.option.option_master import KisOptionContractIdentity
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
class KRXMarketplaceMasterError(ValueError):
    pass
@dataclass(frozen=True)
class KRXMarketplaceOptionMaster:
    identities: dict[str, KisOptionContractIdentity]
    source_files: tuple[str, ...]
    def get_contract_identity(self, krx_isu_cd: str) -> KisOptionContractIdentity | None:
        return self.identities.get(krx_isu_cd.strip())
@dataclass(frozen=True)
class KRXMarketplaceFuturesMaster:
    identities: dict[str, KisFuturesContractIdentity]
    source_files: tuple[str, ...]
    def get_contract_identity(self, krx_isu_cd: str) -> KisFuturesContractIdentity | None:
        return self.identities.get(krx_isu_cd.strip())
def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(_NS + "t")) for si in root.findall(_NS + "si")]

def _sheet_rows(path: Path) -> list[list[str]]:
    try:
        with zipfile.ZipFile(path) as z:
            shared = _shared_strings(z)
            workbook = ET.fromstring(z.read("xl/workbook.xml"))
            sheet = workbook.find(_NS + "sheets")[0]
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            relmap = {x.attrib["Id"]: x.attrib["Target"] for x in rels}
            target = "xl/" + relmap[sheet.attrib[_REL_NS + "id"]].lstrip("/")
            root = ET.fromstring(z.read(target))
    except (OSError, KeyError, ET.ParseError) as exc:
        raise KRXMarketplaceMasterError(f"INVALID_XLSX:{path}") from exc
    rows = []
    for row in root.findall(".//" + _NS + "sheetData/" + _NS + "row"):
        values = []
        for cell in row.findall(_NS + "c"):
            value = cell.find(_NS + "v")
            raw = "" if value is None else value.text or ""
            if cell.attrib.get("t") == "s" and raw:
                raw = shared[int(raw)]
            values.append(raw.strip())
        rows.append(values)
    if not rows:
        raise KRXMarketplaceMasterError(f"EMPTY_XLSX:{path}")
    return rows

def _date(raw: str) -> str:
    try:
        return datetime.strptime(raw.strip(), "%Y/%m/%d").date().isoformat()
    except ValueError as exc:
        raise KRXMarketplaceMasterError(f"INVALID_DATE:{raw}") from exc

def _decimal(raw: str, field: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError) as exc:
        raise KRXMarketplaceMasterError(f"INVALID_{field}:{raw}") from exc
    if value <= 0:
        raise KRXMarketplaceMasterError(f"INVALID_{field}:{raw}")
    return value
def load_option_master(paths: Iterable[str | Path]) -> KRXMarketplaceOptionMaster:
    identities = {}
    sources = []
    for raw_path in paths:
        path = Path(raw_path); rows = _sheet_rows(path); sources.append(path.name)
        for row in rows[1:]:
            if len(row) < 12 or not row[1]:
                continue
            stnd_iscd, shrn_iscd = row[0], row[1]
            english_name = row[3]
            option_type = "CALL" if english_name.startswith("C ") else "PUT" if english_name.startswith("P ") else None
            if option_type is None:
                raise KRXMarketplaceMasterError(f"OPTION_TYPE_UNRESOLVED:{shrn_iscd}")
            identity = KisOptionContractIdentity(shrn_iscd=shrn_iscd, stnd_iscd=stnd_iscd or None,
                expiry=_date(row[6]), option_type=option_type, strike=_decimal(row[11], "STRIKE"),
                info_type="KRX_MARKETPLACE", contract_multiplier=_decimal(row[9], "CONTRACT_MULTIPLIER"))
            existing = identities.get(shrn_iscd)
            if existing is not None and existing != identity:
                raise KRXMarketplaceMasterError(f"CONFLICTING_OPTION_IDENTITY:{shrn_iscd}")
            identities[shrn_iscd] = identity
    if not identities:
        raise KRXMarketplaceMasterError("NO_OPTION_IDENTITIES")
    return KRXMarketplaceOptionMaster(identities, tuple(sources))

def load_futures_master(paths: Iterable[str | Path], product_type: FuturesProductType) -> KRXMarketplaceFuturesMaster:
    identities = {}; sources = []; spec = KRXFuturesContractSpecSource.get(product_type)
    for raw_path in paths:
        path = Path(raw_path); rows = _sheet_rows(path); sources.append(path.name)
        for row in rows[1:]:
            if len(row) < 10 or not row[1]:
                continue
            identity = KisFuturesContractIdentity(shrn_iscd=row[1], stnd_iscd=row[0] or None,
                info_type="KRX_MARKETPLACE", mmsc_cls_code="", unas_shrn_iscd=None,
                unas_kor_name="KOSPI200", kor_name=row[2] or None, product_type=product_type,
                contract_multiplier=_decimal(row[9], "CONTRACT_MULTIPLIER"),
                identity_source=f"KRX_MARKETPLACE:{path.name};{spec.source}")
            existing = identities.get(identity.shrn_iscd)
            if existing is not None and existing != identity:
                raise KRXMarketplaceMasterError(f"CONFLICTING_FUTURES_IDENTITY:{identity.shrn_iscd}")
            identities[identity.shrn_iscd] = identity
    if not identities:
        raise KRXMarketplaceMasterError("NO_FUTURES_IDENTITIES")
    return KRXMarketplaceFuturesMaster(identities, tuple(sources))
