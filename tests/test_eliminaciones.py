"""Ejecuta pruebas de integridad en un proceso con datos aislados."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EliminacionesAisladasTest(unittest.TestCase):
    def test_cola_recuperable_y_respaldo(self):
        raiz = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="siged-prueba-eliminaciones-") as carpeta:
            entorno = os.environ.copy()
            entorno.update(GESTOR_DATA_DIR=carpeta, GESTOR_SECRET_KEY="clave-ficticia-pruebas-eliminacion-123456", PYTHONPATH=str(raiz))
            subprocess.run([sys.executable, str(raiz / "tests" / "eliminaciones_casos.py")], cwd=raiz, env=entorno, check=True, timeout=180)
