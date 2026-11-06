"""Match Bluetooth audio endpoints to the selected phone using Windows identities, never the phone's name."""
import uuid


def _container(value):
    try:
        parsed = uuid.UUID(value) if isinstance(value, str) else None
        return str(parsed) if parsed and parsed.int else None
    except ValueError:
        return None


def _strings(value):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OSError("Windows returned invalid Bluetooth audio metadata. Run setup.ps1 to update the phone helper.")
    return value


def blocking_devices(snapshot):
    """Names of other hands-free devices that can interfere with the chosen phone's laptop audio."""
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise OSError("The phone helper needs an update. Quit Pat and run setup.ps1.")
    phone = snapshot.get("phone")
    if phone is not None and not isinstance(phone, dict):
        raise OSError("Windows returned invalid phone identity metadata.")
    phone = phone or {}
    phone_container = _container(phone.get("container_id"))
    instance = phone.get("instance_id") or ""
    if not isinstance(instance, str):
        raise OSError("Windows returned invalid phone identity metadata.")
    phone_instance = instance.casefold()
    endpoints = snapshot.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) > 1024:
        raise OSError("Windows returned invalid Bluetooth audio metadata.")
    found, seen = [], set()
    for endpoint in endpoints:
        if not isinstance(endpoint, dict) or not isinstance(endpoint.get("name"), str):
            raise OSError("Windows returned invalid Bluetooth audio metadata.")
        services = _strings(endpoint.get("services", []))
        parents = _strings(endpoint.get("instance_ids", []))
        name = endpoint["name"].strip()
        # Driver service metadata handles localized or renamed endpoints. The label is only a legacy HFP hint.
        hands_free = any(service.casefold().startswith("bthhf") for service in services) or "hands-free" in name.casefold()
        if not hands_free:
            continue
        container = _container(endpoint.get("container_id"))
        same_container = phone_container is not None and container == phone_container
        same_instance = bool(phone_instance) and any(parent.casefold() == phone_instance for parent in parents)
        if same_container or same_instance:
            continue
        key = container or endpoint.get("id") or name.casefold()
        if not isinstance(key, str):
            raise OSError("Windows returned invalid Bluetooth audio metadata.")
        if key not in seen:
            found.append(name or "Another Bluetooth hands-free device")
            seen.add(key)
    return found
