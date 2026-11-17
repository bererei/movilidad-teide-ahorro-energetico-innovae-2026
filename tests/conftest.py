"""Estados históricos para probar transiciones sin depender de elecciones posteriores."""
from pathlib import Path
from copy import deepcopy
import json
import pytest

@pytest.fixture
def parametros_historicos():
    root=Path(__file__).resolve().parents[1]
    path=root/'tests/fixtures/parametros_edicion_base.json'
    return deepcopy(json.loads(path.read_text())['parametros'])
