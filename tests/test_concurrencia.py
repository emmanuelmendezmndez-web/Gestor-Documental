"""Pruebas de concurrencia en un proceso y base ficticios."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ConcurrenciaAisladaTest(unittest.TestCase):
    def test_operaciones_documentales(self):
        raiz = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="siged-prueba-concurrencia-") as carpeta:
            entorno = os.environ.copy()
            entorno.update(GESTOR_DATA_DIR=carpeta, GESTOR_SECRET_KEY="clave-ficticia-concurrencia-1234567890", PYTHONPATH=str(raiz))
            subprocess.run([sys.executable, str(raiz / "tests" / "concurrencia_casos.py")], cwd=raiz, env=entorno, check=True, timeout=180)
