import json
import re

TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def normalize_time(value: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    match = TIME_PATTERN.match(text)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def normalize_take_times(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        normalized = normalize_time(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    result.sort()
    return result


def parse_take_times(medication) -> list[str]:
    raw = getattr(medication, "take_times", None)
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, list):
            times = normalize_take_times([str(item) for item in parsed])
            if times:
                return times

    legacy = normalize_time(getattr(medication, "take_time", None) or "")
    return [legacy] if legacy else []


def serialize_take_times(times: list[str] | None) -> str | None:
    normalized = normalize_take_times(times)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)


def apply_take_times_to_medication(medication, take_times: list[str] | None, legacy_take_time: str | None = None):
    times = normalize_take_times(take_times)
    if not times and legacy_take_time:
        single = normalize_time(legacy_take_time)
        times = [single] if single else []
    medication.take_times = serialize_take_times(times)
    medication.take_time = times[0] if times else None


def to_medication_schema(medication) -> "schemas.Medication":
    from .. import schemas

    times = parse_take_times(medication)
    return schemas.Medication(
        id=medication.id,
        user_id=medication.user_id,
        name=medication.name,
        dosage=medication.dosage,
        frequency=medication.frequency,
        take_times=times,
        take_time=times[0] if times else medication.take_time,
        note=medication.note,
        created_at=medication.created_at,
    )
