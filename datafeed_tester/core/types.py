# core/types.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any
import pandas as pd

class BaseStrategy(ABC):
    """
    Interface minimale pour les stratégies.
    Doit retourner un DataFrame aligné temporellement avec au moins:
      - 'side' in {'long','flat','short'} et/ou
      - 'size' float in [0..1]
    """
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        ...

    def name(self) -> str:
        return self.__class__.__name__

