"""Ejecuta los casos v2 sin importar módulos de datos en el proceso principal."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RegistroV2AisladoTest(unittest.TestCase):
    def test_esquema_e_inventarios(self):
        raiz = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="siged-prueba-registro-v2-") as temporal:
            env = os.environ.copy()
            env.update(GESTOR_DATA_DIR=temporal, PYTHONPATH=str(raiz))
            subprocess.run([sys.executable, str(raiz / "tests" / "registro_v2_casos.py")],
                           env=env, cwd=raiz, check=True, timeout=900)
