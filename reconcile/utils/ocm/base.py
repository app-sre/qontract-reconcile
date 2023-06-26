from typing import Optional

from pydantic import BaseModel


class OCMModelLink(BaseModel):
    kind: Optional[str] = None
    id: str
    href: Optional[str] = None
