"""Pruebas de validación ZIP en un proceso con datos exclusivamente ficticios."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ValidacionRespaldoAisladaTest(unittest.TestCase):
    def test_validacion_zip(self):
        raiz = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="siged-prueba-respaldo-") as carpeta:
            entorno = os.environ.copy()
            entorno.update(GESTOR_DATA_DIR=carpeta, GESTOR_SECRET_KEY="clave-ficticia-respaldo-1234567890", PYTHONPATH=str(raiz))
            subprocess.run([sys.executable, str(raiz / "tests" / "respaldo_validacion_casos.py")],
                           cwd=raiz, env=entorno, check=True, timeout=120)
