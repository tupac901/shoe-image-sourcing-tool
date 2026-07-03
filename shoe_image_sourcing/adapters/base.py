from abc import ABC, abstractmethod

from shoe_image_sourcing.models import ImageCandidate


class PlatformAdapter(ABC):
    platform: str

    @abstractmethod
    async def search(self, query: str, limit: int = 12) -> list[ImageCandidate]:
        raise NotImplementedError
