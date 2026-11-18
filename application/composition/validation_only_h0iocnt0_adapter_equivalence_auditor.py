from __future__ import annotations
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

FIELD_MAP = {
    'shrn_iscd': 0,
    'observed_hour': 1,
    'last_price': 2,
    'volume': 10,
    'ask_price': 41,
    'bid_price': 42,
    'implied_volatility': 33,
}


def _expected(field: str, values: list[str]) -> Any:
    raw = values[FIELD_MAP[field]].strip()
    if field == 'shrn_iscd' or field == 'observed_hour':
        return raw
    if field == 'implied_volatility' and not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f'H0IOCNT0_EXPECTED_FIELD_INVALID:{field}') from exc


def audit_adapter_frame(payload: str, adapted_records: Sequence[Any], *, source: str) -> dict[str, Any]:
    parts = payload.split('|', 3)
    if len(parts) != 4 or parts[0] not in {'0', '1'} or parts[1] != 'H0IOCNT0':
        raise ValueError('H0IOCNT0_ENVELOPE_INVALID')
    try:
        declared = int(parts[2])
    except ValueError as exc:
        raise ValueError('H0IOCNT0_DECLARED_COUNT_INVALID') from exc
    fields = parts[3].split('^')
    if declared <= 0 or len(fields) != declared * 58:
        raise ValueError('H0IOCNT0_58_FIELD_LAYOUT_INVALID')
    if len(adapted_records) != declared:
        raise ValueError('H0IOCNT0_ADAPTER_RECORD_COUNT_MISMATCH')
    counts = {'frames': 1, 'raw_records': declared, 'adapter_records': len(adapted_records), 'source_mismatches': 0}
    for field in FIELD_MAP:
        counts[f'{field}_comparisons'] = 0
        counts[f'{field}_mismatches'] = 0
    samples = []
    for index, adapted in enumerate(adapted_records):
        raw_fields = fields[index * 58:(index + 1) * 58]
        for field in FIELD_MAP:
            expected = _expected(field, raw_fields)
            actual = getattr(adapted, field)
            counts[f'{field}_comparisons'] += 1
            if actual != expected:
                counts[f'{field}_mismatches'] += 1
                if len(samples) < 10:
                    samples.append({'record_index': index, 'field': field, 'expected': str(expected), 'actual': str(actual)})
        if getattr(adapted, 'source', None) != source:
            counts['source_mismatches'] += 1
    counts['mismatch_samples'] = samples
    return counts
