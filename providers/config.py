import os
from dataclasses import dataclass
from enum import StrEnum


class SyncFailure(StrEnum):
    none = 'none'
    unavailable = '503'
    timeout = 'timeout'


class FailureType(StrEnum):
    technical = 'technical'
    moderation = 'moderation'
    payload = 'payload'


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class ProviderConfig:
    """Поведение фейкового провайдера задаётся env-переменными."""

    name: str
    failure_rate: float
    failure_type: FailureType
    sync_failure: SyncFailure
    duplicate_webhook: bool
    no_webhook: bool
    late_completed: bool
    webhook_base_url: str
    shared_secret: str
    webhook_delay_min: float = 2.0
    webhook_delay_max: float = 20.0

    @classmethod
    def from_env(cls) -> 'ProviderConfig':
        return cls(
            name=os.getenv('PROVIDER_NAME', 'alpha'),
            failure_rate=float(os.getenv('FAILURE_RATE', '0.0')),
            failure_type=FailureType(os.getenv('FAILURE_TYPE', 'technical')),
            sync_failure=SyncFailure(os.getenv('SYNC_FAILURE', 'none')),
            duplicate_webhook=_bool_env('DUPLICATE_WEBHOOK'),
            no_webhook=_bool_env('NO_WEBHOOK'),
            late_completed=_bool_env('LATE_COMPLETED'),
            webhook_base_url=os.getenv('WEBHOOK_BASE_URL', 'http://backend:8000'),
            shared_secret=os.getenv('PROVIDER_SHARED_SECRET', ''),
        )


config = ProviderConfig.from_env()
