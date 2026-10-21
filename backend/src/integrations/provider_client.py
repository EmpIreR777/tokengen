from typing import Any
from uuid import UUID

import httpx

from src.core.config import settings
from src.core.exceptions import ProviderUnavailableError
from src.models.model import ProviderEnum


class ProviderClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=settings.PROVIDER_TIMEOUT)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_provider_url(self, provider: ProviderEnum) -> str:
        if provider == ProviderEnum.alpha:
            return settings.PROVIDER_ALPHA_URL
        return settings.PROVIDER_BETA_URL

    async def send_task(
        self,
        provider: ProviderEnum,
        task_id: UUID,
        model_slug: str,
        prompt: str,
        ref_images: list[str],
    ) -> str:
        url = f'{self._get_provider_url(provider)}/tasks'
        payload = {
            'task_id': str(task_id),
            'model_slug': model_slug,
            'prompt': prompt,
            'ref_images': ref_images,
        }

        try:
            response = await self.client.post(url, json=payload)
            if response.status_code == 503:
                raise ProviderUnavailableError(f'Провайдер {provider.value} вернул 503')
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            external_id = data.get('external_id')
            if not external_id:
                raise ProviderUnavailableError(f'Провайдер {provider.value} не вернул external_id')
            return str(external_id)
        except httpx.TimeoutException as e:
            raise ProviderUnavailableError(f'Таймаут при запросе к провайдеру {provider.value}') from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                raise ProviderUnavailableError(f'Провайдер {provider.value} вернул {e.response.status_code}') from e
            raise


provider_client = ProviderClient()
