# datafeed_tester/utils_sanitize.py
import math

def sanitize_numbers(obj):
    """
    Remplace NaN / +Inf / -Inf par None pour que le JSON soit valide.
    Fonctionne récursivement (dict, list). Les autres types sont renvoyés tels quels.
    """
    if isinstance(obj, dict):
        return {k: sanitize_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_numbers(x) for x in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if obj is None:
        return None
    return obj
